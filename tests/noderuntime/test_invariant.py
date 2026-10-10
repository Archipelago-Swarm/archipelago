"""T27 completion invariant, end to end: three REAL node runtimes (HTTP on localhost, one process)
learn independently, run tick-cadence exchange windows that a scheduled partition actually cuts,
one of them is killed mid-checkpoint-write and resumes with continued ids, and keeps exchanging."""

import json

from archipelago_noderuntime.runtime import Runtime
from support import Client, Cluster, MiniCoordinator
from test_checkpoint import KillAt, Killed
from test_peers import N1, N2, N3
from test_windows import windows

OVR = dict(lr=1e-3, validation_max_ticks=30, peer_margin=0.0, hidden=32, exchange_every_ticks=10)
IDS = (N1, N2, N3)


def spooled(node):
    out = []
    for p in sorted((node.cfg.checkpoint_dir / "telemetry").glob("seg-*.jsonl")):
        out += [json.loads(x) for x in p.read_text().splitlines()]
    return out


def test_independent_learning_cut_windows_midwrite_kill_and_continued_ids(tmp_path):
    c = Cluster(tmp_path, IDS, **OVR)
    coord = MiniCoordinator(c.clients, max_ticks=500)
    try:
        # --- episode 0: 9 ticks, before the first window: pure independent learning ------------
        assert coord.run_episode(0, seed=2, ticks=9, cadence=10) == 9
        assert all(c.node(i).learner.steps >= 1 for i in IDS)  # trained in ITS OWN process
        shas = {c.clients[i].status()["policy_sha256"] for i in IDS}
        assert len(shas) == 3  # distinct per-node policies
        assert len({c.node(i).learner.replay["o"].tobytes() for i in IDS}) == 3  # own data
        assert all(c.node(i).counters["exchanges"] == 0 for i in IDS)  # nothing exchanged yet
        # --- episode 1: a partition cutting node-01 <-> node-02 only, windows every 10 ticks -----
        cut = [{"start_tick": 15, "end_tick": 35, "cut_links": [[N1, N2]]}]
        n = coord.run_episode(1, seed=3, ticks=45, schedule=cut, end=True, cadence=10)
        assert n == 45
        steps = {i: c.node(i).learner.steps for i in IDS}
        assert all(s > 40 for s in steps.values())
        by = {
            i: {r["tick"]: r for r in windows(c.node(i)) if not r["final"] and r["episode"] == 1}
            for i in IDS
        }
        for t in (20, 30):  # windows inside the cut: no offer on the cut link, others unaffected
            assert by[N1][t]["cut"] == [N2] and N2 not in by[N1][t]["sent"]
            assert by[N2][t]["cut"] == [N1] and N1 not in by[N2][t]["sent"]
            assert by[N1][t]["sent"] == [N3] and by[N3][t]["cut"] == []
            assert sorted(by[N3][t]["sent"]) == [N1, N2]
        for i in IDS:  # local training continued across the whole cut
            assert by[i][40]["train_steps"] > by[i][20]["train_steps"] + 15
        assert c.node(N2).counters["offers_cut"] == 2
        gen_ep0 = {i: c.node(i).checkpoint_generation for i in IDS}
        assert all(g >= 1 for g in gen_ep0.values())  # the episode_end generation exists
        steps_at_gen = c.node(N2).learner.steps

        # --- episode 2: more training, then node-02 dies in the middle of its checkpoint write ----
        coord.run_episode(2, seed=4, ticks=25, schedule=[], end=False, cadence=10)
        victim = c.node(N2)
        boot_before = victim.boot_id
        victim.ckpt_io = KillAt(3)  # dies right before the 3rd filesystem primitive of the write
        st, out = c.clients[N2].control("episode_end", episode=2, tick=25)
        assert st == 202 and c.clients[N2].wait_idle()
        assert "error" in victim.results[out["window_id"]] and Killed.__name__ in str(
            victim.results[out["window_id"]]["error"]
        )
        assert victim.learner.steps > steps_at_gen
        ids_before = {r["event_id"] for r in spooled(victim)}
        seq_before = max(r["record"]["sequence"] for r in spooled(victim))
        cfg2 = c.runtimes[N2].cfg
        c.runtimes[N2].stop(checkpoint=False)  # the process is gone; nothing more is written

        # --- restart on the same volume ---------------------------------------------------------
        rt2 = Runtime(cfg2)
        urls = {i: c.runtimes[i].peer_url for i in IDS}
        urls[N2] = rt2.peer_url
        for rt in c.runtimes.values():
            rt.set_peer_urls(urls)
        rt2.set_peer_urls(urls)
        rt2.start()
        c.runtimes[N2] = rt2
        c.clients[N2] = Client(rt2.control_url)
        n2 = rt2.node
        info = n2.restore_info
        assert info["restored"] is True and info["prev_boot_id"] == boot_before
        assert info["generation"] == gen_ep0[N2]  # the last COMPLETE generation, not the torn one
        assert n2.learner.steps == steps_at_gen and n2.boot_id != boot_before
        assert n2.seq.ceiling > seq_before  # ids continue past everything the dead boot issued

        # --- episode 3: the restarted node trains, exchanges, and its offers are accepted -------
        before = {i: c.node(i).counters["offers_received"] for i in IDS if i != N2}
        coord.run_episode(3, seed=5, ticks=25, schedule=[], end=True, cadence=10)
        assert n2.learner.steps > steps_at_gen + 15
        mine = {r["tick"]: r for r in windows(n2) if r["episode"] == 3 and not r["final"]}
        assert sorted(mine[10]["sent"]) == [N1, N3]
        assert all(not r["refused"] for r in windows(n2))  # post-restart seqs were not stale
        got = sum(c.node(i).counters["offers_received"] - before[i] for i in before)
        assert got >= 2  # the others actually received the restarted node's offers
        recs = spooled(n2)
        ids_all = [r["event_id"] for r in recs]
        assert len(ids_all) == len(set(ids_all))  # no event_id collision across boots
        new = [r for r in recs if r["event_id"] not in ids_before]
        assert new and all(r["event_id"].startswith(f"{N2}-{n2.boot_id}-") for r in new)
        assert min(r["record"]["sequence"] for r in new) > seq_before
    finally:
        c.close()
