"""Real node processes (python -m archipelago_noderuntime) for tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from support import PEER_TOKEN, TOKEN, Client

_ROOT = Path(__file__).resolve().parents[2]
_PKGS = [
    "packages/node/runtime",
    "packages/node/peer",
    "packages/node/learner",
    "packages/transport",
    "packages/contracts/src",
    "packages/learning",
    "packages/sim",
]


class NodeProc:
    def __init__(self, tmp, node_id="node-01", node_ids=None, **env):
        self.tmp, self.node_id = Path(tmp), node_id
        self.env = {
            "PYTHONPATH": os.pathsep.join(str(_ROOT / p) for p in _PKGS),
            "PATH": os.environ.get("PATH", ""),
            "NODE_ID": node_id,
            "NODE_IDS": ",".join(node_ids or [node_id]),
            "NODE_CONTROL_TOKEN": TOKEN,
            "PEER_TOKEN": PEER_TOKEN,
            "EXCHANGE_EVERY_TICKS": "0",
            "NODE_CHECKPOINT_DIR": str(self.tmp / node_id),
            "PEER_PORT": "0",
            "CONTROL_PORT": "0",
            "WORLD_SIZE": "8",
            "WORLD_N_TARGETS": "2",
            "WORLD_MAX_TICKS": "40",
            "VALIDATION_SEEDS": "7001,7002",
            "REPLAY_CAPACITY": "500",
            "BATCH_SIZE": "8",
            "TELEMETRY_INTERVAL": "0.05",
        }
        self.env.update({k: str(v) for k, v in env.items()})
        self.proc: subprocess.Popen | None = None
        self.info: dict = {}
        self.client: Client | None = None

    def start(self) -> NodeProc:
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "archipelago_noderuntime"],
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(self.tmp),
        )
        assert self.proc.stdout is not None and self.proc.stderr is not None
        # No ready line (hung startup, e.g. Windows) must fail fast, not block the suite.
        box: list[str] = []
        t = threading.Thread(target=lambda: box.append(self.proc.stdout.readline()), daemon=True)
        t.start()
        t.join(60)
        if t.is_alive():
            self.proc.kill()
            raise RuntimeError("node produced no ready line within 60s")
        line = box[0]
        if not line:
            raise RuntimeError("node exited early: " + self.proc.stderr.read())
        self.info = json.loads(line)
        self.client = Client(self.info["control_url"])
        return self

    def kill(self) -> None:
        assert self.proc is not None
        self.proc.kill()  # SIGKILL: no shutdown hooks, no final checkpoint
        self.proc.wait()

    def terminate(self) -> int:
        assert self.proc is not None
        self.proc.terminate()
        return self.proc.wait(timeout=30)

    def close(self) -> None:
        if self.proc is None:
            return
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        for f in (self.proc.stdout, self.proc.stderr):
            if f:
                f.close()
