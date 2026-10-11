# ruff: noqa: E501  (long prose and table lines)
"""T30 live pilot: real processes, real optimizer updates, real peer exchange (no Docker, no cloud).

Pre-registered in experiments/prereg/T30.yaml. One command reproduces everything:

    uv run python experiments/t30_live.py all

``arm fleet`` / ``arm isolated`` each start a coordinator and four node processes (tests/e2e/procs.py),
run the plan (training, validation checkpoints, frozen test seeds 200-219), SIGKILL one node mid-training
and restart it, and write raw evidence to experiments/out/T30/raw/<arm>/. ``analyze`` turns the raw
evidence of both arms into results.json, summary.md, curves.csv, decisions.jsonl and spool_excerpt.jsonl.
``all`` runs both arms as two concurrent subprocesses, then analyzes. ``--smoke`` runs a tiny version into
experiments/out/T30_smoke (never touches seeds 200-219).
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
PREREG = ROOT / "experiments" / "prereg" / "T30.yaml"
OUT = ROOT / "experiments" / "out" / "T30"
SMOKE_OUT = ROOT / "experiments" / "out" / "T30_smoke"
FROZEN_TEST = tuple(range(200, 220))
POLL_S = 1.0
RUN_TIMEOUT_S = 75 * 60

LEAN_COUNTERS = (
    "offers_sent", "offers_cut", "offers_received", "received_cut", "exchanges",
    "decisions_accepted", "decisions_rejected", "decisions_window_limit", "summaries_sent",
    "summaries_cut", "summaries_received", "summaries_received_cut", "summaries_applied",
    "feedbacks", "feedback_deadline_missed", "checkpoints", "spool_errors",
)  # fmt: skip


def load_prereg() -> dict:
    return yaml.safe_load(PREREG.read_text())


def arm_config(pre: dict, arm: str, smoke: bool) -> dict:
    """Plan pieces for one arm; ``smoke`` shrinks the plan (and moves the test seeds off 200-219)."""
    from t30_cluster import ALL_PAIRS

    faults = []
    for w in pre["arms"][arm]["fault_schedule"]:
        links = ALL_PAIRS if w["cut_links"] == "ALL_PAIRS" else w["cut_links"]
        faults.append({**w, "cut_links": links})
    episodes = [dict(e) for e in pre["plan"]["episodes"]]
    kill = dict(pre["fault_injection"]["sigkill"])
    if smoke:
        episodes = [
            {"kind": "train", "seed": 1000, "count": 3},
            {"kind": "validation", "seed": 100, "count": 1},
            {"kind": "train", "seed": 1003, "count": 2},
            {"kind": "test", "seed": 5200, "count": 2},
        ]
        kill["at_episode_index"], kill["at_tick_min"] = 4, 30
    else:
        assert [e for e in episodes if e["kind"] == "test"][0]["seed"] == FROZEN_TEST[0]
    return {"faults": faults, "episodes": episodes, "kill": kill}


# ------------------------------------------------------------------------------------ one arm
def lean_status(st: dict) -> dict:
    k = st["counters"]
    return {
        "boot_id": st["boot_id"], "episode": st["episode"], "tick": st["tick"], "mode": st["mode"],
        "train_steps": st["train_steps"], "replay_size": st["replay_size"],
        "policy_version": st["policy_version"], "policy_sha256": st["policy_sha256"],
        "epsilon": st["epsilon"], "peers": st["peers"],
        "checkpoint_generation": st["checkpoint_generation"],
        "sequence_ceiling": st["sequence_ceiling"], "telemetry_backlog": st["telemetry_backlog"],
        "counters": {c: k[c] for c in LEAN_COUNTERS},
    }  # fmt: skip


def checkpoint_current(c, node: str) -> dict:
    f = c.ckpt_dir(node) / "CURRENT"
    try:
        cur = json.loads(f.read_text())
    except (OSError, ValueError):
        return {"error": "no CURRENT"}
    gen = c.ckpt_dir(node) / f"gen-{cur['generation']}"
    try:
        counters = json.loads((gen / "counters.json").read_text())
        steps = counters.get("learner", counters).get("steps")
    except (OSError, ValueError, AttributeError):
        steps = None
    return {"current": cur, "counters_json_steps": steps}


def run_arm(arm: str, out: Path, smoke: bool) -> int:
    from t30_cluster import LiveCluster

    pre = load_prereg()
    cfg = arm_config(pre, arm, smoke)
    raw = out / "raw" / arm
    if raw.exists() and (raw / "DONE").exists():
        raise SystemExit(f"{raw} already holds a finished {arm} run; the test seeds are used once")
    shutil.rmtree(raw, ignore_errors=True)
    raw.mkdir(parents=True)
    tmp = Path(tempfile.mkdtemp(prefix=f"t30-{arm}-"))
    run_id = f"t30-{arm}" + ("-smoke" if smoke else "")
    kill = cfg["kill"]
    c = LiveCluster(
        tmp, exchange_every=pre["plan"]["node_config"]["exchange_every_ticks"],
        no_peer_urls=arm == "isolated",
    )  # fmt: skip
    samples = (raw / "samples.jsonl").open("w")
    kill_rec: dict = {"planned": kill, "done": False}
    t0 = time.monotonic()
    status = "unknown"
    try:
        c.start()
        c.start_run(run_id, episodes=cfg["episodes"], fault_schedule=cfg["faults"], seed=1)
        t0 = time.monotonic()
        while True:
            view = c.run_status(run_id)
            nodes: dict = {}
            for n in c.nodes:
                try:
                    nodes[n] = lean_status(c.node_status(n))
                except Exception as e:  # noqa: BLE001 - a killed node is expected to be unreachable
                    nodes[n] = {"error": repr(e)}
            samples.write(
                json.dumps({
                    "t": round(time.monotonic() - t0, 2), "status": view["status"],
                    "episode": view["episode"], "kind": view["episode_kind"], "tick": view["tick"],
                    "fault_phase": view["fault_phase"], "nodes": nodes,
                }) + "\n"
            )  # fmt: skip
            samples.flush()
            if (
                not kill_rec["done"]
                and view["status"] == "running"
                and view["episode"] == kill["at_episode_index"]
                and view["tick"] >= kill["at_tick_min"]
            ):
                kill_rec = do_kill(c, kill, view, t0)
            if view["status"] in ("completed", "failed", "interrupted"):
                status = view["status"]
                break
            if time.monotonic() - t0 > RUN_TIMEOUT_S:
                status = "timeout"
                break
            time.sleep(POLL_S)
        final = c.run_status(run_id)
        wait_telemetry_drained(c)
        collect(c, raw, run_id, final, kill_rec)
        (raw / "DONE").write_text(json.dumps({"status": status, "wall_s": time.monotonic() - t0}))
        print(f"[{arm}] {status} in {time.monotonic() - t0:.0f}s", flush=True)
        return 0 if status == "completed" else 1
    except BaseException:
        print(c.logs_text(), file=sys.stderr)
        raise
    finally:
        samples.close()
        c.close()
        shutil.copytree(c.logs, raw / "logs", dirs_exist_ok=True)
        shutil.rmtree(tmp, ignore_errors=True)


def do_kill(c, kill: dict, view: dict, t0: float) -> dict:
    """SIGKILL ``node`` mid-episode and restart it on the same checkpoint dir and ports."""
    node = kill["node"]
    pre = c.node_status(node)
    rec = {
        "done": True, "planned": kill, "node": node, "trigger": {"episode": view["episode"], "tick": view["tick"]},
        "t_kill": round(time.monotonic() - t0, 2), "pre": lean_status(pre),
        "pre_restore": pre["restore"], "ckpt_pre": checkpoint_current(c, node),
    }  # fmt: skip
    pid_before = c.nodes[node].popen.pid
    started = time.monotonic()
    c.restart_node(node, kill=True)
    post = c.node_status(node)
    rec |= {
        "restart_seconds": round(time.monotonic() - started, 2), "post": lean_status(post),
        "post_restore": post["restore"], "ckpt_post": checkpoint_current(c, node),
        "pid_before": pid_before, "pid_after": c.nodes[node].popen.pid,
    }  # fmt: skip
    return rec


def wait_telemetry_drained(c, timeout: float = 40.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if all(c.node_status(n)["telemetry_backlog"] == 0 for n in c.nodes):
            return
        time.sleep(0.5)


def collect(c, raw: Path, run_id: str, final: dict, kill_rec: dict) -> None:
    (raw / "run_status.json").write_text(json.dumps(final, indent=1))
    (raw / "kill.json").write_text(json.dumps(kill_rec, indent=1))
    full = {n: c.node_status(n) for n in c.nodes}
    (raw / "node_status_final.json").write_text(json.dumps(full))
    records = c.sink.records()
    with gzip.open(raw / "telemetry.jsonl.gz", "wt") as f:
        for r in records:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    # coordinator events (curves) and per-episode replays (outcomes re-executed in analyze)
    with gzip.open(raw / "coordinator_events.jsonl.gz", "wt") as f:
        for e in c.events(run_id):
            f.write(json.dumps(e, separators=(",", ":")) + "\n")
    rep_root = c.tmp / "coordinator" / "replays"
    src = next(p for p in rep_root.iterdir() if p.name.startswith(run_id))
    shutil.copytree(src, raw / "replays")
    for n in c.nodes:  # node-local state: checkpoint pointer and telemetry spool, no weights
        d = raw / "node_local" / n
        d.mkdir(parents=True)
        (d / "ckpt_current.json").write_text(json.dumps(checkpoint_current(c, n)))
        spool = c.ckpt_dir(n) / "telemetry"
        (d / "spool_state.json").write_text((spool / "state.json").read_text())
        segs = sorted(spool.glob("seg-*.jsonl"), key=lambda p: int(p.stem.split("-")[1]))
        (d / "spool_segments.json").write_text(json.dumps([p.name for p in segs]))
        with gzip.open(d / "spool.jsonl.gz", "wt") as f:
            for p in segs:
                f.write(p.read_text())


# ----------------------------------------------------------------------------------- driver
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("cmd", choices=["arm", "analyze", "all"])
    ap.add_argument("arm_name", nargs="?", choices=["fleet", "isolated"])
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args(argv)
    out = SMOKE_OUT if a.smoke else OUT
    if a.cmd == "arm":
        assert a.arm_name, "arm needs fleet|isolated"
        return run_arm(a.arm_name, out, a.smoke)
    if a.cmd == "all":
        extra = ["--smoke"] if a.smoke else []
        procs = [
            subprocess.Popen([sys.executable, __file__, "arm", name, *extra])
            for name in ("fleet", "isolated")
        ]
        codes = [p.wait() for p in procs]
        print(f"arm exit codes (fleet, isolated): {codes}", flush=True)
        import t30_report

        t30_report.analyze(out, a.smoke)
        return 1 if any(codes) else 0
    import t30_report

    t30_report.analyze(out, a.smoke)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
