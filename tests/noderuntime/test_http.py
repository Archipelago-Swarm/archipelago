import json
import urllib.error
import urllib.request

import numpy as np
import pytest
from archipelago_noderuntime.config import Config, ConfigError
from archipelago_noderuntime.runtime import Runtime
from archipelago_sim.env import GridWorld
from support import TOKEN, Client, MiniCoordinator, make_cfg, obs_json


@pytest.fixture()
def rt(tmp_path):
    r = Runtime(make_cfg(tmp_path, node_ids=("node-01",), train_steps_per_feedback=1)).start()
    yield r
    r.stop(checkpoint=False)


@pytest.fixture()
def cl(rt):
    return Client(rt.control_url)


def _world_obs(seed=1):
    w = GridWorld(size=8, n_agents=1, n_targets=0, max_ticks=500)
    return w, w.reset(seed)["node-0"]


def test_status_ready_and_shape(cl):
    st = cl.status()
    assert st["ready"] is True and st["backend"] == "torch-cpu"
    assert st["node_id"] == "node-01" and st["train_steps"] == 0 and st["replay_size"] == 0
    assert st["rss_bytes"] > 0 and st["peers"] == {}
    assert st["telemetry_backlog"] >= 0 and st["checkpoint_generation"] == 0


def test_auth_is_enforced_on_every_endpoint(cl):
    _, o = _world_obs()
    ob = obs_json("run-a", "n", 0, o)
    assert cl.call("GET", "/v1/status", token=None)[0] == 401
    assert cl.call("GET", "/v1/status", token="x" * 20)[0] == 401
    assert cl.act("run-a", 0, 0, ob, token=None)[0] == 401
    assert cl.act("run-a", 0, 0, ob, token="wrong-token-wrong-token")[0] == 401
    assert cl.call("POST", "/v1/control", {"command": "pause"}, token=None)[0] == 401
    assert cl.call("POST", "/v1/feedback", {}, token="bad")[0] == 401
    assert cl.status()["tick"] == -1  # nothing the unauthenticated calls sent had any effect
    assert cl.act("run-a", 0, 0, ob)[0] == 200


def test_oversized_and_malformed_bodies_are_rejected(cl):
    big = b'{"command":"pause","pad":"' + b"a" * (300 * 1024) + b'"}'
    assert cl.call("POST", "/v1/control", raw=big)[0] == 413
    assert cl.call("POST", "/v1/control", raw=b"{not json")[0] == 400
    assert cl.call("POST", "/v1/control", {"command": "launch_missiles"})[0] == 422
    assert cl.call("POST", "/v1/act", {"run_id": "r"})[0] == 422
    assert cl.call("POST", "/v1/nope", {})[0] == 404
    assert cl.call("GET", "/v1/act")[0] in (404, 405)
    assert cl.status()["ready"] is True  # still serving after all of it


def test_act_idempotent_per_step_key_and_stale_is_409(cl):
    _, o = _world_obs()
    ob = obs_json("run-a", "n", 0, o)
    s1, a1 = cl.act("run-a", 0, 0, ob)
    s2, a2 = cl.act("run-a", 0, 0, ob)
    assert s1 == s2 == 200 and a1 == a2  # same action, same event_id: not re-sampled
    assert a1["action"]["command"] in ("stay", "north", "east", "south", "west")
    assert a1["action"]["source_node_id"] == "node-01" and a1["node_id"] == "node-01"
    st3, a3 = cl.act("run-a", 0, 1, obs_json("run-a", "n", 1, o))
    assert st3 == 200 and a3["action"]["sequence"] > a1["action"]["sequence"]
    # tick 0 again but not an exact duplicate of cached? It is cached -> still idempotent
    assert cl.act("run-a", 0, 0, ob)[1] == a1
    # a tick lower than the last acted tick and not cached is stale
    cl.call("POST", "/v1/control", {"command": "reset", "run_id": "run-a", "episode": 0})  # dup
    s, body = cl.act("run-a", 0, 5, obs_json("run-a", "n", 5, o))
    assert s == 200
    s, body = cl.act("run-a", 0, 3, obs_json("run-a", "n", 3, o))
    assert s == 409 and body["error"] == "stale"
    assert (
        cl.status()["counters"]["act_stale"] == 1 and cl.status()["counters"]["act_duplicates"] >= 2
    )


def test_exploration_is_not_resampled_on_duplicates(rt, cl):
    _, o = _world_obs()
    outs = set()
    for _ in range(30):  # high epsilon: any re-sampling would show up as differing replies
        outs.add(json.dumps(cl.act("run-a", 0, 0, obs_json("run-a", "n", 0, o))[1], sort_keys=True))
    assert len(outs) == 1
    assert rt.node.counters["acts"] == 1


def test_episode_and_run_ordering(cl):
    _, o = _world_obs()
    assert cl.act("run-a", 1, 0, obs_json("run-a", "n", 0, o))[0] == 200
    s, b = cl.act("run-a", 0, 0, obs_json("run-a", "n", 0, o))
    assert s == 409 and b["error"] == "stale"  # older episode
    s, b = cl.act("run-b", 1, 1, obs_json("run-b", "n", 1, o))
    assert s == 409 and b["error"] == "wrong_run"
    st, b = cl.control("reset", run_id="run-b", episode=0)
    assert st == 200
    assert cl.act("run-b", 0, 0, obs_json("run-b", "n", 0, o))[0] == 200


def test_bad_crop_shape_is_a_422_not_a_crash(cl):
    _, o = _world_obs()
    o = dict(o, crop=[row[:3] for row in o["crop"][:3]], known_mask=[[True] * 3] * 3)
    s, b = cl.act("run-a", 0, 0, obs_json("run-a", "n", 0, o))
    assert s == 422 and b["error"] == "bad_observation"
    assert cl.status()["ready"]


def _drive(cl, n, run="run-a", ep=0, start=0):
    w = GridWorld(size=8, n_agents=1, n_targets=0, max_ticks=1000)
    obs = w.reset(1)
    out = []
    for t in range(start, start + n):
        st, a = cl.act(run, ep, t, obs_json(run, "n", t, obs["node-0"]))
        assert st == 200
        nxt, rew, term, trunc, _ = w.step({"node-0": a["action"]["command"]})
        st, f = cl.feedback(run, ep, t, rew["node-0"], obs_json(run, "n", t + 1, nxt["node-0"]))
        assert st == 200, f
        out.append(f)
        obs = nxt
    return out


def test_feedback_idempotent_stale_and_unknown_step(cl):
    w = GridWorld(size=8, n_agents=1, n_targets=0, max_ticks=100)
    o = w.reset(1)["node-0"]
    cl.act("run-a", 0, 0, obs_json("run-a", "n", 0, o))
    nxt = obs_json("run-a", "n", 1, o)
    s1, f1 = cl.feedback("run-a", 0, 0, 0.5, nxt)
    s2, f2 = cl.feedback("run-a", 0, 0, 0.5, nxt)
    assert s1 == s2 == 200 and f1["accepted"] and f2["duplicate"] is True
    assert f1["train_steps"] == f2["train_steps"] and f1["replay_size"] == f2["replay_size"] == 1
    assert cl.status()["replay_size"] == 1  # the duplicate stored nothing
    s, b = cl.feedback("run-a", 0, 7, 0.5, nxt)  # never acted
    assert s == 409 and b["error"] == "unknown_step"
    cl.act("run-a", 0, 1, obs_json("run-a", "n", 1, o))
    cl.act("run-a", 0, 2, obs_json("run-a", "n", 2, o))
    assert cl.feedback("run-a", 0, 2, 0.1, nxt)[0] == 200
    s, b = cl.feedback("run-a", 0, 1, 0.1, nxt)  # older than the last feedback
    assert s == 409 and b["error"] == "stale"


def test_training_happens_in_process_and_counts_match(rt, cl):
    n = 60
    outs = _drive(cl, n)
    st = cl.status()
    batch = rt.node.cfg.batch
    # replay holds one transition per feedback; one optimizer step per feedback once replay >= batch
    assert st["replay_size"] == n
    assert outs[-1]["replay_size"] == n
    assert st["train_steps"] == n - batch + 1
    assert st["policy_version"] == st["train_steps"]  # every step published a new policy
    assert st["loss_ema"] is not None and np.isfinite(st["loss_ema"])
    L = rt.node.learner
    assert L.steps == st["train_steps"] and L.n == n  # state is in THIS process, not forwarded


def test_pause_stops_training_but_acting_and_replay_continue(rt, cl):
    _drive(cl, 20)
    before = cl.status()
    assert before["train_steps"] > 0
    assert cl.control("pause")[0] == 200
    _drive(cl, 10, start=20)
    mid = cl.status()
    assert mid["train_steps"] == before["train_steps"] and mid["replay_size"] == 30
    assert mid["tick"] == 29  # acting continued
    assert cl.control("resume")[0] == 200
    _drive(cl, 5, start=30)
    assert cl.status()["train_steps"] > mid["train_steps"]


def test_eval_mode_freezes_optimizer_exploration_and_replay(rt, cl):
    _drive(cl, 40)
    cl.control("reset", run_id="run-a", episode=1, mode="eval")
    frozen = cl.status()
    assert frozen["mode"] == "eval" and frozen["epsilon"] == 0.0
    w = GridWorld(size=8, n_agents=1, n_targets=0, max_ticks=1000)
    o = w.reset(2)["node-0"]
    acts = []
    for t in range(12):
        st, a = cl.act("run-a", 1, t, obs_json("run-a", "n", t, o))  # same obs every tick
        assert st == 200 and a["epsilon"] == 0.0
        acts.append(a["action"]["command"])
        assert cl.feedback("run-a", 1, t, 1.0, obs_json("run-a", "n", t + 1, o))[0] == 409
    assert len(set(acts)) == 1  # greedy: no exploration noise
    after = cl.status()
    for k in ("train_steps", "replay_size", "policy_version", "policy_sha256", "loss_ema"):
        assert after[k] == frozen[k], k
    # leaving eval resumes training exactly where it was
    cl.control("reset", run_id="run-a", episode=2, mode="train")
    _drive(cl, 5, ep=2)
    assert cl.status()["train_steps"] == frozen["train_steps"] + 5


def test_two_nodes_in_a_sorted_manifest_get_distinct_initial_policies(tmp_path):
    a = Runtime(make_cfg(tmp_path, "node-01", ("node-01", "node-02"))).start()
    b = Runtime(make_cfg(tmp_path, "node-02", ("node-01", "node-02"))).start()
    try:
        assert (
            Client(a.control_url).status()["policy_sha256"]
            != Client(b.control_url).status()["policy_sha256"]
        )
    finally:
        a.stop(False)
        b.stop(False)


def test_config_requires_strong_token_and_rejects_test_seed_overlap(tmp_path):
    env = {
        "NODE_ID": "node-01",
        "NODE_IDS": "node-01,node-02",
        "NODE_CHECKPOINT_DIR": str(tmp_path),
    }
    with pytest.raises(ConfigError, match="at least 16"):
        Config.from_env({**env, "NODE_CONTROL_TOKEN": "short"})
    with pytest.raises(ConfigError, match="required"):
        Config.from_env(env)
    with pytest.raises(ConfigError, match="test seeds"):
        Config.from_env(
            {**env, "NODE_CONTROL_TOKEN": TOKEN, "VALIDATION_SEEDS": "1,2", "TEST_SEEDS": "2,3"}
        )
    cfg = Config.from_env(
        {
            **env,
            "NODE_CONTROL_TOKEN": TOKEN,
            "PEER_URLS": "node-01=http://node-01:9000,node-02=http://node-02:9000",
            "TORCH_THREADS": "2",
            "LR": "0.005",
        }
    )
    assert cfg.peer_urls["node-02"] == "http://node-02:9000" and cfg.torch_threads == 2
    assert cfg.lr == 0.005 and cfg.obs_dim == 28


def test_unauthenticated_healthz_exposes_nothing_else(rt):
    with urllib.request.urlopen(rt.control_url + "/healthz", timeout=5) as r:
        assert json.loads(r.read()) == {"ok": True}
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(rt.control_url + "/v1/status", timeout=5)
    assert e.value.code == 401


def test_minicoordinator_roundtrip_smoke(tmp_path):
    r = Runtime(make_cfg(tmp_path, node_ids=("node-01",))).start()
    try:
        c = Client(r.control_url)
        n = MiniCoordinator({"node-01": c}).run_episode(0, seed=3, ticks=25)
        assert n == 25 and c.status()["replay_size"] == 25
    finally:
        r.stop(False)


def test_stop_command_signals_shutdown(rt, cl):
    assert not rt.node.stop_event.is_set()
    st, out = cl.control("stop")
    assert st == 200 and out["stopping"] is True and rt.node.stop_event.is_set()
