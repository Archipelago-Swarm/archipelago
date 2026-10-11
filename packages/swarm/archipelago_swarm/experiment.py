"""Deterministic 10-phase experiment (spawn -> fragment -> learn -> skill -> reconnect -> transfer
-> reuse -> adapt -> derive). Everything below the phase markers is the same public API a user has:
Swarm.run / set_learning / nodes[...].start_mission. The only scripted inputs are the terrain seed,
node home positions, learning budgets and the one mission waypoint (the crest), all in SCENARIO.
No skill, link or transfer is injected: they appear (or not) from learning, terrain and RF."""

from __future__ import annotations

import json

from .node import NodeConfig
from .swarm import Swarm
from .world import NavWorld

SCENARIO = {
    "terrain_seed": 12,
    "homes": {  # start cells
        "node-0": (2, 8),
        "node-1": (6, 12),
        "node-2": (5, 9),
        "node-3": (16, 5),
        "node-4": (17, 7),
    },
    # operating areas (geofence boxes x0,x1,y0,y1). Chosen by exhaustive RF scan: no cell pair
    # across the two boxes has a non-DOWN link (the ridge at x~10-12 and distance separate them).
    "west_box": (1, 7, 7, 13),
    "east_box": (14, 20, 3, 10),
    "west": ["node-0", "node-1", "node-2"],
    "east": ["node-3", "node-4"],
    "relay": "creator",  # the skill holder flies the mission (a data mule), default; or a node id
    "crest": (
        13,
        4,
    ),  # north-pass vantage: legal path from the west, UP line of sight to ~40% of the east box
    "home_radius": 2,
    "isolated_learning_ticks": 3000,  # phase 3
    "east_learning_budget": 300,  # east nodes stop learning here (compute budget); west continues
    "max_skill_ticks": 4000,
    "max_mission_ticks": 400,
    "max_adapt_ticks": 5000,
}


def cross_links(sw: Swarm, sc) -> list[str]:
    """Non-DOWN RF links between the two clusters right now."""
    return [
        f"{a}-{b}:{lk.state}"
        for (a, b), lk in sw.net.links.items()
        if ((a in sc["west"]) != (b in sc["west"])) and lk.state != "DOWN"
    ]


def run_experiment(out_dir=None, seed: int = 0, sc: dict | None = None, log=print) -> dict:
    sc = {**SCENARIO, **(sc or {})}
    sw = Swarm(
        NavWorld(seed=sc["terrain_seed"]),
        sc["homes"],
        seed=seed,
        out_dir=out_dir,
        areas={n: sc["west_box" if n in sc["west"] else "east_box"] for n in sc["homes"]},
        node_cfg=NodeConfig(home_radius=sc["home_radius"]),
    )
    W, E, N = sc["west"], sc["east"], sc["homes"]
    ev = sw.store.get_events
    R: dict = {
        "scenario": {k: v for k, v in sc.items() if k != "homes"},
        "seed": seed,
        "phases": {},
    }

    def phase(name, **kv):
        R["phases"][name] = kv
        log(f"[{name}] t={sw.t} " + json.dumps(kv, default=str))

    # P1 spawn
    h0 = {n: sw.nodes[n].policy_hash() for n in N}
    phase(
        "1_spawn",
        identical_initial_policy=len(set(h0.values())) == 1,
        policy_hash=next(iter(h0.values()))[:12],
        nodes=len(N),
    )
    # P2 terrain-induced fragmentation
    sw.tick()
    phase("2_fragmentation", groups=sw.groups(), cross_cluster_links=cross_links(sw, sc))
    leaks: list[str] = []

    def watch(s):
        leaks.extend(cross_links(s, sc))
        return False

    # P3 independent learning while isolated
    sw.set_learning(N)
    sw.run(sc["east_learning_budget"], until=watch)
    sw.set_learning(E, False)
    sw.run(sc["isolated_learning_ticks"] - sc["east_learning_budget"], until=watch)
    hashes = {n: sw.nodes[n].policy_hash() for n in N}
    phase(
        "3_isolated_learning",
        distinct_policies=len(set(hashes.values())),
        cross_cluster_link_ticks=len(leaks),
        updates={n: sw.nodes[n].learner.steps for n in N},
        last_eval_success={n: sw.nodes[n].my_eval["success_rate"] for n in N},
        peers_discovered={n: sorted({e["peer"] for e in ev("PEER_DISCOVERED", n)}) for n in N},
    )
    # P4 local capability acquisition
    sw.run(sc["max_skill_ticks"], until=lambda s: bool(ev("SKILL_CREATED")))
    created = ev("SKILL_CREATED")
    sk = created[0]["skill"] if created else None
    phase(
        "4_skill_created",
        skill=sk
        and {k: sk[k] for k in ("skill_id", "origin_node_id", "origin_type", "evaluation")},
        creator=created[0]["node"] if created else None,
        created_tick=created[0]["tick"] if created else None,
    )
    # run on so the skill spreads inside the west cluster; east must stay empty
    sw.run(150, until=watch)
    east_has = [n for n in E if sw.nodes[n].registry.list_local_skills()]
    phase(
        "5_skill_stays_local",
        east_nodes_holding_skill=east_has,
        cross_cluster_link_ticks=len(leaks),
        west_holders=[n for n in W if sw.nodes[n].registry.list_local_skills()],
    )
    # P6 topology change: the relay flies to the crest with its own policy
    rid = created[0]["node"] if sc["relay"] == "creator" and created else sc["relay"]
    relay = sw.nodes[rid]
    relay.start_mission(sc["crest"], sw.t, autopilot=True, hold=True)
    t_mission = sw.t
    sw.run(
        sc["max_mission_ticks"],
        until=lambda s: bool(ev("NODE_MISSION_COMPLETED", rid)) and bool(cross_links(s, sc)),
    )
    sw.run(10)  # let the link persist long enough to be announced (event debounce)
    phase(
        "6_topology_change",
        relay=rid,
        mission_completed=bool(ev("NODE_MISSION_COMPLETED", rid)),
        relay_position=list(relay.pos),
        ticks=sw.t - t_mission,
        cross_cluster_links=cross_links(sw, sc),
        groups=sw.groups(),
        peers_discovered=[
            (e["node"], e["peer"], e["tick"])
            for e in ev("PEER_DISCOVERED")
            if (e["node"] in E) != (e["peer"] in E)
        ],
    )
    # P7/8 propagation + reuse
    sw.run(300, until=lambda s: any(e["node"] in E for e in ev("SKILL_ACTIVATED")))
    acts = [e for e in ev("SKILL_ACTIVATED") if e["node"] in E]
    phase(
        "7_transfer",
        installs=[
            (e["node"], e["skill_id"], e["source_peer"], e["tick"])
            for e in ev("SKILL_INSTALLED")
            if e["node"] in E
        ],
        failures=[(e["node"], e["reason"]) for e in ev("SKILL_TRANSFER_FAILED")],
        east_activations=[(e["node"], e["skill_id"], e["reason"]) for e in acts],
    )
    # P9/10 local adaptation -> derived skill
    receivers = sorted({e["node"] for e in acts})
    sw.set_learning(receivers)
    sw.run(sc["max_adapt_ticks"], until=lambda s: any(e["node"] in E for e in ev("SKILL_DERIVED")))
    der = [e for e in ev("SKILL_DERIVED") if e["node"] in E]
    phase(
        "8_adaptation_derivation",
        derived=[
            (e["node"], e["skill"]["skill_id"], e["parent"], e["derived_from_node"]) for e in der
        ],
        lineage=[m["skill_id"] for m in sw.store.get_skill_lineage(der[0]["skill"]["skill_id"])]
        if der
        else None,
    )
    ph = R["phases"]
    R["checks"] = {
        "T0_equal_initial_policies": ph["1_spawn"]["identical_initial_policy"],
        "T4_terrain_partition": not ph["2_fragmentation"]["cross_cluster_links"]
        and all(len({n in W for n in g}) == 1 for g in ph["2_fragmentation"]["groups"]),
        "T5_no_cross_cluster_link_while_isolated": ph["3_isolated_learning"][
            "cross_cluster_link_ticks"
        ]
        == 0,
        "T6_policies_diverged": ph["3_isolated_learning"]["distinct_policies"] == len(N),
        "T8_skill_earned": sk is not None,
        "T9_skill_local_before_reconnect": not ph["5_skill_stays_local"]["east_nodes_holding_skill"]
        and ph["5_skill_stays_local"]["cross_cluster_link_ticks"] == 0,
        "T10_topology_changed": bool(ph["6_topology_change"]["cross_cluster_links"]),
        "T11_peers_discovered": bool(ph["6_topology_change"]["peers_discovered"]),
        "T12_T13_skill_transferred_and_activated": bool(acts),
        "T16_derived_with_lineage": bool(der),
    }
    R["ok"] = all(R["checks"].values())
    R["final_metrics"] = sw.metrics()
    sw.store.write_json("report.json", R)
    sw.close()
    return R
