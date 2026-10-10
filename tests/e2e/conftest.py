# ruff: noqa: E501  (long prose and SVG/f-string lines)
"""Fixtures for the no-Docker live smoke. ``procs.py`` is loaded under the unique module name ``e2e_procs``
because tests/noderuntime/procs.py is also called ``procs`` and pytest puts both directories on sys.path."""

import importlib.util
import sys
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("e2e_procs", Path(__file__).with_name("procs.py"))
assert _spec and _spec.loader
e2e_procs = importlib.util.module_from_spec(_spec)
sys.modules["e2e_procs"] = e2e_procs
_spec.loader.exec_module(e2e_procs)

SMOKE_EPISODES = [
    {"kind": "train", "seed": 11},
    {"kind": "train", "seed": 12},
    {"kind": "validation", "seed": 21},
    {"kind": "test", "seed": 31},
]
SMOKE_CUT = [{"start_tick": 20, "end_tick": 50, "cut_links": e2e_procs.HALVES_CUT}]


@pytest.fixture
def make_cluster(tmp_path_factory, request):
    """Factory: ``make_cluster(ticks=80, **node_env)`` -> started Cluster. Prints process logs when the test fails."""
    made = []

    def make(ticks=80, tick_interval_s=0.0, **node_env):
        c = e2e_procs.Cluster(tmp_path_factory.mktemp("live"), ticks=ticks, **node_env)
        made.append(c)
        return c.start(tick_interval_s)

    failed_before = request.session.testsfailed
    yield make
    for c in made:
        if request.session.testsfailed > failed_before:
            print(c.logs_text(), file=sys.stderr)
        c.close()


@pytest.fixture(scope="module")
def smoke(tmp_path_factory, request):
    """One shared 4-episode run (2 train, validation, test) with a cut window; returns (cluster, run_id, final view)."""
    c = e2e_procs.Cluster(tmp_path_factory.mktemp("live-smoke"), ticks=80)
    failed_before = request.session.testsfailed
    try:
        c.start()
        c.start_run("e2e-smoke", episodes=SMOKE_EPISODES, fault_schedule=SMOKE_CUT, seed=1)
        view = c.wait_run("e2e-smoke", timeout=240)
        yield c, "e2e-smoke", view
    finally:
        if request.session.testsfailed > failed_before:
            print(c.logs_text(), file=sys.stderr)
        c.close()
