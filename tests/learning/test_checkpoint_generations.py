import io
import json
from pathlib import Path

import numpy as np
import pytest
import torch
from archipelago_learning import encode, offer
from archipelago_learning.checkpoint import CheckpointError, DurableIO, write_generation
from torch_support import torch_learner, trained_torch


def state(L):
    return {
        "params": L.params_numpy(),
        "target": L.target_numpy(),
        "opt": L._optimizer_arrays(),
        "replay": {k: v.copy() for k, v in L.replay.items()},
        "rng": json.dumps(L.rng.bit_generator.state),
        "tgen": L.torch_gen.get_state().clone(),
        "counters": (L.steps, L.version, L.n, L.paused),
        "events": json.loads(json.dumps(L.events)),
        "previous": None if L.previous is None else {k: v.copy() for k, v in L.previous.items()},
    }


def assert_same_state(a, b):
    for part in ("params", "target", "opt", "replay"):
        assert a[part].keys() == b[part].keys()
        assert all(np.array_equal(a[part][k], b[part][k]) for k in a[part]), part
    assert a["rng"] == b["rng"] and torch.equal(a["tgen"], b["tgen"])
    assert a["counters"] == b["counters"] and a["events"] == b["events"]
    assert (a["previous"] is None) == (b["previous"] is None)
    if a["previous"] is not None:
        assert all(np.array_equal(a["previous"][k], b["previous"][k]) for k in a["previous"])


def test_generation_roundtrip_restores_everything_including_extra(tmp_path):
    teacher = trained_torch(0, "teacher")
    a = trained_torch(1, "a", steps=120)
    assert offer(a, encode(teacher), lambda p: 0.0, margin=-1)["accepted"]  # previous + event
    for _ in range(7):
        a.train_step()
    a.act([0, 1, 0], eps=0.5)  # advance exploration RNG
    a.paused = True
    extra = {"node_runtime": {"sequence": 41, "epsilon": 0.2, "dedupe": [["node-02", 3, "ab"]]}}
    m = a.save_generation(tmp_path, extra=extra)
    assert m["generation"] == 1 and "extra.node_runtime.json" in m["files"]
    b = torch_learner("a", seed=99)  # different seed: everything must come from the checkpoint
    got = b.load_latest(tmp_path)
    assert got["extra"] == extra and got["counters"]["steps"] == a.steps
    assert_same_state(state(a), state(b))
    assert b.act([0, 1, 0]) == a.act([0, 1, 0]) and b.paused


def test_restore_and_continue_equals_uninterrupted_run(tmp_path):
    ref = trained_torch(0, "a", steps=60)
    ref.save_generation(tmp_path)
    resumed = torch_learner("a", seed=123)
    resumed.load_latest(tmp_path)
    data = np.random.default_rng(5)
    for _ in range(80):  # same new data + same exploration for both, target syncs included
        o = np.eye(3, dtype=np.float32)[data.integers(3)]
        outs = []
        for L in (ref, resumed):
            a = L.act(o, eps=0.3)
            L.observe(o, a, float(a == int(o.argmax())), o, False)
            outs.append((a, L.train_step(target_every=7)))
        assert outs[0][0] == outs[1][0] and outs[0][1] == pytest.approx(outs[1][1], rel=1e-5)
    for k, v in ref.params_numpy().items():
        assert np.allclose(v, resumed.params_numpy()[k], atol=1e-6)
    for k, v in ref.target_numpy().items():
        assert np.allclose(v, resumed.target_numpy()[k], atol=1e-6)
    assert ref.version == resumed.version and ref.steps == resumed.steps


def test_keeps_last_three_generations_and_numbers_increase(tmp_path):
    L = trained_torch(0, steps=5)
    for i in range(5):
        L.train_step()
        assert L.save_generation(tmp_path)["generation"] == i + 1
    assert sorted(p.name for p in tmp_path.glob("gen-*")) == ["gen-3", "gen-4", "gen-5"]
    assert json.loads((tmp_path / "CURRENT").read_text())["generation"] == 5
    assert not list(tmp_path.rglob("*.tmp"))


# --- fault injection ------------------------------------------------------------------------


class Kill(Exception):
    pass


class KillAt(DurableIO):
    """Simulates the writer dying at its k-th filesystem primitive (before it takes effect)."""

    def __init__(self, k, torn=False):
        self.k, self.torn, self.i, self.log = k, torn, 0, []

    def hook(self, op, path):
        self.log.append((op, Path(path).name))
        if self.i == self.k and not (self.torn and op == "write_tmp"):
            self.i += 1
            raise Kill(f"{op} {path}")
        self.i += 1

    def write_tmp(self, tmp, data):
        if self.torn and self.i == self.k:  # half the bytes reach disk, then the process dies
            tmp.write_bytes(data[: len(data) // 2])
            raise Kill(f"torn {tmp}")
        super().write_tmp(tmp, data)


def count_ops(L, root):
    io_ = KillAt(10**9)
    L.save_generation(root, extra={"x": {"k": 1}}, _io=io_)
    return io_.i, io_.log


@pytest.mark.parametrize("torn", [False, True])
def test_kill_between_every_pair_of_writes_leaves_loadable_previous_generation(tmp_path, torn):
    probe = trained_torch(0, steps=3)
    total, log = count_ops(probe, tmp_path / "probe")
    switch = next(i for i, (op, name) in enumerate(log) if op == "rename" and name == "CURRENT")
    assert total > 12 and switch > 8  # many files -> many cut points
    for k in range(total):
        root = tmp_path / f"k{k}"
        L = trained_torch(0, steps=3)
        L.save_generation(root, extra={"x": {"gen": 1}})  # generation 1, fully committed
        s1 = state(L)
        for _ in range(4):
            L.train_step()
        s2 = state(L)
        with pytest.raises(Kill):
            L.save_generation(root, extra={"x": {"gen": 2}}, _io=KillAt(k, torn))
        fresh = torch_learner("t", seed=77)
        got = fresh.load_latest(root)
        if k <= switch:  # CURRENT still names generation 1 (or has not been renamed yet)
            assert got["generation"] == 1 and got["extra"] == {"x": {"gen": 1}}, k
            assert_same_state(s1, state(fresh))
        else:  # generation 2 was complete and CURRENT already switched
            assert got["generation"] == 2 and got["extra"] == {"x": {"gen": 2}}, k
            assert_same_state(s2, state(fresh))
        # the writer can recover: next save succeeds, garbage-collects debris, and loads back
        gen = L.save_generation(root)["generation"]
        assert gen > got["generation"] and not list(root.rglob("*.tmp"))
        assert torch_learner("t").load_latest(root)["generation"] == gen


def test_kill_during_first_ever_generation_never_yields_a_half_state(tmp_path):
    L = trained_torch(0, steps=3)
    total, log = count_ops(L, tmp_path / "probe")
    manifest = next(i for i, (op, n) in enumerate(log) if op == "rename" and n == "MANIFEST.json")
    want = state(L)
    for k in range(total):
        root = tmp_path / f"f{k}"
        with pytest.raises(Kill):
            L.save_generation(root, extra={"x": {"k": 1}}, _io=KillAt(k))
        fresh = torch_learner("t", seed=3)
        if k <= manifest:  # manifest not yet committed: nothing is loadable, failure is named
            with pytest.raises(CheckpointError, match="no loadable"):
                fresh.load_latest(root)
        else:  # generation complete (CURRENT may be missing: found by scan); state is whole
            assert fresh.load_latest(root)["generation"] == 1
            assert_same_state(want, state(fresh))


def newest(root):
    return max(Path(root).glob("gen-*"), key=lambda p: int(p.name[4:]))


def three_generations(root):
    L = trained_torch(0, steps=3)
    states = []
    for _ in range(3):
        L.train_step()
        L.save_generation(root, extra={"e": {"v": L.steps}})
        states.append(state(L))
    return states


@pytest.mark.parametrize(
    "fname",
    ["model.npz", "optimizer.npz", "replay.npz", "rng.npz", "extra.e.json", "counters.json"],
)
def test_corrupt_newest_file_falls_back_to_previous_complete_generation(tmp_path, fname):
    states = three_generations(tmp_path)
    f = newest(tmp_path) / fname
    raw = bytearray(f.read_bytes())
    raw[len(raw) // 2] ^= 0xFF
    f.write_bytes(bytes(raw))
    fresh = torch_learner("t", seed=5)
    got = fresh.load_latest(tmp_path)
    assert got["generation"] == 2 and got["extra"] == {"e": {"v": states[1]["counters"][0]}}
    assert_same_state(states[1], state(fresh))


def test_all_generations_corrupt_raises_named_error(tmp_path):
    three_generations(tmp_path)
    for g in tmp_path.glob("gen-*"):
        (g / "model.npz").write_bytes(b"x")
    with pytest.raises(CheckpointError, match="no loadable"):
        torch_learner("t").load_latest(tmp_path)


def test_missing_manifest_truncated_file_and_bad_current_are_handled(tmp_path):
    states = three_generations(tmp_path)
    (newest(tmp_path) / "MANIFEST.json").unlink()  # incomplete generation ignored
    fresh = torch_learner("t")
    assert fresh.load_latest(tmp_path)["generation"] == 2
    assert_same_state(states[1], state(fresh))
    (tmp_path / "CURRENT").write_text("{garbage")  # damaged pointer: scan for newest complete
    assert torch_learner("t").load_latest(tmp_path)["generation"] == 2
    f = tmp_path / "gen-2" / "replay.npz"
    f.write_bytes(f.read_bytes()[:100])  # truncated
    assert torch_learner("t").load_latest(tmp_path)["generation"] == 1


def test_current_pointing_at_replaced_manifest_is_not_trusted(tmp_path):
    three_generations(tmp_path)
    cur = json.loads((tmp_path / "CURRENT").read_text())
    cur["manifest_sha256"] = "0" * 64
    (tmp_path / "CURRENT").write_text(json.dumps(cur))
    # still loads (newest complete generation found by scan) but via verified hashes only
    assert torch_learner("t").load_latest(tmp_path)["generation"] == 3


def test_load_rejects_incompatible_or_unsafe_checkpoint_without_touching_learner(tmp_path):
    L = trained_torch(0, steps=3)
    L.save_generation(tmp_path)
    other = torch_learner("t", hidden=8)
    before = state(other)
    with pytest.raises(CheckpointError, match="hidden"):
        other.load_latest(tmp_path)
    assert_same_state(before, state(other))
    # a hash-valid generation whose npz carries a pickled object is never unpickled
    root = tmp_path / "evil"
    buf = io.BytesIO()
    np.savez(buf, p_w1=np.array([object()], dtype=object))
    files = {n: (tmp_path / "gen-1" / n).read_bytes() for n in ("optimizer.npz", "replay.npz")}
    files |= {n: (tmp_path / "gen-1" / n).read_bytes() for n in ("rng.npz", "previous.npz")}
    files |= {n: (tmp_path / "gen-1" / n).read_bytes() for n in ("counters.json", "events.json")}
    write_generation(root, files | {"model.npz": buf.getvalue()})
    victim = torch_learner("t")
    before = state(victim)
    with pytest.raises(CheckpointError):
        victim.load_latest(root)
    assert_same_state(before, state(victim))


def test_bad_extra_names_and_values_are_refused(tmp_path):
    L = trained_torch(0, steps=3)
    with pytest.raises(ValueError):
        L.save_generation(tmp_path, extra={"../evil": {}})
    with pytest.raises(ValueError):
        L.save_generation(tmp_path, extra={"nan": float("nan")})


def test_checkpoint_events_are_capped_to_newest_and_size_stays_bounded(tmp_path):
    from archipelago_learning import torch_dqn

    cap = torch_dqn.MAX_CKPT_EVENTS

    def evs(n):
        return [{"type": "local_update", "step": i, "version": i, "loss": 0.0} for i in range(n)]

    L = trained_torch(0, "a", steps=10)
    L.events = evs(cap)
    L.save_generation(tmp_path / "small")
    small = (tmp_path / "small" / "gen-1" / "events.json").stat().st_size
    L.events = evs(cap * 5)
    L.save_generation(tmp_path / "big")
    assert (tmp_path / "big" / "gen-1" / "events.json").stat().st_size <= small * 1.1
    R = torch_learner("a")
    out = R.load_latest(tmp_path / "big")
    assert R.events == L.events[-cap:]
    assert out["counters"]["events_dropped"] == cap * 4
