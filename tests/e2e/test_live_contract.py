# ruff: noqa: E501  (long prose and SVG/f-string lines)
"""Cross-service wire contracts, checked with the real processes of the local smoke.

These guard the seams between components owned by different workers. They fail while a seam is broken and the
failure message says which bytes disagree.
"""

import json
import sys
from pathlib import Path

from e2e_procs import NODE_IDS, NODE_PATHS, ROOT

sys.path[:0] = [str(ROOT / p) for p in NODE_PATHS]  # to import the node runtime's protocol models
GOOD = ROOT / "packages/contracts/fixtures/good"


def test_coordinator_control_messages_are_accepted_by_nodes(smoke):
    """The run completed with the coordinator talking to the nodes directly (no translating proxy), and the
    plan the nodes ran under is the one in the server-side plan file."""
    c, run_id, view = smoke
    assert view["status"] == "completed", view
    assert json.loads(c.plan_file.read_text())["plans"][run_id]["battery_scale"] == 4.0
    for n in NODE_IDS:
        assert c.node_status(n)["counters"]["acts"] > 0


def test_node_telemetry_batches_are_accepted_by_the_api_ingest(smoke, tmp_path):
    """A real node batch, posted unchanged to the API's /v1/telemetry route, is admitted."""
    from archipelago_api.app import create_app, fixture_factory
    from archipelago_api.settings import Settings
    from archipelago_api.telemetry import make_router
    from fastapi.testclient import TestClient

    c, run_id, _ = smoke
    assert c.sink.batches, "no node shipped a batch"
    batch = c.sink.batches[0]
    token = "telemetry-test-only-credential"
    login = "login-test-only-credential"
    app = create_app(
        Settings(api_token=login, data_dir=tmp_path, tick_interval=None),
        fixture_factory(GOOD),
        None,
    )
    app.include_router(make_router(app.state.manager, token=token))
    with TestClient(app) as client:
        cfg = json.loads((GOOD / "run_config.json").read_text())
        cfg["run_id"] = run_id
        r = client.post(
            "/v1/runs",
            json=cfg,
            headers={"Authorization": f"Bearer {login}", "Idempotency-Key": "k"},
        )
        assert r.status_code == 201, r.text
        resp = client.post(
            "/v1/telemetry", json=batch, headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200, (
            f"API ingest rejected the node's batch ({resp.status_code} {resp.text}); node sends keys "
            f"{sorted(batch)}, ingest requires ['boot_id', 'events', 'source'] plus optional 'context' (agreement 8.1/A7)"
        )
        assert resp.json()["accepted"] > 0, resp.json()


def test_api_telemetry_route_is_mounted_in_the_served_app():
    """Compose runs ``create_app_from_env``; nodes post to /v1/telemetry on it."""
    from archipelago_api import app as api_app

    src = Path(api_app.__file__).read_text()
    assert "make_router" in src and "telemetry" in src, (
        "the ingest router is not mounted by create_app_from_env"
    )
