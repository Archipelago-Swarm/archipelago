# ruff: noqa: E501  (long prose and SVG/f-string lines)
"""run_demo.py against an in-process fake API (no Docker): login, start, poll, events paging, artifacts."""

import csv
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "infra/demo"))

import run_demo  # noqa: E402

TOKEN = "dev-only-api-token-0123456789abcdef"
FIXTURE = json.loads((ROOT / "apps/web/src/fixtures/partition_run.json").read_text())


class FakeApi:
    def __init__(self, final_status="completed", polls_before_done=2, events=None):
        self.final_status, self.polls_before_done = final_status, polls_before_done
        self.events = FIXTURE if events is None else events
        self.seen: list[tuple[str, str, dict]] = []
        self.polls = 0
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body):
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _auth(self):
                return self.headers.get("Authorization") == f"Bearer {TOKEN}"

            def do_GET(self):
                fake.seen.append(("GET", self.path, dict(self.headers)))
                if self.path == "/readyz":
                    return self._send(200, {"ready": True})
                if not self._auth():
                    return self._send(401, {"detail": "bad token"})
                if self.path.startswith("/v1/runs/") and "/events" in self.path:
                    after = int(self.path.split("after_sequence=")[1].split("&")[0])
                    page = [e for e in fake.events if e["sequence"] > after][:7]
                    return self._send(
                        200, {"events": page, "latest_sequence": 99, "oldest_sequence": 1}
                    )
                if self.path.startswith("/v1/runs/"):
                    fake.polls += 1
                    done = fake.polls > fake.polls_before_done
                    return self._send(200, {"run_id": "run-x", "status": fake.final_status if done else "running",
                                            "episode": 0, "tick": fake.polls})  # fmt: skip
                self._send(404, {})

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"null")
                fake.seen.append(("POST", self.path, {**dict(self.headers), "_body": body}))
                if self.path == "/v1/login":
                    return self._send(200 if body["token"] == TOKEN else 401, {})
                if not self._auth():
                    return self._send(401, {"detail": "bad token"})
                if self.path.startswith("/v1/runs"):
                    return self._send(201, {"run_id": body["run_id"], "status": "starting"})
                self._send(404, {})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fake():
    made = []

    def make(**kw):
        f = FakeApi(**kw)
        made.append(f)
        return f

    yield make
    for f in made:
        f.close()


def test_smoke_run_collects_all_artifacts(fake, tmp_path):
    f = fake()
    api = run_demo.Api(f.url, TOKEN)
    api.wait_ready(5)
    out = run_demo.run_and_collect(
        api, "smoke", tmp_path, commit="deadbee", image_digests={"archipelago/node": "sha256:x"},
        poll_interval=0.01, log=lambda *_: None,
    )  # fmt: skip
    assert out.parent == tmp_path and (tmp_path / "LATEST").read_text().strip() == out.name
    for name in ("summary.json", "curves.csv", "peer_decisions.csv", "topology_snapshots.json",
                 "node_timeline.json", "learning_curve.svg", "coverage_return.svg",
                 "partition_timeline.svg", "run.json"):  # fmt: skip
        assert (out / name).stat().st_size > 0, name
    s = json.loads((out / "summary.json").read_text())
    assert (
        s["commit"] == "deadbee"
        and s["plan"] == "smoke"
        and s["image_digests"] == {"archipelago/node": "sha256:x"}
    )
    assert s["events"] == len(FIXTURE)  # all pages (7 per page) were fetched
    assert s["modes"]["learner"] == "peer_dqn" and s["wall_seconds"] >= 0
    assert s["seeds"]["env"] == 101
    rows = list(csv.DictReader((out / "peer_decisions.csv").open()))
    assert {r["transfer"] for r in rows if r["event"] == "decision"} == {"accepted", "rejected"}


def test_driver_uses_login_idempotency_key_and_plan_name(fake, tmp_path):
    f = fake()
    run_demo.run_and_collect(
        run_demo.Api(f.url, TOKEN), "demo", tmp_path, poll_interval=0.01, log=lambda *_: None
    )
    posts = {p: h for m, p, h in f.seen if m == "POST"}
    assert "/v1/login" in posts
    start = next(h for p, h in posts.items() if p.startswith("/v1/runs"))
    assert len(start["Idempotency-Key"]) >= 16
    cfg = start["_body"]
    assert cfg["plan"] == "demo"  # selected by body NAME; the API ignores a query parameter
    assert cfg["budgets"]["max_ticks"] == 900 and cfg["fault_schedule"][0]["start_tick"] == 300
    assert start["Authorization"] == f"Bearer {TOKEN}"


def test_bad_token_fails_at_login(fake, tmp_path):
    f = fake()
    with pytest.raises(run_demo.DemoError, match="login failed"):
        run_demo.run_and_collect(
            run_demo.Api(f.url, "wrong-token-0123456789"), "smoke", tmp_path, log=lambda *_: None
        )


def test_failed_run_still_writes_artifacts_then_raises(fake, tmp_path):
    f = fake(final_status="failed")
    with pytest.raises(run_demo.DemoError, match="failed"):
        run_demo.run_and_collect(
            run_demo.Api(f.url, TOKEN), "smoke", tmp_path, poll_interval=0.01, log=lambda *_: None
        )
    (run_dir,) = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert json.loads((run_dir / "summary.json").read_text())["events"] == len(FIXTURE)


def test_completed_run_without_events_is_an_error(fake, tmp_path):
    f = fake(events=[])
    with pytest.raises(run_demo.DemoError, match="no events"):
        run_demo.run_and_collect(
            run_demo.Api(f.url, TOKEN), "smoke", tmp_path, poll_interval=0.01, log=lambda *_: None
        )


def test_wait_ready_times_out_with_the_last_error():
    api = run_demo.Api("http://127.0.0.1:1", TOKEN, timeout=0.2)
    with pytest.raises(run_demo.DemoError, match="/readyz not ready"):
        api.wait_ready(0.5, interval=0.1)


def test_compose_command_uses_local_profile_and_dev_env_files():
    cmd = run_demo.compose_cmd("up", "-d")
    assert cmd[:4] == ["docker", "compose", "-p", "archipelago-demo"]
    assert cmd.count("--env-file") == 2 and cmd[-2:] == ["up", "-d"]
    assert cmd[cmd.index("--profile") + 1] == "local"
    env = run_demo.compose_env("demo", "abc")
    assert (
        env["DEMO_PLAN"] == "demo"
        and env["DEMO_MAX_TICKS"] == "900"
        and env["ARCHIPELAGO_COMMIT"] == "abc"
    )


def test_unknown_plan_is_rejected():
    with pytest.raises(run_demo.DemoError):
        run_demo.load_plan("nope")


def test_dev_token_comes_from_local_env():
    t = run_demo.read_env_file(run_demo.ENV_FILES[1])["ARCHIPELAGO_API_TOKEN"]
    assert len(t) >= 16 and "dev-only" in t
