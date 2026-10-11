"""T38 acceptance (1): numeric parity of the node-side v2 encoder with the T37 NumPy harness.

The reference is ``experiments/protocol_harness.flat`` on a ``GridWorld`` (the encoder the study
trained on). The node side sees only what a live node sees: contract ``Observation`` records (pose
at cell centre, crop, battery) and, for the shared id, visited-cell summaries that went through the
real wire codec. The two vectors must be identical element for element at every tick, for several
seeds, both ids. A golden file of hashes also pins the harness output itself.

Not covered by parity (a documented deviation): the study's InfoBus also merged peers' MAP cells into
each drone's buffer, so its crop and frontier saw them. The live world has no such merge, so this test
runs the harness with the bus's visit half only (``visit_bus``).

Regenerate the golden file (only after a deliberate, reviewed change of the encoder definition):
    PYTHONPATH=packages/learning:packages/sim:packages/contracts/src:packages/node/runtime:\
packages/transport:experiments:tests/noderuntime python tests/noderuntime/test_v2_parity.py
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments"))

import protocol_harness as H  # noqa: E402
from archipelago_contracts.models import Observation  # noqa: E402
from archipelago_learning import encoders  # noqa: E402
from archipelago_noderuntime import summary  # noqa: E402
from archipelago_noderuntime.encoder import encode_observation  # noqa: E402
from support import obs_json  # noqa: E402

GOLDEN = Path(__file__).with_name("golden_v2_parity.json")
SEEDS = (3, 11, 42, 77, 123)
TICKS = 70
SIZE, RADIUS = H.ENV_KW["size"], 2
IDS = {
    H.V2_LOCAL: encoders.get(f"grid-flat-v2-visits-s{SIZE}-r{RADIUS}"),
    H.V2_SHARED: encoders.get(f"grid-flat-v2-visits-shared-s{SIZE}-r{RADIUS}"),
}


def visit_bus(world) -> None:
    """The visits half of experiments' InfoBus: every living drone learns every other's stood-on
    cells (links up). No map cells are merged."""
    names = sorted(world.agents)
    sent = {s: set(world.drones[s].visits) for s in names}
    for src in names:
        for dst in names:
            if src != dst:
                world.drones[dst].peer_visits |= sent[src]


def contract_obs(run_id: str, agent: str, tick: int, raw: dict) -> Observation:
    j = obs_json(run_id, agent, tick, raw)
    j["pose"]["x"] += 0.5  # Sim2DAdapter reports the cell centre
    j["pose"]["y"] += 0.5
    return Observation.model_validate(j)


def run_pair(seed: int, obs_id: str, ticks: int = TICKS):
    """Yield (tick, agent, harness vector, node vector) over one random-action episode."""
    enc = IDS[obs_id]
    env = H.make_env(obs_id, "rew-v1")
    env.reset(seed=seed)
    w = env.world
    mems = {a: enc.new_memory() for a in env.possible_agents}
    rng = random.Random(seed)
    tick = 0
    while env.agents and tick <= ticks:
        if obs_id == H.V2_SHARED:
            visit_bus(w)
        raws = {a: w.observe(a) for a in env.agents}
        for a in env.agents:  # node side: observe first, then exchange real summaries, then encode
            mems[a].observe(tick, *raws[a]["pose"], raws[a]["crop"])
        if enc.shared:
            for a in env.agents:
                payload = summary.encode(
                    a, "run-p", 0, tick, enc.id, SIZE, mems[a].own_cells()
                )
                for b in env.agents:
                    if b != a:
                        s = summary.decode(payload, expect_size=SIZE, expect_encoder=enc.id)
                        mems[b].merge_peer(a, s.cells)
        for a in env.agents:
            want = H.flat(env, a)
            got = encode_observation(enc, contract_obs("run-p", a, tick, raws[a]), mems[a], tick)
            yield tick, a, want, got
        env.step({a: rng.randrange(5) for a in env.agents})
        tick += 1


def digest(vectors) -> str:
    h = hashlib.sha256()
    for v in vectors:
        h.update(np.ascontiguousarray(v, np.float32).tobytes())
    return h.hexdigest()


@pytest.mark.parametrize("obs_id", [H.V2_LOCAL, H.V2_SHARED])
@pytest.mark.parametrize("seed", SEEDS)
def test_node_encoder_equals_the_numpy_harness_encoder_at_every_tick(seed, obs_id):
    n = 0
    for tick, agent, want, got in run_pair(seed, obs_id):
        assert got.dtype == np.float32 and got.shape == want.shape == (IDS[obs_id].obs_dim,)
        np.testing.assert_array_equal(got, want, err_msg=f"{obs_id} seed={seed} {agent} t={tick}")
        n += 1
    assert n >= 2 * 40, "episodes ended too early to mean anything"


def test_dimensions_and_layout_match_the_adoption_note():
    assert IDS[H.V2_LOCAL].obs_dim == 57 and IDS[H.V2_SHARED].obs_dim == 82
    assert H.obs_dim(H.V2_LOCAL) == 57 and H.obs_dim(H.V2_SHARED) == 82
    # shared = local + 25 peer flags, in that order
    for (_, _, w_loc, _), (_, _, w_sh, g_sh) in zip(
        run_pair(3, H.V2_LOCAL, 10), run_pair(3, H.V2_SHARED, 10), strict=True
    ):
        np.testing.assert_array_equal(g_sh[:57], w_loc)
        np.testing.assert_array_equal(g_sh[:57], w_sh[:57])


def test_peer_flags_are_non_trivial_in_the_fixtures():
    """Guard against a vacuous pass: the shared fixtures must actually contain peer flags,
    own visit counts above 1 and frontier fractions strictly inside (0, 1)."""
    peer = visits = frontier = 0
    for seed in SEEDS:
        for _, _, want, _ in run_pair(seed, H.V2_SHARED):
            peer += int(want[57:].sum() > 0)
            visits += int((want[28:53] > 0.25).any())
            frontier += int(((want[53:57] > 0) & (want[53:57] < 1)).any())
    assert peer > 20 and visits > 20 and frontier > 20, (peer, visits, frontier)


def golden_doc() -> dict:
    return {
        f"{obs_id}|seed={seed}": digest(w for *_, w, _ in run_pair(seed, obs_id))
        for obs_id in (H.V2_LOCAL, H.V2_SHARED)
        for seed in SEEDS
    }


def test_golden_hashes_pin_both_the_harness_and_the_node_encoder():
    golden = json.loads(GOLDEN.read_text())
    assert set(golden) == {f"{o}|seed={s}" for o in IDS for s in SEEDS}
    for key, want in golden.items():
        obs_id, seed = key.split("|seed=")
        pairs = list(run_pair(int(seed), obs_id))
        assert digest(w for *_, w, _ in pairs) == want, f"harness drifted: {key}"
        assert digest(g for *_, g in pairs) == want, f"node encoder differs: {key}"


if __name__ == "__main__":  # regenerate the golden file
    GOLDEN.write_text(json.dumps(golden_doc(), indent=1, sort_keys=True) + "\n")
    print("wrote", GOLDEN)
