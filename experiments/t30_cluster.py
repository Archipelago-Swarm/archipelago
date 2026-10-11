# ruff: noqa: E501  (long prose and table lines)
"""T30: the no-Docker live cluster (real coordinator + four real node processes) at the T37 world size.

Thin subclass of ``tests/e2e/procs.py::Cluster`` (loaded by path, as tests/e2e/conftest.py does). It only
changes configuration: a 16x16 world with 8 targets and 150-tick episodes (the T37 geometry, four drones
instead of two), the T37 ids in the node environment (so a SIGKILLed node restarts with the identity its
checkpoint carries), the exchange cadence and node-private gate seeds in the Plan. No product code is touched.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("t30_e2e_procs", ROOT / "tests" / "e2e" / "procs.py")
assert _spec and _spec.loader
procs = importlib.util.module_from_spec(_spec)
sys.modules["t30_e2e_procs"] = procs
_spec.loader.exec_module(procs)

NODE_IDS: list[str] = procs.NODE_IDS
SIZE, N_TARGETS, MAX_TICKS = 16, 8, 150
STARTS_16 = {"node-01": (0, 0), "node-02": (15, 0), "node-03": (0, 15), "node-04": (15, 15)}
HALVES = {"node-01": 0, "node-02": 0, "node-03": 1, "node-04": 1}
ALL_PAIRS = [[a, b] for i, a in enumerate(NODE_IDS) for b in NODE_IDS[i + 1 :]]
GATE_SEEDS = [9001, 9002, 9003]  # node-private model selection; disjoint from every plan seed


class LiveCluster(procs.Cluster):
    def __init__(
        self, tmp: Path, exchange_every: int = 25, no_peer_urls: bool = False, **node_env: str
    ) -> None:
        procs.STARTS = STARTS_16  # run_body reads the module global at call time
        self.exchange_every = exchange_every
        self.no_peer_urls = no_peer_urls
        super().__init__(tmp, ticks=MAX_TICKS, ids="t37", **node_env)

    def _node(self, n: str):
        p = super()._node(n)
        p.env.update(
            WORLD_SIZE=str(SIZE), WORLD_N_TARGETS=str(N_TARGETS), WORLD_MAX_TICKS=str(MAX_TICKS),
            VALIDATION_MAX_TICKS=str(MAX_TICKS), REPLAY_CAPACITY="50000", BATCH_SIZE="32",
            TARGET_EVERY="50", ENCODER_FAMILY=procs.T37_ENCODER_FAMILY, REWARD_ID=procs.T37_REWARD,
            LEARNER_SCHEDULE_ID=procs.T37_SCHEDULE, DOUBLE_DQN="1",
        )  # fmt: skip
        if (
            self.no_peer_urls
        ):  # isolated control: no node knows any peer address (see prereg amendment 1)
            p.env["PEER_URLS"] = ""
        return p

    def start_coordinator(self, tick_interval_s: float = 0.0) -> None:
        """Same process and environment as ``Cluster.start_coordinator`` but the 16x16 world."""
        urls = ",".join(f"{n}={self.coord_node_url(n)}" for n in NODE_IDS)
        env = procs.child_env(
            procs.COORD_PATHS,
            COORDINATOR_TOKEN=procs.COORD_TOKEN, COORDINATOR_ADMIN_TOKEN=procs.ADMIN_TOKEN,
            NODE_CONTROL_TOKEN=procs.CONTROL_TOKEN, COORDINATOR_DATA_DIR=str(self.tmp / "coordinator"),
            COORDINATOR_NODE_URLS=urls, ARCHIPELAGO_ENV="production", ARCHIPELAGO_COMMIT="t30",
            COORDINATOR_WORLD_KWARGS=json.dumps({"size": SIZE, "n_targets": N_TARGETS}),
            COORDINATOR_PLAN_FILE=str(self.plan_file),
            COORDINATOR_TICK_INTERVAL_S=str(tick_interval_s),
        )  # fmt: skip
        argv = [sys.executable, "-m", "archipelago_coordinator", "--host", "127.0.0.1",
                "--port", str(self.coord_port)]  # fmt: skip
        self.coord = procs.Proc("coordinator", argv, env, self.logs, self.tmp)
        self.coord.start()

    def id_plan(self) -> dict[str, Any]:
        base = super().id_plan()
        base["node_config"] = {
            **base["node_config"], "exchange_every_ticks": self.exchange_every,
            "gate_seeds": GATE_SEEDS,
        }  # fmt: skip
        return base
