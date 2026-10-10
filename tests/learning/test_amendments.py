"""Agreement amendments A1 (window limit), A3/A17 (sequence allocator, checkpoint constants), A6."""

import numpy as np
import pytest
from archipelago_contracts.models import Observation
from archipelago_learning import (
    Learner,
    OfferWindow,
    PeerError,
    TorchLearner,
    decode,
    encode,
    encoders,
    offer,
)
from archipelago_learning import checkpoint as ck
from archipelago_learning.compat import encoder_sha256
from archipelago_sim.pz import GridParallelEnv
from torch_support import fill, numpy_learner, score, torch_learner, trained_torch

# ---------------- A6 encoders ----------------


def _contract_obs(raw: dict) -> Observation:
    x, y = raw["pose"]
    return Observation(
        schema_version="0.1.0",
        event_id="e-1",
        run_id="r-1",
        source_node_id="node-0",
        sim_tick=0,
        emitted_at_utc="2026-10-10T00:00:00Z",
        sequence=0,
        crop=raw["crop"],
        known_mask=raw["known_mask"],
        pose={"x": x + 0.5, "y": y + 0.25, "z": 0.0},  # sub-cell offsets must floor away
        battery=raw["battery"],
        visible_markers=[],
    )


@pytest.mark.parametrize("size", [8, 16])
def test_both_entry_points_match_env_flat_at_sizes_8_and_16(size):
    env = GridParallelEnv(size=size, n_agents=2, n_targets=2, max_ticks=30)
    enc = encoders.get(encoders.encoder_id(size, env.world.radius))
    flat, _ = env.reset(seed=3)
    checked = 0
    for t in range(6):
        for a in env.world.agents:
            raw = env.world.observe(a)
            want = flat[a].copy()
            want[-3:-1] /= size  # sim _flat leaves pose in cells; encoder normalises
            assert env._flat(raw).shape == (enc.obs_dim,)
            np.testing.assert_array_equal(enc.encode_raw(raw), want)
            np.testing.assert_array_equal(enc.encode_observation(_contract_obs(raw)), want)
            checked += 1
        if not env.agents:
            break
        flat, *_ = env.step({a: (t + i) % 5 for i, a in enumerate(env.agents)})
    assert checked >= 2


def test_encoder_hash_changes_with_geometry_and_header_carries_id_and_hash():
    ids = [encoders.encoder_id(s, r) for s in (8, 16) for r in (1, 2)]
    hashes = {encoder_sha256(i) for i in ids}
    assert len(hashes) == 4
    for i in ids:
        assert encoder_sha256(i) == encoders.get(i).sha256
    for L in (Learner("a", 28, 5, encoder=ids[1]), TorchLearner("b", 28, 5, encoder=ids[1])):
        assert L.encoder == ids[1] and L.encoder_sha256 == encoder_sha256(ids[1])
        assert decode(encode(L), L)[0]["encoder_sha256"] == L.encoder_sha256
    with pytest.raises(ValueError):
        encoders.get("grid-flat-v0")


def test_mismatched_encoder_id_rejected_with_named_reason_across_backends():
    a = numpy_learner("a")
    b = TorchLearner("b", 3, 3, encoder="grid-flat-v1-s16-r2")
    with pytest.raises(PeerError, match="incompatible encoder: 'grid-flat-v1-s16-r2'"):
        decode(encode(b), a)
    ev = offer(a, encode(b), score)
    assert not ev["accepted"] and "incompatible encoder" in ev["reason"]
    with pytest.raises(PeerError, match="incompatible encoder"):
        decode(encode(a), b)


# ---------------- A1 window limit ----------------


def _teachers(n):
    return [encode(trained_torch(0, f"t{i}")) for i in range(n)]


def test_second_candidate_in_window_rejected_without_evaluation():
    rx = numpy_learner("rx", 5)
    fill(rx)
    calls = []

    def ev_fn(p):
        calls.append(1)
        return score(p)

    w = OfferWindow()
    p1, p2, p3 = _teachers(3)
    first = offer(rx, p1, ev_fn, window=w)
    assert first["accepted"]
    n = len(calls)
    for p in (p2, p3):
        e = offer(rx, p, ev_fn, window=w)
        assert not e["accepted"] and e["reason"] == "window_limit"
        assert "candidate_score" not in e and "validation_seconds" not in e
    assert len(calls) == n and rx.version == first["new_version"]
    assert w.offers == 3 and w.accepted == 1
    offer(rx, p2, ev_fn, window=OfferWindow())
    assert len(calls) > n  # a fresh window evaluates again


def test_current_score_evaluated_at_most_once_per_window():
    rx = torch_learner("rx", 5)
    fill(rx)
    w = OfferWindow()
    seen = []

    def ev_fn(p):
        seen.append(p)
        return 0.0 if len(seen) == 1 else -1.0  # nothing is accepted

    own_before = rx.params_numpy()
    for p in _teachers(3):
        assert not offer(rx, p, ev_fn, window=w)["accepted"]
    assert w.evaluations == 4 and len(seen) == 4  # 1 current + 3 candidates
    assert all(np.array_equal(seen[0][k], own_before[k]) for k in own_before)
    # without a window the current policy is evaluated per offer
    seen.clear()
    for p in _teachers(3):
        offer(rx, p, ev_fn)
    assert len(seen) == 6


def test_window_is_unaffected_by_rejections_then_accepts_one():
    rx = numpy_learner("rx", 5)
    fill(rx)
    w = OfferWindow()
    bad = encode(numpy_learner("bad", 9))  # untrained: not better, rejected on score
    good = encode(trained_torch(0, "good"))
    assert offer(rx, bad, score, margin=0.5, window=w)["reason"] != "window_limit"
    assert offer(rx, good, score, window=w)["accepted"]
    assert offer(rx, bad, score, window=w)["reason"] == "window_limit"


# ---------------- A3 sequence allocator ----------------


class Crash(RuntimeError):
    pass


class KillAt(ck.DurableIO):
    def __init__(self, op):
        self.op, self.armed = op, False

    def hook(self, op, path):
        if self.armed and op == self.op:
            raise Crash(op)


def test_sequences_monotonic_and_block_reserved_before_use(tmp_path):
    f = tmp_path / "seq.json"
    a = ck.SequenceAllocator(f)
    got = [a.next() for _ in range(2500)]
    assert got == list(range(2500)) and a.ceiling == 3000
    import json

    assert json.loads(f.read_bytes())["ceiling"] == 3000


def test_no_number_reissued_after_restart(tmp_path):
    f = tmp_path / "s" / "seq.json"
    a = ck.SequenceAllocator(f)
    first = [a.next() for _ in range(1500)]
    b = ck.SequenceAllocator(f)  # crash: no shutdown, state is whatever was persisted
    second = [b.next() for _ in range(5)]
    assert min(second) > max(first) and second == sorted(second)
    assert b.ceiling == 3000


@pytest.mark.parametrize("op", ["write_tmp", "rename", "fsync_dir"])
def test_crash_during_reservation_never_reissues(tmp_path, op):
    f = tmp_path / "seq.json"
    io = KillAt(op)
    a = ck.SequenceAllocator(f, io=io)
    issued = [a.next() for _ in range(1000)]  # exhausts the first block
    io.armed = True
    with pytest.raises(Crash):
        a.next()  # reserving block 2 crashes
    b = ck.SequenceAllocator(f)
    after = [b.next() for _ in range(3)]
    assert min(after) > max(issued)
    assert len(set(issued + after)) == len(issued) + len(after)


def test_unreadable_sequence_state_refuses_to_start(tmp_path):
    f = tmp_path / "seq.json"
    f.write_bytes(b"{not json")
    with pytest.raises(ck.CheckpointError):
        ck.SequenceAllocator(f)


# ---------------- A17 constants ----------------


def test_checkpoint_file_names_and_cadence_are_fixed():
    assert ck.CHECKPOINT_FILES == (
        "policy.npz",
        "target.npz",
        "optimizer.npz",
        "replay.npz",
        "rng.json",
        "counters.json",
    )
    assert ck.CHECKPOINT_EVERY_FEEDBACK_STEPS == 200 and ck.SEQUENCE_BLOCK == 1000
    assert [n for n in range(1, 801) if ck.checkpoint_due(n)] == [200, 400, 600, 800]
    assert not ck.checkpoint_due(0)
    assert ck.replay_max_bytes(5000, 28) == 5000 * 28 * 4 * 2
    for name in ck.CHECKPOINT_FILES:  # all are legal generation members
        assert ck._NAME.match(name)
