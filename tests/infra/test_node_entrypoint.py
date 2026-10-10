"""Node entrypoint: serves peer envelopes and keeps its checkpoint across restarts."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# node packages are not uv workspace members yet, so put them on the path directly
sys.path[:0] = [str(ROOT / "packages/node/peer"), str(ROOT / "packages/transport")]

from archipelago_peer import post  # noqa: E402
from archipelago_transport import Envelope  # noqa: E402


def _run(tmp, port):
    env = {
        **os.environ,
        "NODE_ID": "node-01",
        "NODE_IDS": "node-01,node-02",
        "PEER_PORT": str(port),
        "NODE_CHECKPOINT_DIR": str(tmp),
        "PYTHONPATH": os.pathsep.join(
            str(ROOT / p) for p in ("packages/node/peer", "packages/transport")
        ),
    }
    return subprocess.Popen([sys.executable, str(ROOT / "infra/node/entrypoint.py")], env=env)


def test_checkpoint_survives_restart(tmp_path):
    port = 19231
    ck = tmp_path / "checkpoint.json"
    p = _run(tmp_path, port)
    try:
        for _ in range(50):  # wait for the server, then deliver one envelope
            if (
                post(
                    f"http://127.0.0.1:{port}", Envelope.make("node-02", "node-01", 7, b"x"), 0.2, 0
                )
                == 200
            ):
                break
            time.sleep(0.1)
        for _ in range(50):
            if ck.exists() and json.loads(ck.read_text())["seen"]:
                break
            time.sleep(0.1)
    finally:
        p.kill()
        p.wait()
    assert json.loads(ck.read_text())["seen"] == {"node-02": 7}
    p = _run(tmp_path, port)
    try:
        for _ in range(50):
            if json.loads(ck.read_text())["boots"] == 2:
                break
            time.sleep(0.1)
    finally:
        p.kill()
        p.wait()
    assert json.loads(ck.read_text()) == {"boots": 2, "seen": {"node-02": 7}}
