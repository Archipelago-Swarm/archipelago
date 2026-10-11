"""SwarmNode: one UAV with its own learner, replay, optimizer, skill registry, decision history
and peer view. It reaches the world only through ``plant`` (observe/step physics for its own
cell) and the network only through its ``NetPort``; it holds no reference to other nodes.

Per tick: network phase (RF-gated inbox, discovery, advertise, request, stream) -> act phase
(observe, Q forward pass, select, step, reward, store experience, maybe train, trace) ->
skills phase (periodic evaluation: qualify a SELF_LEARNED skill, or derive from an adapted one).
"""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass

import numpy as np

from .explain import attribute
from .learner import NodeLearner
from .network import NetPort
from .skills import (
    LOCALLY_DERIVED,
    PEER_RECEIVED,
    SELF_LEARNED,
    Skill,
    SkillError,
    SkillRegistry,
    check_compat,
    compat_header,
    evaluate_params,
)
from .store import Store
from .world import ACTIONS, DELTA, OBS_NAMES


@dataclass
class NodeConfig:
    home_radius: int = 4
    max_ep_steps: int = 30
    mission_max_steps: int = 40  # per leg; a timed-out leg is re-planned from where the node is
    eval_episodes: int = 40
    eval_every: int = 250  # learning env-steps between evaluations
    qual_success: float = 0.5  # absolute floor for a first skill
    qual_gain: float = 0.3  # ... and gain over the spawn baseline
    root_gain: float = 0.1  # a later SELF_LEARNED skill must beat the previous one by this
    warmup: int = 100
    train_every: int = 1
    eps_decay: int = 1500
    eps_min: float = 0.05
    eps_adapt: float = 0.1
    eps_eval: float = 0.02
    advert_period: int = 10
    summary_period: int = 20
    request_cooldown: int = 30
    request_margin: float = 0.1  # advertised success must beat my last eval by this to request
    act_margin: float = 0.1  # local eval success must beat my current policy by this to activate
    stall_limit: int = 5
    peer_debounce: int = 5  # ticks a link must persist before PEER_DISCOVERED / PEER_LOST
    adapt_min_updates: int = 300
    derive_return_gain: float = 0.1


@dataclass
class _Out:  # outbound artifact transfer (sender side)
    sid: str
    peer: str
    skill_id: str
    blob: bytes
    offset: int = 0
    stalled: int = 0
    sent_at: int = 0
    done_tick: int | None = None


@dataclass
class _In:  # inbound artifact transfer (receiver side)
    sid: str
    peer: str
    meta: dict
    buf: bytearray
    last_progress: int
    started: int


class SwarmNode:
    def __init__(
        self,
        node_id,
        plant,
        store: Store,
        home,
        init_seed,
        node_seed,
        cfg=None,
        dt_s=0.1,
        area=None,
    ):
        self.id, self.plant, self.store, self.cfg, self.dt = (
            node_id,
            plant,
            store,
            cfg or NodeConfig(),
            dt_s,
        )
        self.learner = NodeLearner(node_id, init_seed, node_seed)
        self.registry = SkillRegistry(node_id)
        self.home, self.pos, self.battery = tuple(home), tuple(home), 1.0
        self.area = tuple(area) if area else None  # (x0, x1, y0, y1) operating box, else a disk
        self.fence = frozenset(self._home_cells())
        self.compat = compat_header(self.learner.hidden)
        self.goal_rng = random.Random(node_seed * 31 + 1)
        self.eval_set = self._make_eval_set(random.Random(node_seed * 31 + 2))
        self.base_eval = self.my_eval = evaluate_params(
            plant, self.learner.params_numpy(), self.eval_set
        )
        self.learning_enabled = False
        self.mission: tuple[int, int] | None = None
        self.route: list[tuple[int, int]] = []
        self.autopilot = self.hold = False
        self.node_step = self.learn_steps = self.episode = self.ep_steps = 0
        self.ep_return = 0.0
        self.goal = self._new_goal()
        self.step_rewards: deque[float] = deque(maxlen=200)
        self.outcomes: deque[bool] = deque(maxlen=50)
        self.last_reward = 0.0
        self.peers: dict[str, dict] = {}  # peer -> {reachable, adverts, summary}
        self.out: dict[str, _Out] = {}
        self.inn: _In | None = None
        self.cooldown: dict[str, int] = {}
        self._flip: dict[str, int] = {}
        self.announced: set[tuple[str, str]] = set()
        self.adapt_start = 0
        self.neighbors: dict[str, dict] = {}
        self.c = dict.fromkeys(
            (
                "decisions",
                "peer_summaries_sent",
                "peer_summaries_received",
                "skill_advertisements",
                "skill_adverts_received",
                "skill_requests",
                "skill_requests_received",
                "skill_transfers_sent",
                "skill_transfers_received",
                "skill_transfer_failures",
            ),
            0,
        )
        self._phase = sum(map(ord, node_id))
        self._hash_cache: tuple[int, str] = (-1, "")
        store.emit(
            "NODE_SPAWNED",
            0,
            node_id,
            home=list(self.home),
            policy_id=self.learner.policy_id,
            policy_hash=self.policy_hash(),
            baseline_eval=self.base_eval,
            init_seed=init_seed,
            node_seed=node_seed,
        )

    # --- helpers ---------------------------------------------------------------------------
    def policy_hash(self) -> str:
        if self._hash_cache[0] != self.learner.version:
            self._hash_cache = (self.learner.version, self.learner.policy_hash())
        return self._hash_cache[1]

    def _home_cells(self):
        if self.area:
            x0, x1, y0, y1 = self.area
            return [
                (x, y)
                for x in range(x0, x1 + 1)
                for y in range(y0, y1 + 1)
                if self.plant.inside((x, y))
            ]
        hx, hy = self.home
        r = self.cfg.home_radius
        return [
            (x, y)
            for x in range(hx - r, hx + r + 1)
            for y in range(hy - r, hy + r + 1)
            if self.plant.inside((x, y)) and (x - hx) ** 2 + (y - hy) ** 2 <= r * r
        ]

    def _make_eval_set(self, rng: random.Random):
        cells, out = self._home_cells(), []
        while len(out) < self.cfg.eval_episodes:
            s, g = rng.choice(cells), rng.choice(cells)
            if self.plant.feasible_goal(s, g):
                out.append((s, g))
        return out

    def _new_goal(self):
        if self.mission:
            return self.route[0]
        cells = [c for c in self._home_cells() if self.plant.feasible_goal(self.pos, c)]
        return self.goal_rng.choice(cells or self._home_cells())

    @property
    def active_entry(self):
        return (
            self.registry.entries.get(self.registry.active_id) if self.registry.active_id else None
        )

    def set_learning(self, on: bool, tick: int) -> None:
        if on != self.learning_enabled:
            self.learning_enabled = on
            self.store.emit(
                "LOCAL_LEARNING_STARTED" if on else "LOCAL_LEARNING_STOPPED",
                tick,
                self.id,
                policy_id=self.learner.policy_id,
            )

    def start_mission(
        self, target, tick: int, route=None, autopilot: bool = False, hold: bool = False
    ) -> None:
        """Fly to ``target``. ``route`` = waypoints from the (simulator-side) mission planner; the
        learned policy flies each leg. ``autopilot=True`` instead follows the planner's cell path
        directly (a SCRIPTED transit: the Q-values are still logged but do not choose the action,
        and no experience is stored or trained on)."""
        self.mission, self.autopilot, self.hold = tuple(target), autopilot, hold
        self.route = [tuple(w) for w in (route or [target])]
        self.goal, self.ep_steps, self.ep_return = self.route[0], 0, 0.0
        self.episode += 1
        self.store.emit(
            "NODE_MISSION_STARTED",
            tick,
            self.id,
            target=list(self.mission),
            from_pos=list(self.pos),
            waypoints=[list(w) for w in self.route],
        )

    def _epsilon(self) -> float:
        if not self.learning_enabled:
            return self.cfg.eps_eval
        e = self.active_entry
        if e and e.local_state in (PEER_RECEIVED, LOCALLY_DERIVED):
            return self.cfg.eps_adapt
        return max(self.cfg.eps_min, 1.0 - self.learn_steps / self.cfg.eps_decay)

    # --- tick ------------------------------------------------------------------------------
    def tick(self, t: int, port: NetPort) -> None:
        self._network_phase(t, port)
        self._act(t)
        if self.learning_enabled and self.learn_steps % self.cfg.eval_every == 0:
            self._skills_phase(t)

    # --- act -------------------------------------------------------------------------------
    def _act(self, t: int) -> None:
        lr, cfg = self.learner, self.cfg
        obs = self.plant.observe(self.pos, self.goal)
        q = lr.q_values(obs)
        eps = self._epsilon()
        greedy = int(np.argmax(q))
        explore = bool(lr.act_rng.random() < eps)
        a = int(lr.act_rng.integers(len(ACTIONS))) if explore else greedy
        scripted = self.mission is not None and self.autopilot
        if scripted:
            step = (self.plant.route(self.pos, self.mission, 1) or [self.pos])[0]
            a = (
                DELTA.index((step[0] - self.pos[0], step[1] - self.pos[1]))
                if step != self.pos
                else greedy
            )
            explore = False
        prob = [eps / len(ACTIONS) + (1 - eps) * (i == greedy) for i in range(len(ACTIONS))]
        order = np.argsort(-q)
        versus = int(order[1]) if a == greedy else greedy
        snap = lr._published
        attr = {
            "versus": ACTIONS[versus],
            "top": attribute({k: snap[k] for k in ("w1", "b1", "w2", "b2")}, obs, a, versus),
        }
        pos0, v0 = self.pos, lr.version
        ent = self.active_entry
        diverged = bool(ent and self.policy_hash() != ent.skill.training["params_sha256"])
        nxt, r, comp, reached, info = self.plant.step(
            self.pos, self.goal, a, None if self.mission else self.fence
        )
        self.pos = nxt
        self.battery = max(0.0, self.battery - 0.00005 - 0.000001 * info["climb_m"])
        obs2 = self.plant.observe(nxt, self.goal)
        recorded = self.learning_enabled and not scripted
        upd = None
        if recorded:
            lr.observe_aug(obs, a, r, obs2, reached)
            self.learn_steps += 1
            if lr.n >= cfg.warmup * 8 and self.learn_steps % cfg.train_every == 0:
                upd = lr.train_update()
        self.node_step += 1
        self.c["decisions"] += 1
        self.step_rewards.append(r)
        self.last_reward = r
        self.ep_steps += 1
        self.ep_return += r
        did = f"{self.id}-d{self.node_step:06d}"
        names = dict(zip(OBS_NAMES, (round(float(x), 4) for x in obs), strict=True))
        rec = {
            "decision_id": did,
            "sim_time_s": round(t * self.dt, 3),
            "step": t,
            "node_step": self.node_step,
            "episode_id": f"{self.id}-ep{self.episode:04d}",
            "node_id": self.id,
            "position": list(pos0),
            "elevation_m": round(self.plant.elev(pos0), 1),
            "battery": round(self.battery, 4),
            "goal": list(self.goal),
            "mission": bool(self.mission),
            "observation_summary": names,
            "observation": [round(float(x), 5) for x in obs],
            "terrain_features": {k: v for k, v in names.items() if not k.startswith("goal")},
            "network_context": {p: n["state"] for p, n in self.neighbors.items()},
            "reachable_peers": sorted(self.neighbors),
            "active_policy_id": f"{self.id}-policy-v{v0:04d}",
            "active_skill_id": ent.skill.skill_id if ent else None,
            "active_skill_origin": ent.local_state if ent else None,
            "active_skill_version": ent.skill.version if ent else None,
            "active_skill_source_peer": ent.source_peer if ent else None,
            "policy_diverged_from_skill": diverged,
            "raw_policy_output": {
                "q_values": {n: round(float(x), 4) for n, x in zip(ACTIONS, q, strict=True)}
            },
            "action_distribution": {n: round(p, 4) for n, p in zip(ACTIONS, prob, strict=True)},
            "greedy_action": ACTIONS[greedy],
            "selected_action": ACTIONS[a],
            "selected_action_index": a,
            "action_confidence": round(prob[a], 4),
            "q_margin": round(float(q[order[0]] - q[order[1]]), 4),
            "exploration_vs_exploitation": "scripted"
            if scripted
            else "explore"
            if explore
            else "exploit",
            "selection_method": "mission_autopilot"
            if scripted
            else "epsilon_random"
            if explore
            else "greedy_argmax_q",
            "epsilon": round(eps, 4),
            "attribution": attr,
            "executed": {
                "rejected": info["rejected"],
                "slope": None if info["slope"] is None else round(info["slope"], 4),
            },
            "reward_after_action": round(r, 4),
            "reward_components": {k: round(v, 4) for k, v in comp.items()},
            "next_position": list(nxt),
            "reached_goal": reached,
            "next_state_summary": {
                "goal_dist_cells": round(float(obs2[2]) * 12.0, 3),
                "battery": round(self.battery, 4),
            },
            "experience_recorded": recorded,
            "training_update_triggered": upd is not None,
            "policy_version_before": v0,
            "policy_version_after": lr.version,
        }
        codes = [
            "MISSION_AUTOPILOT"
            if scripted
            else "EXPLORATORY_RANDOM_ACTION"
            if explore
            else "GREEDY_Q"
        ]
        if info["rejected"]:
            codes.append("MOVE_REJECTED_" + info["rejected"].upper())
        if not self.learning_enabled:
            codes.append("LEARNING_DISABLED")
        if not self.neighbors:
            codes.append("ISOLATED")
        rec["reason_codes"] = codes
        if upd:
            tid = f"{self.id}-tu{lr.steps:06d}"
            rec["training_event_id"] = tid
            self.store.add_update(
                {
                    "training_event_id": tid,
                    "node_id": self.id,
                    "episode": self.episode,
                    "step": t,
                    "node_step": self.node_step,
                    "decision_id": did,
                    **upd,
                    "experience_count": self.learn_steps,
                    "reward_window": round(float(np.mean(self.step_rewards)), 4),
                    "success_window": self.success_rate,
                    "policy_id_after": lr.policy_id,
                    "policy_hash_after": self.policy_hash(),
                    "active_skill_id": rec["active_skill_id"],
                    "n_neighbors": len(self.neighbors),
                }
            )
        self.store.add_decision(rec)
        limit = cfg.mission_max_steps if self.mission else cfg.max_ep_steps
        if reached or self.ep_steps >= limit:
            self.outcomes.append(bool(reached))
            if self.mission and not reached:
                self.route = self.plant.route(self.pos, self.mission) or [self.mission]
            elif self.mission and len(self.route) > 1:
                self.route.pop(0)
            elif self.mission and reached:
                self.home, self.area, self.mission, self.route = self.pos, None, None, []
                if self.hold:  # station-keeping relay: stay on the vantage cell, stop training
                    self.area = (self.pos[0], self.pos[0], self.pos[1], self.pos[1])
                    self.set_learning(False, t)
                self.fence = frozenset(self._home_cells())
                self.store.emit(
                    "NODE_MISSION_COMPLETED",
                    t,
                    self.id,
                    position=list(self.pos),
                    steps=self.ep_steps,
                )
            self.episode += 1
            self.ep_steps, self.ep_return = 0, 0.0
            self.goal = self._new_goal()

    @property
    def success_rate(self) -> float | None:
        return round(sum(self.outcomes) / len(self.outcomes), 3) if self.outcomes else None

    # --- skills ----------------------------------------------------------------------------
    def _skills_phase(self, t: int) -> None:
        ev = evaluate_params(
            self.plant, self.learner.params_numpy(), self.eval_set, self.cfg.max_ep_steps
        )
        self.my_eval = ev
        ent = self.active_entry
        if ent and ent.local_state in (PEER_RECEIVED, LOCALLY_DERIVED):
            self._maybe_derive(t, ent, ev)
        else:
            self._maybe_qualify(t, ev)

    def _maybe_qualify(self, t: int, ev: dict) -> None:
        held = [e.skill for e in self.registry.entries.values() if e.local_state == SELF_LEARNED]
        need = (
            max(
                self.cfg.qual_success,
                max(s.evaluation["success_rate"] for s in held) + self.cfg.root_gain,
            )
            if held
            else max(self.cfg.qual_success, self.base_eval["success_rate"] + self.cfg.qual_gain)
        )
        ok = ev["success_rate"] >= need
        self.store.emit(
            "SKILL_EVALUATED",
            t,
            self.id,
            purpose="qualification",
            evaluation=ev,
            required_success=round(need, 3),
            passed=ok,
            policy_id=self.learner.policy_id,
        )
        if not ok:
            return
        self.store.emit(
            "SKILL_CANDIDATE_CREATED",
            t,
            self.id,
            evaluation=ev,
            baseline=self.base_eval,
            required_success=round(need, 3),
            policy_id=self.learner.policy_id,
        )
        ver = str(len(held) + 1)
        sk = self._build_skill(
            f"terrain-nav-v{ver}@{self.id}", ver, SELF_LEARNED, None, None, t, ev
        )
        e = self.registry.add(sk, SELF_LEARNED, None, t)
        e.local_eval, self.registry.active_id = ev, sk.skill_id
        self.store.emit(
            "SKILL_CREATED",
            t,
            self.id,
            skill=sk.meta(),
            size_bytes=sk.size_bytes,
            policy_id=self.learner.policy_id,
        )
        self._persist(sk)

    def _maybe_derive(self, t: int, parent_e, ev: dict) -> None:
        base = parent_e.local_eval or {"success_rate": 0.0, "mean_return": -1e9}
        ready = self.learner.steps - self.adapt_start >= self.cfg.adapt_min_updates
        diverged = self.policy_hash() != parent_e.skill.training["params_sha256"]
        ok = (
            ready
            and diverged
            and ev["success_rate"] >= base["success_rate"]
            and ev["mean_return"] >= base["mean_return"] + self.cfg.derive_return_gain
        )
        self.store.emit(
            "SKILL_EVALUATED",
            t,
            self.id,
            purpose="adaptation",
            skill_id=parent_e.skill.skill_id,
            evaluation=ev,
            baseline_local_eval=base,
            passed=ok,
            updates_since_activation=self.learner.steps - self.adapt_start,
        )
        if ok:
            self.derive_skill(parent_e, ev, t)

    def derive_skill(self, parent_e, ev: dict, t: int) -> Skill:
        p = parent_e.skill
        k = 1 + sum(e.skill.parent_skill_id == p.skill_id for e in self.registry.entries.values())
        ver = f"{p.version}.{k}"
        sk = self._build_skill(
            f"terrain-nav-v{ver}@{self.id}",
            ver,
            LOCALLY_DERIVED,
            p.skill_id,
            p.origin_node_id,
            t,
            ev,
        )
        e = self.registry.add(sk, LOCALLY_DERIVED, None, t)
        e.local_eval, self.registry.active_id = ev, sk.skill_id
        self.adapt_start = self.learner.steps
        self.store.emit(
            "SKILL_DERIVED",
            t,
            self.id,
            skill=sk.meta(),
            parent=p.skill_id,
            parent_local_state=parent_e.local_state,
            parent_source_peer=parent_e.source_peer,
            derived_from_node=p.origin_node_id,
            size_bytes=sk.size_bytes,
            policy_id=self.learner.policy_id,
        )
        self._persist(sk)
        return sk

    def _build_skill(self, sid, ver, origin_type, parent, from_node, t, ev) -> Skill:
        lr = self.learner
        return Skill.build(
            lr.params_numpy(),
            skill_id=sid,
            version=ver,
            origin_node_id=self.id,
            origin_type=origin_type,
            parent_skill_id=parent,
            derived_from_node_id=from_node,
            created_step=t,
            evaluation={
                **ev,
                "eval_set": "creator-home-region",
                "baseline_success_rate": self.base_eval["success_rate"],
            },
            training={
                "policy_id": lr.policy_id,
                "policy_version": lr.version,
                "params_sha256": self.policy_hash(),
                "updates": lr.steps,
                "experience_count": self.learn_steps,
                "episodes": self.episode,
                "learn_steps": self.learn_steps,
                "algorithm": "double-dqn",
                "reward_id": lr.reward_id,
            },
            compat=self.compat,
        )

    def _persist(self, sk: Skill) -> None:
        if self.store.root:
            d = self.store.root / "skills"
            d.mkdir(parents=True, exist_ok=True)
            sk.save(d / f"{sk.skill_id}__{self.id}.skill")

    def evaluate_skill(self, entry, t: int) -> dict:
        ev = evaluate_params(self.plant, entry.skill.params, self.eval_set, self.cfg.max_ep_steps)
        entry.local_eval = ev
        return ev

    def activate_skill(self, skill_id: str, t: int, reason: dict) -> None:
        e = self.registry.entries[skill_id]
        v0, v1 = self.learner.install_params(e.skill.params)
        self.registry.active_id, self.adapt_start = skill_id, self.learner.steps
        self.store.emit(
            "SKILL_ACTIVATED",
            t,
            self.id,
            skill_id=skill_id,
            source_peer=e.source_peer,
            local_state=e.local_state,
            reason=reason,
            policy_version_before=v0,
            policy_version_after=v1,
            policy_id=self.learner.policy_id,
        )

    # --- network ---------------------------------------------------------------------------
    def _network_phase(self, t: int, port: NetPort) -> None:
        cfg = self.cfg
        nb = self.neighbors = port.neighbors()
        for p in sorted(set(nb) | set(self.peers)):  # announce stable changes only
            known = self.peers.get(p, {}).get("reachable", False)
            if (p in nb) == known:
                self._flip.pop(p, None)
            elif t - self._flip.setdefault(p, t) >= cfg.peer_debounce:
                self._flip.pop(p)
                v = self.peers.setdefault(p, {"adverts": {}, "summary": None})
                v["reachable"] = p in nb
                if p in nb:
                    self.store.emit("PEER_DISCOVERED", t, self.id, peer=p, link=nb[p]["state"])
                else:
                    self.store.emit("PEER_LOST", t, self.id, peer=p)
        for m in port.recv():
            self._handle(t, port, m)
        if self.registry.entries and (t + self._phase) % cfg.advert_period == 0:
            ad = self.registry.advertisement()
            for p in nb:
                if port.send(p, {"kind": "SKILL_ADVERT", "skills": ad}):
                    self.c["skill_advertisements"] += 1
                    for a in ad:
                        if (p, a["content_hash"]) not in self.announced:
                            self.announced.add((p, a["content_hash"]))
                            self.store.emit(
                                "SKILL_ADVERTISED",
                                t,
                                self.id,
                                peer=p,
                                skill_id=a["skill_id"],
                                content_hash=a["content_hash"],
                                size_bytes=a["size_bytes"],
                            )
        if (t + self._phase) % cfg.summary_period == 0:
            s = {
                "position": list(self.pos),
                "policy_version": self.learner.version,
                "success_rate": self.success_rate,
                "rolling_reward": self._rolling(),
            }
            for p in nb:
                if port.send(p, {"kind": "PEER_SUMMARY", "summary": s}):
                    self.c["peer_summaries_sent"] += 1
        self._request_phase(t, port)
        self._stream_out(t, port)
        self._check_in(t)

    def _rolling(self):
        return round(float(np.mean(self.step_rewards)), 4) if self.step_rewards else 0.0

    def _handle(self, t: int, port: NetPort, m: dict) -> None:
        src, kind = m["src"], m["kind"]
        pv = self.peers.setdefault(src, {"adverts": {}, "summary": None, "reachable": True})
        if kind == "PEER_SUMMARY":
            pv["summary"] = m["summary"]
            self.c["peer_summaries_received"] += 1
        elif kind == "SKILL_ADVERT":
            pv["adverts"] = {a["skill_id"]: a for a in m["skills"]}
            self.c["skill_adverts_received"] += 1
        elif kind == "SKILL_REQUEST":
            self.c["skill_requests_received"] += 1
            e = self.registry.entries.get(m["skill_id"])
            if e and e.skill.content_hash == m["content_hash"] and src not in self.out:
                blob = e.skill.to_bytes()
                self.out[src] = _Out(m["sid"], src, e.skill.skill_id, blob, sent_at=t)
                self.store.emit(
                    "SKILL_TRANSFER_STARTED",
                    t,
                    self.id,
                    peer=src,
                    skill_id=e.skill.skill_id,
                    size_bytes=len(blob),
                    side="sender",
                    sid=m["sid"],
                )
        elif kind == "SKILL_CHUNK":
            i = self.inn
            if i and i.sid == m["sid"] and m["offset"] == len(i.buf):
                i.buf += m["data"]
                i.last_progress = t
                if len(i.buf) >= m["total"]:
                    self._finish_in(t, port)
        elif kind == "SKILL_ACK":
            o = self.out.get(src)
            if o and o.sid == m["sid"]:
                del self.out[src]
                if m["ok"]:
                    self.c["skill_transfers_sent"] += 1
                    self.store.emit(
                        "SKILL_TRANSFER_COMPLETED",
                        t,
                        self.id,
                        peer=src,
                        skill_id=o.skill_id,
                        side="sender",
                        ticks=t - o.sent_at,
                        bytes=len(o.blob),
                    )

    def _request_phase(self, t: int, port: NetPort) -> None:
        if self.inn:
            return
        for p in sorted(self.neighbors):
            for sid, a in sorted(self.peers.get(p, {}).get("adverts", {}).items()):
                if (
                    self.registry.has(a["content_hash"])
                    or self.cooldown.get(a["content_hash"], -999) > t
                    or a["compat"] != self.compat
                    or a["evaluation"]["success_rate"]
                    < self.my_eval["success_rate"] + self.cfg.request_margin
                ):
                    continue
                req = f"{p}>{self.id}:{sid}:{t}"
                if port.send(
                    p,
                    {
                        "kind": "SKILL_REQUEST",
                        "sid": req,
                        "skill_id": sid,
                        "content_hash": a["content_hash"],
                    },
                ):
                    self.inn = _In(req, p, a, bytearray(), t, t)
                    self.c["skill_requests"] += 1
                    self.store.emit(
                        "SKILL_REQUESTED",
                        t,
                        self.id,
                        peer=p,
                        skill_id=sid,
                        advertised_success=a["evaluation"]["success_rate"],
                        my_success=self.my_eval["success_rate"],
                        sid=req,
                    )
                    return

    def _stream_out(self, t: int, port: NetPort) -> None:
        for p, o in list(self.out.items()):
            if o.offset >= len(o.blob):  # waiting for the ack
                if t - (o.done_tick or t) > 3 * self.cfg.stall_limit:
                    self._fail_out(t, o, "ack_timeout")
                continue
            budget = port.budget_bytes(p)
            if budget <= 0:
                o.stalled += 1
                if o.stalled > self.cfg.stall_limit:
                    self._fail_out(t, o, "link_not_up")
                continue
            o.stalled = 0
            chunk = o.blob[o.offset : o.offset + budget]
            if port.send(
                p,
                {
                    "kind": "SKILL_CHUNK",
                    "sid": o.sid,
                    "offset": o.offset,
                    "total": len(o.blob),
                    "data": chunk,
                },
            ):
                o.offset += len(chunk)
                if o.offset >= len(o.blob):
                    o.done_tick = t

    def _fail_out(self, t: int, o: _Out, reason: str) -> None:
        self.out.pop(o.peer, None)
        self.c["skill_transfer_failures"] += 1
        self.store.emit(
            "SKILL_TRANSFER_FAILED",
            t,
            self.id,
            peer=o.peer,
            skill_id=o.skill_id,
            side="sender",
            reason=reason,
            bytes_sent=o.offset,
            size_bytes=len(o.blob),
        )

    def _check_in(self, t: int) -> None:
        i = self.inn
        if i and t - i.last_progress > 2 * self.cfg.stall_limit:
            self.inn = None
            self.cooldown[i.meta["content_hash"]] = t + self.cfg.request_cooldown
            self.c["skill_transfer_failures"] += 1
            self.store.emit(
                "SKILL_TRANSFER_FAILED",
                t,
                self.id,
                peer=i.peer,
                skill_id=i.meta["skill_id"],
                side="receiver",
                reason="no_data_received",
                bytes_received=len(i.buf),
            )

    def _finish_in(self, t: int, port: NetPort) -> None:
        i, self.inn = self.inn, None
        assert i is not None
        try:
            sk = Skill.from_bytes(bytes(i.buf))
            if sk.content_hash != i.meta["content_hash"]:
                raise SkillError("content hash differs from the advertisement")
            check_compat(sk, self.compat)
        except SkillError as e:
            self.c["skill_transfer_failures"] += 1
            self.cooldown[i.meta["content_hash"]] = t + self.cfg.request_cooldown
            self.store.emit(
                "SKILL_TRANSFER_FAILED",
                t,
                self.id,
                peer=i.peer,
                skill_id=i.meta["skill_id"],
                side="receiver",
                reason=f"validation: {e}",
                bytes_received=len(i.buf),
            )
            port.send(i.peer, {"kind": "SKILL_ACK", "sid": i.sid, "ok": False})
            return
        self.install_skill(sk, i.peer, t)
        port.send(i.peer, {"kind": "SKILL_ACK", "sid": i.sid, "ok": True})
        self.c["skill_transfers_received"] += 1
        self.store.emit(
            "SKILL_TRANSFER_COMPLETED",
            t,
            self.id,
            peer=i.peer,
            skill_id=sk.skill_id,
            side="receiver",
            ticks=t - i.started,
            bytes=len(i.buf),
        )

    def install_skill(self, sk: Skill, source: str, t: int) -> None:
        e = self.registry.add(sk, PEER_RECEIVED, source, t)
        self.store.emit(
            "SKILL_INSTALLED",
            t,
            self.id,
            skill_id=sk.skill_id,
            content_hash=sk.content_hash,
            source_peer=source,
            origin_node=sk.origin_node_id,
            local_state=PEER_RECEIVED,
        )
        ev = self.evaluate_skill(e, t)
        cur = evaluate_params(
            self.plant, self.learner.params_numpy(), self.eval_set, self.cfg.max_ep_steps
        )
        self.my_eval = cur
        go = ev["success_rate"] >= cur["success_rate"] + self.cfg.act_margin
        reason = {
            "candidate_local_success": ev["success_rate"],
            "current_policy_local_success": cur["success_rate"],
            "required_margin": self.cfg.act_margin,
            "compat": "ok",
            "candidate_local_return": ev["mean_return"],
            "current_policy_local_return": cur["mean_return"],
        }
        self.store.emit(
            "SKILL_EVALUATED",
            t,
            self.id,
            purpose="received",
            skill_id=sk.skill_id,
            evaluation=ev,
            current_policy_evaluation=cur,
            passed=go,
            activated=go,
        )
        if go:
            self.activate_skill(sk.skill_id, t, reason)

    # --- metrics ---------------------------------------------------------------------------
    def metrics(self, t: int) -> dict:
        lr = self.learner
        return {
            "node_id": self.id,
            "tick": t,
            "episode": self.episode,
            "step": self.node_step,
            "position": list(self.pos),
            "battery": round(self.battery, 4),
            "learning_enabled": self.learning_enabled,
            "experience_count": self.learn_steps,
            "policy_update_count": lr.steps,
            "policy_version": lr.version,
            "policy_id": lr.policy_id,
            "policy_hash": self.policy_hash(),
            "reward": round(self.last_reward, 4),
            "rolling_reward": self._rolling(),
            "success_rate": self.success_rate,
            "last_eval": self.my_eval,
            **self.registry.counts(),
            "active_skill_id": self.registry.active_id,
            "decision_count": self.c["decisions"],
            "reachable_peers": sorted(self.neighbors),
            "rf_link_count": len(self.neighbors),
            **{k: v for k, v in self.c.items() if k != "decisions"},
        }
