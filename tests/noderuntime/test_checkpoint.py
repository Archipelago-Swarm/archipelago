"""Generation checkpoints, restore, and sequence/event_id continuity across restarts."""

import json
import time

import pytest
from archipelago_learning.checkpoint import DurableIO
from archipelago_noderuntime.encoder import ACTIONS
from archipelago_noderuntime.node import Node
from archipelago_noderuntime.protocol import ActRequest, FeedbackRequest
from archipelago_sim.env import GridWorld
from procs import NodeProc
from support import FakeSink, make_cfg, obs_json


class Killed(Exception):
    pass


class KillAt(DurableIO):
    """Dies (as a killed process would) right before the n-th filesystem primitive."""

    def __init__(self, n):
        self.n, self.seen = n, 0

    def hook(self, op, path):
        self.seen += 1
        if self.seen == self.n:
            raise Killed(f"{op} {path}")


def drive(node, ticks, run="run-k", episode=0, start=0):
    """act + feedback straight through the node API (no HTTP)."""
    w = GridWorld(size=8, n_agents=1, n_targets=0, max_ticks=100000)
    obs = w.reset(1 + start)["node-0"]
    if node.run_id != run or node.episode != episode:
        from archipelago_noderuntime.protocol import Reset

        node.control_reset(Reset(command="reset", run_id=run, episode=episode))
    for t in range(start, start + ticks):
        if not w.agents:
            obs = w.reset(t)["node-0"]
        a = node.act(
            ActRequest.model_validate(
                {
                    "run_id": run,
                    "episode": episode,
                    "tick": t,
                    "observation": obs_json(run, "n", t, obs),
                }
            )
        )
        nxt, rew, _, _, _ = w.step({"node-0": a["action"]["command"]})
        obs = nxt.get("node-0", obs)
        node.feedback(
            FeedbackRequest.model_validate(
                {
                    "run_id": run,
                    "episode": episode,
                    "tick": t,
                    "reward": rew["node-0"],
                    "next_observation": obs_json(run, "n", t + 1, obs),
                    "terminated": False,
                    "truncated": False,
                    "executed_command": a["action"]["command"],
                    "action_index": ACTIONS.index(a["action"]["command"]),
                    "deadline_missed": False,
                }
            )
        )


def spooled(cfg):
    out = []
    for p in sorted((cfg.checkpoint_dir / "telemetry").glob("seg-*.jsonl")):
        out += [json.loads(x) for x in p.read_text().splitlines()]
    return out


def test_kill_at_every_checkpoint_write_step_restores_last_complete_generation(tmp_path):
    k, completed_once = 1, False
    while not completed_once:
        cfg = make_cfg(tmp_path / f"k{k}", node_ids=("node-01",), update_every=5)
        n1 = Node(cfg)
        drive(n1, 30)
        n1.checkpoint()  # generation 1 completes
        s1, ver1 = n1.learner.steps, n1.learner.version
        sha1 = n1.status()["policy_sha256"]
        eps1, acts1 = n1.epsilon(), n1.act_count
        drive(n1, 15, start=30)
        s2 = n1.learner.steps
        assert s2 > s1
        n1.ckpt_io = KillAt(k)
        try:
            n1.checkpoint()
            completed_once = True  # write finished before the kill point: end of the sweep
        except Killed:
            pass
        # n1 is now "dead": no close(), no final flush. A new process starts on the same volume.
        n2 = Node(cfg)
        info = n2.restore_info
        assert info["restored"] is True
        if completed_once:
            assert info["generation"] == 2 and n2.learner.steps == s2
        else:
            # generation 2 was incomplete or not yet switched: the last COMPLETE one is restored,
            # unless the kill hit after CURRENT was switched (then generation 2 is complete)
            assert info["generation"] in (1, 2)
            if info["generation"] == 1:
                assert n2.learner.steps == s1 and n2.learner.version == ver1
                assert n2.status()["policy_sha256"] == sha1
                assert n2.act_count == acts1 and n2.epsilon() == eps1  # exploration schedule
            else:
                assert n2.learner.steps == s2
        # sequence continues, event ids never collide
        old = spooled(cfg)
        old_ids = {r["event_id"] for r in old}
        old_max = max(r["record"]["sequence"] for r in old)
        assert n2.seq.ceiling > old_max
        assert n2.boot_id != n1.boot_id
        drive(n2, 12, start=45)
        n2.checkpoint()
        allrecs = spooled(cfg)
        ids = [r["event_id"] for r in allrecs]
        assert len(ids) == len(set(ids))  # no event_id collision across boots
        new = [r for r in allrecs if r["event_id"] not in old_ids]
        assert new and min(r["record"]["sequence"] for r in new) > old_max
        assert all(r["event_id"].startswith(f"node-01-{n2.boot_id}-") for r in new)
        k += 1
        assert k < 60, "kill sweep did not terminate"
    assert k > 8  # the sweep really covered many distinct write steps


def test_restore_returns_every_part_of_node_state(tmp_path):
    cfg = make_cfg(tmp_path, node_ids=("node-01", "node-02"), update_every=5)
    n1 = Node(cfg)
    from archipelago_contracts.models import FaultWindow

    n1.schedule = type(n1.schedule)(
        [FaultWindow(start_tick=5, end_tick=50, cut_links=[("node-01", "node-02")])]
    )
    n1.dedupe["node-02|3|abc"] = None
    n1.last_sent["node-02"] = (9, "d" * 64)
    drive(n1, 70)
    st = n1.checkpoint()
    n2 = Node(cfg)
    assert n2.checkpoint_generation == st["generation"]
    assert n2.learner.steps == n1.learner.steps and n2.learner.n == n1.learner.n
    assert (n2.learner.replay["o"] == n1.learner.replay["o"]).all()
    assert list(n2.dedupe) == list(n1.dedupe) and n2.last_sent == n1.last_sent
    assert n2.schedule.sha256 == n1.schedule.sha256 and n2.schedule.windows
    assert n2.run_id == "run-k" and n2.loss_ema == n1.loss_ema
    assert n2.act_rng.bit_generator.state == n1.act_rng.bit_generator.state
    assert n2.counters["feedbacks"] == n1.counters["feedbacks"]
    # restored training continues exactly like an uninterrupted node would
    drive(n1, 10, start=70)
    drive(n2, 10, start=70)
    assert n1.status()["policy_sha256"] == n2.status()["policy_sha256"]


def test_corrupt_newest_generation_falls_back_to_previous_complete(tmp_path):
    cfg = make_cfg(tmp_path, node_ids=("node-01",))
    n1 = Node(cfg)
    drive(n1, 30)
    n1.checkpoint()
    s1 = n1.learner.steps
    drive(n1, 10, start=30)
    n1.checkpoint()
    victim = cfg.checkpoint_dir / "ckpt" / "gen-2" / "policy.npz"
    victim.write_bytes(victim.read_bytes()[:-20])  # bit rot / torn write
    n2 = Node(cfg)
    assert n2.restore_info["generation"] == 1 and n2.learner.steps == s1


def test_nothing_loadable_starts_fresh_and_says_so(tmp_path):
    cfg = make_cfg(tmp_path, node_ids=("node-01",))
    (cfg.checkpoint_dir / "ckpt" / "gen-1").mkdir(parents=True)  # a partial generation only
    n = Node(cfg)
    assert n.restore_info["restored"] is False and "no loadable" in n.restore_info["error"]
    assert n.learner.steps == 0


def test_checkpoint_with_different_hyperparameters_is_refused_not_silently_reset(tmp_path):
    from archipelago_learning.checkpoint import CheckpointError

    cfg = make_cfg(tmp_path, node_ids=("node-01",))
    n = Node(cfg)
    drive(n, 20)
    n.checkpoint()
    with pytest.raises(CheckpointError, match="hidden"):
        Node(cfg.with_(hidden=16))


# --- a real process, SIGKILLed ---------------------------------------------------------------
def _drive_http(client, ticks, start=0, run="run-p", episode=0):
    w = GridWorld(size=8, n_agents=1, n_targets=0, max_ticks=100000)
    obs = w.reset(2)["node-0"]
    for t in range(start, start + ticks):
        if not w.agents:
            obs = w.reset(t)["node-0"]
        st, a = client.act(run, episode, t, obs_json(run, "n", t, obs))
        assert st == 200, a
        nxt, rew, _, _, _ = w.step({"node-0": a["action"]["command"]})
        obs = nxt.get("node-0", obs)
        st, f = client.feedback(
            run, episode, t, rew["node-0"], obs_json(run, "n", t + 1, obs),
            cmd=a["action"]["command"],
        )  # fmt: skip
        assert st == 200, f


def test_sigkilled_process_restarts_from_its_checkpoint_with_continued_sequences(tmp_path):
    sink = FakeSink()
    env = dict(TELEMETRY_URL=sink.url, TELEMETRY_UPDATE_EVERY=5)
    p1 = NodeProc(tmp_path, **env).start()
    try:
        c = p1.client
        c.control("reset", run_id="run-p", episode=0)
        _drive_http(c, 40)
        st, ck = c.control("checkpoint")
        assert st == 200 and ck["generation"] == 1
        at_ckpt = c.status()
        _drive_http(c, 25, start=40)  # work after the checkpoint is lost by the kill
        assert c.status()["train_steps"] > at_ckpt["train_steps"]
        deadline = time.time() + 10
        while not sink.events and time.time() < deadline:
            time.sleep(0.05)
        boot1 = p1.info["boot_id"]
        p1.kill()
    finally:
        p1.close()
    p2 = NodeProc(tmp_path, **env).start()
    try:
        c = p2.client
        assert p2.info["restore"]["restored"] is True and p2.info["restore"]["generation"] == 1
        st = c.status()
        assert (
            st["train_steps"] == at_ckpt["train_steps"]
            and st["replay_size"] == at_ckpt["replay_size"]
        )
        assert (
            st["policy_sha256"] == at_ckpt["policy_sha256"] and st["epsilon"] == at_ckpt["epsilon"]
        )
        assert st["boot_id"] != boot1 and st["run_id"] == "run-p"
        _drive_http(c, 20, start=65)
        deadline = time.time() + 15
        while time.time() < deadline and c.status()["telemetry_backlog"] > 0:
            time.sleep(0.05)
        recs = list(sink.events.values())
        ids = [r["event_id"] for r in recs]
        assert len(ids) == len(set(ids))
        b1 = [r["record"]["sequence"] for r in recs if f"-{boot1}-" in r["event_id"]]
        b2 = [r["record"]["sequence"] for r in recs if f"-{p2.info['boot_id']}-" in r["event_id"]]
        assert b1 and b2 and max(b1) < min(b2)  # the sequence continued across the kill
        assert p2.terminate() == 0  # graceful stop writes a final generation
    finally:
        p2.close()
        sink.close()
    p3 = NodeProc(tmp_path, **env).start()
    try:
        assert p3.info["restore"]["generation"] >= 2
        assert p3.client.status()["train_steps"] == at_ckpt["train_steps"] + 20
    finally:
        p3.close()


# --- A17: fixed file names, size bound, cadence --------------------------------------------------
def _gen_dir(cfg, n):
    return cfg.checkpoint_dir / "ckpt" / f"gen-{n}"


def test_generation_uses_the_a17_file_names_and_replay_stays_within_its_bound(tmp_path):
    from archipelago_learning import checkpoint as ck

    cfg = make_cfg(tmp_path, node_ids=("node-01",), capacity=300)
    n = Node(cfg)
    drive(n, 350)  # more feedbacks than capacity: the buffer is full and has wrapped
    n.wait_idle()
    gen = n.checkpoint()["generation"]
    d = _gen_dir(cfg, gen)
    assert sorted(p.name for p in d.iterdir()) == sorted([*ck.CHECKPOINT_FILES, "MANIFEST.json"])
    assert (cfg.checkpoint_dir / "ckpt" / "CURRENT").exists()
    manifest = json.loads((d / "MANIFEST.json").read_text())
    assert set(manifest["files"]) == set(ck.CHECKPOINT_FILES)
    assert (d / "replay.npz").stat().st_size <= ck.replay_max_bytes(300, cfg.obs_dim)
    counters = json.loads((d / "counters.json").read_text())
    assert counters["steps"] == n.learner.steps and counters["node"]["run_id"] == "run-k"
    json.loads((d / "rng.json").read_text())
    n.close()


def test_checkpoint_every_200_feedback_steps_and_at_episode_end(tmp_path):
    from archipelago_noderuntime.protocol import EpisodeEnd

    cfg = make_cfg(tmp_path, node_ids=("node-01",))
    n = Node(cfg)
    try:
        drive(n, 199)
        n.wait_idle()
        assert n.checkpoint_generation == 0  # not yet due
        drive(n, 1, start=199)  # the 200th feedback
        assert n.wait_idle() and n.checkpoint_generation == 1
        drive(n, 200, start=200)
        assert n.wait_idle() and n.checkpoint_generation == 2
        assert n.counters["feedbacks"] == 400
        code, out = n.request_episode_end(
            EpisodeEnd(command="episode_end", run_id="run-k", episode=0, tick=400)
        )
        assert code == 202 and out["window_id"]
        assert n.wait_window(out["window_id"]) is not None
        assert n.checkpoint_generation == 3  # the episode_end generation
        n2 = Node(cfg)  # the cadence counts feedback steps, so it survives a restart
        assert n2.counters["feedbacks"] == 400
        n2.close()
    finally:
        n.close()


# --- A3: pending (obs, action), stale rule, block-reserved sequences --------------------------
def _act_req(run, ep, tick, obs):
    return ActRequest.model_validate(
        {"run_id": run, "episode": ep, "tick": tick, "observation": obs_json(run, "n", tick, obs)}
    )


def _fb_req(run, ep, tick, obs, cmd):
    return FeedbackRequest.model_validate(
        {
            "run_id": run, "episode": ep, "tick": tick, "reward": 0.5, "terminated": False,
            "next_observation": obs_json(run, "n", tick + 1, obs),
            "executed_command": cmd, "action_index": ACTIONS.index(cmd),
            "deadline_missed": False,
        }
    )  # fmt: skip


def test_pending_obs_action_and_ticks_survive_a_restart(tmp_path):
    from archipelago_noderuntime.node import ApiError

    cfg = make_cfg(tmp_path, node_ids=("node-01",))
    n1 = Node(cfg)
    drive(n1, 10)
    w = GridWorld(size=8, n_agents=1, n_targets=0, max_ticks=1000)
    obs = w.reset(9)["node-0"]
    a10 = n1.act(_act_req("run-k", 0, 10, obs))  # acted, feedback not yet received
    n1.checkpoint()
    n2 = Node(cfg)
    assert n2.restore_info["pending"] == 1 and n2.tick == 10 and n2.fed_tick == 9
    # the feedback of the act that preceded the checkpoint is accepted after the restart ...
    before = n2.learner.n
    out = n2.feedback(_fb_req("run-k", 0, 10, obs, "east"))
    assert out["accepted"] is True and n2.learner.n == before + 1
    # ... and trains on the EXECUTED action (east), not necessarily the one the node chose
    i = (n2.learner.n - 1) % n2.learner.capacity
    assert int(n2.learner.replay["a"][i]) == ACTIONS.index("east")
    # the stale rule is lexicographic on (episode, tick) and survives the restart
    with pytest.raises(ApiError) as e:
        n2.act(_act_req("run-k", 0, 9, obs))
    assert e.value.status == 409 and e.value.code == "stale"
    with pytest.raises(ApiError) as e2:
        n2.feedback(_fb_req("run-k", 0, 5, obs, "stay"))
    assert e2.value.status == 409 and e2.value.code == "stale"
    assert a10["action"]["event_id"].startswith(f"node-01-{n1.boot_id}-")


def test_sequence_ceiling_is_reserved_in_blocks_and_a_restart_starts_at_the_ceiling(tmp_path):
    cfg = make_cfg(tmp_path, node_ids=("node-01",))
    n1 = Node(cfg)
    drive(n1, 600)  # more than a thousand events (actions, learning events, metrics)
    issued = [
        json.loads(x)["record"]["sequence"]
        for p in sorted((cfg.checkpoint_dir / "telemetry").glob("seg-*.jsonl"))
        for x in p.read_text().splitlines()
    ]
    top = n1.seq.ceiling
    assert top % 1000 == 0 and top > max(issued)  # a whole block ahead of everything issued
    persisted = json.loads((cfg.checkpoint_dir / "sequence.json").read_text())
    assert persisted["ceiling"] == top  # written BEFORE the numbers were used
    n2 = Node(cfg)  # restart without any graceful shutdown
    boot = [r for r in spooled(cfg) if r["event_id"].startswith(f"node-01-{n2.boot_id}-")]
    assert [r["record"]["sequence"] for r in boot] == [top]  # its boot metric took the ceiling
    assert n2.seq.next() == top + 1 and top > max(issued)  # nothing below the ceiling was reissued
    assert n2.status()["sequence_ceiling"] == top + 1000
    assert n2.boot_id != n1.boot_id
