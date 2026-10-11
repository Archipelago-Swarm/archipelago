"""Swarm: simulator bookkeeping. Owns the world, the RF network and the nodes, advances ticks and
exposes metrics. It never makes an agent decision: all intelligence lives in SwarmNode."""

from __future__ import annotations

from .network import Network
from .node import NodeConfig, SwarmNode
from .rf import DOWN, RFConfig
from .store import Store
from .world import NavWorld


class Swarm:
    def __init__(
        self,
        world: NavWorld,
        homes: dict[str, tuple[int, int]],
        seed: int = 0,
        out_dir=None,
        areas: dict | None = None,
        node_cfg: NodeConfig | None = None,
        rf_cfg: RFConfig | None = None,
        dt_s: float = 0.1,
    ):
        self.world, self.t, self.dt = world, 0, dt_s
        self.store = Store(out_dir)
        self.net = Network(self.store, rf_cfg or RFConfig(), dt_s)
        # Equivalent baseline: every node gets the SAME initial weights (init_seed=seed) but its
        # own replay/exploration/goal streams (node_seed distinct per node).
        self.nodes = {
            nid: SwarmNode(
                nid,
                world,
                self.store,
                home,
                seed,
                seed * 1000 + 17 * i + 1,
                node_cfg,
                dt_s,
                (areas or {}).get(nid),
            )
            for i, (nid, home) in enumerate(sorted(homes.items()))
        }
        self.ports = {nid: self.net.port(nid) for nid in self.nodes}

    def set_learning(self, ids, on: bool = True) -> None:
        for i in ids:
            self.nodes[i].set_learning(on, self.t)

    def tick(self) -> None:
        self.t += 1
        self.net.update(self.t, self.world.terrain, {n: x.pos for n, x in self.nodes.items()})
        for nid, node in self.nodes.items():
            node.tick(self.t, self.ports[nid])

    def run(self, ticks: int, until=None) -> int:
        for _ in range(ticks):
            self.tick()
            if until and until(self):
                break
        return self.t

    def groups(self) -> list[list[str]]:
        """Connected components of the current RF graph (links not DOWN). Bookkeeping view only."""
        adj = {n: set() for n in self.nodes}
        for (a, b), lk in self.net.links.items():
            if lk.state != DOWN:
                adj[a].add(b)
                adj[b].add(a)
        seen, out = set(), []
        for n in sorted(adj):
            if n in seen:
                continue
            comp, stack = [], [n]
            while stack:
                x = stack.pop()
                if x not in seen:
                    seen.add(x)
                    comp.append(x)
                    stack += adj[x]
            out.append(sorted(comp))
        return out

    def skills_metrics(self) -> list[dict]:
        holders: dict[str, list[dict]] = {}
        for n in self.nodes.values():
            for e in n.registry.list_local_skills():
                holders.setdefault(e.skill.skill_id, []).append(
                    {
                        "node": n.id,
                        "local_state": e.local_state,
                        "source_peer": e.source_peer,
                        "active": n.registry.active_id == e.skill.skill_id,
                    }
                )
        return [
            {
                "skill_id": s,
                "version": m["version"],
                "origin_node": m["origin_node_id"],
                "provenance": m["origin_type"],
                "parent": m["parent_skill_id"],
                "derived_from_node": m["derived_from_node_id"],
                "evaluation": m["evaluation"],
                "content_hash": m["content_hash"],
                "current_holders": holders.get(s, []),
            }
            for s, m in sorted(self.store.skill_meta.items())
        ]

    def metrics(self) -> dict:
        return {
            "tick": self.t,
            "sim_time_s": round(self.t * self.dt, 3),
            "nodes": [n.metrics(self.t) for n in self.nodes.values()],
            "links": [
                {
                    "node_a": a,
                    "node_b": b,
                    **{k: v for k, v in lk.as_dict().items() if k not in ("a", "b")},
                }
                for (a, b), lk in sorted(self.net.links.items())
            ],
            "groups": self.groups(),
            "network_messages": {n: dict(v) for n, v in sorted(self.net.stats.items())},
            "skills": self.skills_metrics(),
        }

    def close(self) -> None:
        self.store.write_json("metrics.json", self.metrics())
        self.store.close()
