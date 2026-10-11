"""ARCHIPELAGO core mission engine: discover -> verify -> share POIs under RF-limited connectivity,
with one genuinely behaviour-changing P2P skill. Pure Python, deterministic for a seed
(every random draw comes from a named `random.Random(f"{seed}:<stream>")`; iteration is sorted).

Layers (FRONTEND_INTEGRATION.md has the contract):
  world/ground truth : POIs, disruption events, terrain (archipelago_sim.terrain, reused for LOS/detection)
  physical UAVs      : position, sensors, comm radius, health
  local agent        : obs (local world model), search cells, skill registry, decision logic
  P2P exchange       : data sharing and skill sharing, only over links of the current RF graph G(t)
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from archipelago_sim.terrain import Terrain

from .rf import PROFILES, RFEngine, RFNode, geometric_horizon_m

TILE_M = 100_000.0  # 1 world tile = 100 km; canonical sim unit is metres everywhere
TILES_X, TILES_Y = 4, 5
W, H = TILES_X * TILE_M, TILES_Y * TILE_M  # 400 km x 500 km


def tiles_to_m(t: float) -> float:
    return t * TILE_M


def m_to_tiles(m: float) -> float:
    return m / TILE_M


CELL_M = 10_000.0  # terrain cell (40 x 50 cells)
NX, NY = 16, 20  # coarse search cells (25 x 25 km)
CW, CH = W / NX, H / NY
ALL_CELLS = [(i, j) for j in range(NY) for i in range(NX)]
POI_TYPES = ("INFRASTRUCTURE", "VEHICLE", "SIGNAL")
# Every UAV is identical: speed m/s, sensor radius m, cruise altitude AGL m; RF uses the single default profile.
UAV_SPEED_MPS, UAV_SENSOR_M, UAV_ALT_M = 140.0, 40_000.0, 400.0
RF_PROFILE = PROFILES["GENERAL"]  # 40 km nominal link range
ALT_MAX_M, CLIMB_M_PER_TICK = 2000.0, 150.0
SKILL = "adaptive_search_spacing"


@dataclass
class MissionConfig:
    seed: int = 1042
    dt: float = 30.0  # seconds per tick
    time_limit: float = 28800.0
    n_uavs: int = 6
    n_pois: int = 6
    required_pois: int | None = None  # default: all
    knowledge_threshold: float = 0.8
    verify_conf: float = 0.9  # one observation, or noisy-or of distinct observers, above this
    skill_transfer_s: float = 60.0  # seconds of full-bandwidth link needed to move a skill
    skills_enabled: bool = True
    validation_ticks: int = 2
    min_adopt_utility: float = 0.5
    isolated_ticks_before_rendezvous: int = 8
    rendezvous_after: float = (
        0.45  # fraction of time_limit after which nodes holding verified POIs spread them
    )


@dataclass
class Skill:
    name: str
    version: int
    source_node: str
    created_at: float
    confidence: float
    utility: float
    behavior_type: str
    metadata: dict
    status: str = "LOCAL"  # LOCAL | RECEIVED | VALIDATING | ADOPTED | REJECTED
    received_at: float | None = None
    received_from: str | None = None
    validate_left: int = 0

    @property
    def id(self) -> str:
        return f"{self.name}_v{self.version}"

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "version": self.version, "sourceNodeId": self.source_node,
            "createdAt": self.created_at, "receivedAt": self.received_at, "receivedFrom": self.received_from,
            "confidence": self.confidence, "utilityScore": self.utility, "behaviorType": self.behavior_type,
            "status": self.status, "metadata": self.metadata,
        }  # fmt: skip

    def copy(self) -> Skill:
        return Skill(**{**self.__dict__, "metadata": dict(self.metadata)})


@dataclass
class Uav:
    id: str
    x: float
    y: float
    speed_max: float
    sensor_r: float
    alt_base: float
    learn_threshold: int
    bias: dict
    heading: float = 0.0
    speed: float = 0.0
    alt: float = 0.0
    climbing: bool = False
    skill_progress: dict = field(default_factory=dict)
    status: str = "OPERATIONAL"
    health: float = 1.0
    objective: str = "DISCOVER_POI"
    action: str = "search"
    sensor_state: str = "NOMINAL"
    comm_state: str = "ISOLATED"
    neighbors: list = field(default_factory=list)
    comp: int = 0
    obs: dict = field(
        default_factory=dict
    )  # "<node>|<poi>" -> record  (LocalWorldModel.observations)
    own_cells: set = field(default_factory=set)
    peer_cells: set = field(default_factory=set)
    peer_pos: dict = field(default_factory=dict)  # node -> (x, y, t)
    peer_target: dict = field(default_factory=dict)  # node -> (cell, t)
    last_sync: dict = field(default_factory=dict)  # node -> t
    skills: dict = field(default_factory=dict)  # name -> Skill  (local skill registry)
    rejected: set = field(default_factory=set)
    target: tuple | None = None  # ("cell"|"poi"|"pos", value)
    redundancy_hits: int = 0
    isolated_ticks: int = 0
    used_skill: bool = False
    last_key: tuple | None = None

    @property
    def alive(self) -> bool:
        return self.status == "OPERATIONAL"

    def active_skill(self) -> Skill | None:
        s = self.skills.get(SKILL)
        return s if s and s.status in ("LOCAL", "ADOPTED") else None


def _dist(ax, ay, bx, by) -> float:
    return math.hypot(ax - bx, ay - by)


def _cell_of(x: float, y: float) -> tuple[int, int]:
    return min(NX - 1, max(0, int(x // CW))), min(NY - 1, max(0, int(y // CH)))


def _center(c) -> tuple[float, float]:
    return (c[0] + 0.5) * CW, (c[1] + 0.5) * CH


def poi_view(u: Uav, poi: str, thr: float) -> dict | None:
    """What UAV `u` believes about `poi`, derived only from its own observation records."""
    recs = [r for k, r in sorted(u.obs.items()) if r["poi"] == poi]
    if not recs:
        return None
    best = max(recs, key=lambda r: (r["conf"], r["node"]))
    miss = 1.0
    for r in recs:
        miss *= 1.0 - r["conf"]
    comb = 1.0 - miss
    return {"conf": comb, "cls": best["cls"], "verified": best["conf"] >= thr or comb >= thr,
            "n": sum(r["n"] for r in recs), "last": max(r["t"] for r in recs),
            "nodes": [r["node"] for r in recs]}  # fmt: skip


class MissionSim:
    def __init__(self, cfg: MissionConfig):
        self.cfg, self.t, self.tick, self.status = cfg, 0.0, 0, "RUNNING"
        s = cfg.seed
        self.required = cfg.required_pois or cfg.n_pois
        self.terrain = Terrain.generate(
            int(W / CELL_M), CELL_M, s, height=int(H / CELL_M), style="alpine"
        )
        self.rng_sense = random.Random(f"{s}:sense")
        self.rf = RFEngine(self.ground_elev)
        self._build_pois(random.Random(f"{s}:pois"))
        self._build_uavs(random.Random(f"{s}:uavs"))
        self._build_events(random.Random(f"{s}:events"))
        self.events: list[dict] = []
        self.decisions: list[dict] = []
        self.links: list[dict] = []
        self.n_components = 1
        self.global_cells: dict = {}  # truth only (stats): cell -> first node
        self.stats = {"redundantCellMarks": 0, "uniqueCellMarks": 0, "skillsLearned": 0,
                      "skillTransfers": 0, "skillAdoptions": 0, "skillRejections": 0,
                      "partitions": 0, "dataSyncs": 0}  # fmt: skip
        self._seen = {"disc": set(), "ver": set()}
        self.frames: list[dict] = []
        self.emit(
            "MISSION_STARTED",
            True,
            requiredPois=self.required,
            totalPois=cfg.n_pois,
            timeLimit=cfg.time_limit,
        )
        self._exchange_and_links()
        self.frames.append(self.frame())

    def ground_elev(self, x: float, y: float) -> float:
        t = self.terrain
        return t.elev[min(t.size - 1, max(0, int(x // CELL_M)))][
            min(t.height - 1, max(0, int(y // CELL_M)))
        ]

    # ---------------------------------------------------------------- scenario (seed -> world)
    def _build_pois(self, r: random.Random) -> None:
        self.pois: list[dict] = []
        while len(self.pois) < self.cfg.n_pois:
            x, y = r.uniform(0.06 * W, 0.94 * W), r.uniform(0.06 * H, 0.94 * H)
            if all(_dist(x, y, p["x"], p["y"]) > 60_000 for p in self.pois):
                self.pois.append(
                    {
                        "id": f"POI-{len(self.pois) + 1:02d}",
                        "x": x,
                        "y": y,
                        "trueType": r.choice(POI_TYPES),
                    }
                )

    def _build_uavs(self, r: random.Random) -> None:
        cx, cy = r.uniform(0.05 * W, 0.15 * W), r.uniform(0.3 * H, 0.7 * H)
        self.uavs: list[Uav] = []
        for i in range(self.cfg.n_uavs):
            sp, sr, alt = UAV_SPEED_MPS, UAV_SENSOR_M, UAV_ALT_M
            a = 2 * math.pi * i / self.cfg.n_uavs + r.uniform(-0.3, 0.3)
            rad = r.uniform(5_000, 15_000)
            nid = f"UAV-{i + 1:02d}"
            br = random.Random(f"{self.cfg.seed}:bias:{nid}")
            self.uavs.append(Uav(nid, cx + rad * math.cos(a), cy + rad * math.sin(a), sp, sr, alt,
                                 r.randint(10, 24), {c: br.random() for c in ALL_CELLS}, heading=a, alt=alt))  # fmt: skip
        self.by_id = {u.id: u for u in self.uavs}

    def _build_events(self, r: random.Random) -> None:
        mk = lambda i, typ, **k: {
            "id": f"EVT-{i}",
            "type": typ,
            "active": False,
            "endTime": None,
            "started": False,
            "ended": False,
            **k,
        }  # noqa: E731
        L = self.cfg.time_limit
        self.disruptions = [
            mk(
                1,
                "COMMUNICATION_DEGRADATION",
                startTime=r.uniform(0.06, 0.12) * L,
                duration=r.uniform(0.12, 0.18) * L,
                x=r.uniform(0.25, 0.65) * W,
                y=r.uniform(0.3, 0.7) * H,
                radius=r.uniform(45_000, 70_000),
                vx=r.uniform(-8, 8),
                vy=r.uniform(-8, 8),
                severity=0.9,
            ),  # fmt: skip
            mk(
                2,
                "NAVIGATION_DEGRADATION",
                startTime=r.uniform(0.02, 0.07) * L,
                duration=r.uniform(0.15, 0.22) * L,
                x=r.uniform(0.2, 0.7) * W,
                y=r.uniform(0.2, 0.8) * H,
                radius=r.uniform(30_000, 45_000),
                vx=0.0,
                vy=0.0,
                severity=0.6,
            ),  # fmt: skip
            mk(
                3,
                "PLATFORM_FAILURE",
                startTime=r.uniform(0.45, 0.6) * L,
                duration=0.0,
                node=f"UAV-{r.randint(2, self.cfg.n_uavs):02d}",
                severity=1.0,
            ),  # fmt: skip
        ]
        for d in self.disruptions:
            d["endTime"] = d["startTime"] + d["duration"] if d["duration"] else None

    # ---------------------------------------------------------------- events / logs
    def emit(self, typ: str, demo: bool, **kw) -> dict:
        e = {
            "id": f"E-{len(self.events) + 1:04d}",
            "type": typ,
            "timestamp": round(self.t, 2),
            "demo": demo,
            **kw,
        }
        self.events.append(e)
        return e

    def decide_log(
        self,
        u: Uav,
        objective: str,
        action: str,
        reason: str,
        metrics: dict,
        skill: Skill | None,
        target,
    ) -> None:
        key = (objective, action, str(target), skill.id if skill else None)
        if key == u.last_key:
            return
        u.last_key = key
        self.decisions.append({"timestamp": round(self.t, 2), "nodeId": u.id, "state": objective, "action": action,
                               "reason": reason, "metrics": {k: round(v, 3) for k, v in metrics.items()},
                               "skillUsed": skill.id if skill else None, "target": target})  # fmt: skip

    # ---------------------------------------------------------------- disruptions
    def _zone(self, typ: str):
        return [d for d in self.disruptions if d["type"] == typ and d["active"]]

    def _update_disruptions(self) -> None:
        for d in self.disruptions:
            if d["active"] and d["type"] != "PLATFORM_FAILURE":
                d["x"] += d["vx"] * self.cfg.dt
                d["y"] += d["vy"] * self.cfg.dt
            if not d["started"] and self.t >= d["startTime"]:
                d["started"] = d["active"] = True
                if d["type"] == "PLATFORM_FAILURE":
                    u = self.by_id[d["node"]]
                    u.status, u.health, u.speed = "FAILED", 0.0, 0.0
                    self.emit("UAV_FAILED", True, nodeId=u.id, eventId=d["id"])
                    d["active"], d["ended"] = False, True
                else:
                    self.emit("DISRUPTION_STARTED", True, eventId=d["id"], disruptionType=d["type"],
                              position={"x": d["x"], "y": d["y"]}, radius=d["radius"], severity=d["severity"])  # fmt: skip
            elif d["active"] and d["endTime"] is not None and self.t >= d["endTime"]:
                d["active"], d["ended"] = False, True
                self.emit("DISRUPTION_ENDED", True, eventId=d["id"], disruptionType=d["type"])

    def _in_zone(self, typ: str, x: float, y: float):
        for d in self._zone(typ):
            if _dist(x, y, d["x"], d["y"]) < d["radius"]:
                return d
        return None

    # ---------------------------------------------------------------- per-node decisions
    def _local_pois(self, u: Uav) -> dict:
        thr = self.cfg.verify_conf
        return {p["id"]: v for p in self.pois if (v := poi_view(u, p["id"], thr))}

    def _pick_cell(self, u: Uav, skill: Skill | None) -> tuple[int, int]:
        cands = [c for c in ALL_CELLS if c not in u.own_cells]
        if not cands:  # local sweep complete: start another
            u.own_cells.clear()
            cands = list(ALL_CELLS)
        peers = [v for v in u.peer_pos.values()]
        if skill:  # skill: exclude cells peers cover / claim, and keep spacing from peers
            cands = [c for c in cands if c not in u.peer_cells] or cands
            claimed = {c for c, t in u.peer_target.values() if self.t - t < 150}
            cands = [c for c in cands if c not in claimed] or cands
            sp = skill.metadata["spacing_m"]

        def cost(c):
            cx, cy = _center(c)
            d = _dist(u.x, u.y, cx, cy)
            pen = (
                sum(max(0.0, sp - _dist(cx, cy, px, py)) for px, py, _ in peers) * 0.8
                if skill
                else 0.0
            )
            return (d + pen) * (1 + 0.25 * u.bias[c]), c

        return min(cands, key=cost)

    def _decide(self, u: Uav, rng: random.Random) -> None:
        cfg, loc = self.cfg, self._local_pois(u)
        verified = [p for p, v in loc.items() if v["verified"]]
        skill = u.active_skill() if cfg.skills_enabled else None
        m = {
            "neighbors": len(u.neighbors),
            "verifiedKnown": len(verified),
            "discoveredKnown": len(loc),
        }
        tgt, obj, act, reason, used = None, "DISCOVER_POI", "search", "", None
        zone = self._in_zone("NAVIGATION_DEGRADATION", u.x, u.y)
        uncertain = [p for p in self.pois if p["id"] in loc and not loc[p["id"]]["verified"]]
        if zone:  # 1. stay operational
            obj, act = "STAY_OPERATIONAL", "leave_degradation_zone"
            reason = "Inside navigation/sensor degradation zone."
            n = max(1.0, _dist(u.x, u.y, zone["x"], zone["y"]))
            tgt = (u.x + (u.x - zone["x"]) / n * 20_000, u.y + (u.y - zone["y"]) / n * 20_000)
        elif uncertain:  # 4. verify uncertain POIs (nearest locally-known unverified)
            p = min(uncertain, key=lambda p: (_dist(u.x, u.y, p["x"], p["y"]), p["id"]))
            obj, act, tgt = "VERIFY_POI", "approach_poi", (p["x"], p["y"])
            reason = (
                f"{p['id']} is known but confidence {loc[p['id']]['conf']:.2f} < {cfg.verify_conf}."
            )
            m["confidence"] = loc[p["id"]]["conf"]
            u.target = ("poi", p["id"])
        elif len(verified) >= self.required or (
            verified and self.t >= cfg.rendezvous_after * cfg.time_limit
        ):  # 6. share: spread what is known
            for k in [
                k
                for k, v in u.peer_pos.items()
                if k not in u.neighbors and _dist(u.x, u.y, v[0], v[1]) < 8_000
            ]:
                del u.peer_pos[k]  # reached the last-known spot and nobody is there: stale
            others = [(v, k) for k, v in sorted(u.peer_pos.items()) if k not in u.neighbors]
            if u.neighbors and not others:
                obj, act, tgt, reason = (
                    "SHARE_INFORMATION",
                    "hold_position",
                    None,
                    "All required POIs verified; holding link.",
                )
            elif others:
                (px, py, _), k = min(
                    others, key=lambda o: (_dist(u.x, u.y, o[0][0], o[0][1]), o[1])
                )
                obj, act, tgt = "SHARE_INFORMATION", "move_toward_peer", (px, py)
                reason = f"Holding {len(verified)} verified POIs; carrying knowledge toward last-known position of {k}."
            else:
                obj, act, tgt, reason = (
                    "SHARE_INFORMATION",
                    "hold_position",
                    None,
                    "All required POIs verified; no peers known.",
                )
        elif (
            u.isolated_ticks >= cfg.isolated_ticks_before_rendezvous and u.peer_pos
        ):  # 5. connectivity
            k, (px, py, _) = min(
                sorted(u.peer_pos.items()), key=lambda i: (_dist(u.x, u.y, i[1][0], i[1][1]), i[0])
            )
            obj, act, tgt = "MAINTAIN_CONNECTIVITY", "rejoin_peer", (px, py)
            reason = (
                f"No RF link for {u.isolated_ticks} ticks; heading to last-known position of {k}."
            )
            m["isolatedTicks"] = u.isolated_ticks
        else:  # 3. discover
            cell = u.target[1] if u.target and u.target[0] == "cell" else None
            stale = (
                cell is None or cell in u.own_cells or (skill is not None and cell in u.peer_cells)
            )
            if stale:
                cell = self._pick_cell(u, skill)
                u.target = ("cell", cell)
                if skill is None and cell in u.peer_cells and cell not in u.own_cells:
                    u.redundancy_hits += (
                        1  # baseline notices it is re-searching what a peer already covered
                    )
                    m["redundancyHits"] = u.redundancy_hits
            tgt = _center(cell)
            if skill:
                used = skill
                reason = f"Search cell {cell} chosen with peer coverage exclusion and {skill.metadata['spacing_m']:.0f} m spacing."
            else:
                reason = f"Nearest unsearched cell {cell} (local coverage only)."
            m["cell"] = cell[0] * 100 + cell[1]
            act = "search_cell"
        u.objective, u.action = obj, act
        if skill and obj == "DISCOVER_POI" and not u.used_skill:
            u.used_skill = True
            self.emit(
                "SKILL_USED",
                True,
                nodeId=u.id,
                skillId=skill.id,
                version=skill.version,
                behavior="search_cell_selection",
            )
        if obj != "DISCOVER_POI":
            u.target = u.target if obj == "VERIFY_POI" else u.target
        self.decide_log(u, obj, act, reason, m, used, list(map(round, tgt)) if tgt else None)
        # altitude: climb for LOS/horizon while isolated, settle back to cruise altitude once linked
        if u.isolated_ticks >= 3 and u.alt < ALT_MAX_M:
            u.alt = min(ALT_MAX_M, u.alt + CLIMB_M_PER_TICK)
            if not u.climbing:
                u.climbing = True
                self.decisions.append({"timestamp": round(self.t, 2), "nodeId": u.id, "state": "MAINTAIN_CONNECTIVITY", "action": "climb_for_los",
                                       "reason": f"No RF link for {u.isolated_ticks} ticks; gaining altitude to extend horizon and clear terrain.",
                                       "metrics": {"altitudeMeters": u.alt}, "skillUsed": None, "target": None})  # fmt: skip
        elif u.neighbors and u.alt > u.alt_base:
            u.alt = max(u.alt_base, u.alt - CLIMB_M_PER_TICK)
            u.climbing = False
        # move
        sp = u.speed_max * (1 - 0.5 * zone["severity"]) if zone else u.speed_max
        if tgt is None:
            u.speed = 0.0
            return
        d = _dist(u.x, u.y, *tgt)
        step = min(d, sp * cfg.dt)
        if d > 1e-6:
            u.heading = math.atan2(tgt[1] - u.y, tgt[0] - u.x)
            u.x = min(W, max(0.0, u.x + math.cos(u.heading) * step))
            u.y = min(H, max(0.0, u.y + math.sin(u.heading) * step))
        u.speed = step / cfg.dt

    # ---------------------------------------------------------------- sensing
    def _sense(self, u: Uav) -> None:
        zone = self._in_zone("NAVIGATION_DEGRADATION", u.x, u.y)
        r = u.sensor_r * (1 - 0.6 * zone["severity"]) if zone else u.sensor_r
        u.sensor_state = "DEGRADED" if zone else "NOMINAL"
        for c in ALL_CELLS:
            cx, cy = _center(c)
            if c not in u.own_cells and _dist(u.x, u.y, cx, cy) <= r + 0.5 * CH:
                u.own_cells.add(c)
                if c in self.global_cells and self.global_cells[c] != u.id:
                    self.stats["redundantCellMarks"] += 1
                elif c not in self.global_cells:
                    self.global_cells[c] = u.id
                    self.stats["uniqueCellMarks"] += 1
        tc = (int(u.x // CELL_M), int(u.y // CELL_M))
        for p in self.pois:
            d = _dist(u.x, u.y, p["x"], p["y"])
            if d > r:
                continue
            pc = (
                min(self.terrain.size - 1, int(p["x"] // CELL_M)),
                min(self.terrain.height - 1, int(p["y"] // CELL_M)),
            )
            tc = (min(self.terrain.size - 1, tc[0]), min(self.terrain.height - 1, tc[1]))
            if self.rng_sense.random() >= self.terrain.detect_p(tc, pc, max(1, int(r // CELL_M))):
                continue
            conf = min(
                0.99, max(0.05, 0.4 + 0.58 * (1 - d / r) + self.rng_sense.uniform(-0.08, 0.08))
            )
            cls = (
                p["trueType"]
                if self.rng_sense.random() < conf
                else self.rng_sense.choice(POI_TYPES)
            )
            k = f"{u.id}|{p['id']}"
            rec = u.obs.get(k) or {
                "node": u.id,
                "poi": p["id"],
                "conf": 0.0,
                "cls": cls,
                "n": 0,
                "t": 0.0,
            }
            rec["n"] += 1
            rec["t"] = round(self.t, 2)
            if conf > rec["conf"]:
                rec["conf"], rec["cls"] = conf, cls
            u.obs[k] = rec

    # ---------------------------------------------------------------- RF
    def _compute_links(self) -> None:
        ops = [u for u in self.uavs if u.alive]
        zones = [
            {"x": z["x"], "y": z["y"], "radius": z["radius"], "severity": z["severity"]}
            for z in self._zone("COMMUNICATION_DEGRADATION")
        ]
        links = self.rf.compute_links(
            [RFNode(u.id, u.x, u.y, u.alt, RF_PROFILE) for u in ops], zones, self.t
        )
        self.links = links
        for u in self.uavs:
            u.neighbors = []
        for l in links:
            if l["connected"]:
                self.by_id[l["sourceNodeId"]].neighbors.append(l["targetNodeId"])
                self.by_id[l["targetNodeId"]].neighbors.append(l["sourceNodeId"])
        seen: dict = {}
        for u in ops:  # connected components of G(t)
            if u.id in seen:
                continue
            stack = [u.id]
            seen[u.id] = len(set(seen.values()))
            while stack:
                for n in self.by_id[stack.pop()].neighbors:
                    if n not in seen:
                        seen[n] = seen[u.id]
                        stack.append(n)
        for u in self.uavs:
            u.comp = seen.get(u.id, -1)
            degraded = any(
                not l["connected"]
                and l["disruptionFactor"] < 0.99
                and u.id in (l["sourceNodeId"], l["targetNodeId"])
                for l in links
            )  # noqa: E741
            u.comm_state = (
                "OFFLINE"
                if not u.alive
                else "CONNECTED"
                if u.neighbors
                else "DEGRADED"
                if degraded
                else "ISOLATED"
            )
            u.isolated_ticks = u.isolated_ticks + 1 if (u.alive and not u.neighbors) else 0
        n = len(set(seen.values()))
        if n != self.n_components:
            if (n > 1) != (self.n_components > 1):
                comps: dict = {}
                for k, c in seen.items():
                    comps.setdefault(c, []).append(k)
                if n > 1:
                    self.stats["partitions"] += 1
                self.emit("NETWORK_PARTITIONED" if n > 1 else "NETWORK_RECONNECTED", True,
                          components=[sorted(v) for v in comps.values()])  # fmt: skip
            else:
                self.emit("NETWORK_TOPOLOGY_CHANGED", False, componentCount=n)
            self.n_components = n

    # ---------------------------------------------------------------- P2P: data + skills (only over connected links)
    def _exchange_and_links(self) -> None:
        self._compute_links()
        snap = {u.id: {"obs": {k: dict(v) for k, v in u.obs.items()}, "cells": u.own_cells | u.peer_cells,
                       "pos": (u.x, u.y), "target": u.target[1] if u.target and u.target[0] == "cell" else None,
                       "peers": dict(u.peer_pos), "skills": {n: s.copy() for n, s in u.skills.items() if s.status in ("LOCAL", "ADOPTED")}}
                for u in self.uavs if u.alive}  # fmt: skip
        for l in self.links:  # noqa: E741
            if not l["connected"]:
                continue
            a, b = self.by_id[l["sourceNodeId"]], self.by_id[l["targetNodeId"]]
            self.stats["dataSyncs"] += 1
            for me, peer in ((a, b), (b, a)):
                s = snap[peer.id]
                for k, rec in s[
                    "obs"
                ].items():  # DATA SHARING: last-writer-wins per (observer, poi)
                    if k not in me.obs or rec["n"] > me.obs[k]["n"]:
                        me.obs[k] = dict(rec)
                me.peer_cells |= s["cells"] - me.own_cells
                for k, v in list(s["peers"].items()) + [(peer.id, (*s["pos"], self.t))]:
                    if k != me.id and (k not in me.peer_pos or v[2] >= me.peer_pos[k][2]):
                        me.peer_pos[k] = v
                if s["target"] is not None:
                    me.peer_target[peer.id] = (s["target"], self.t)
                me.last_sync[peer.id] = self.t
                if (
                    self.cfg.skills_enabled
                ):  # SKILL SHARING: manifest compare, transfer missing/newer
                    for name, sk in sorted(s["skills"].items()):
                        mine = me.skills.get(name)
                        if sk.id in me.rejected or (
                            mine and (mine.version, mine.utility) >= (sk.version, sk.utility)
                        ):
                            continue
                        key = (
                            peer.id,
                            sk.id,
                        )  # transfer is paced by link bandwidth (resumable across ticks)
                        me.skill_progress[key] = (
                            me.skill_progress.get(key, 0.0)
                            + l["bandwidthFactor"] * self.cfg.dt / self.cfg.skill_transfer_s
                        )
                        if me.skill_progress[key] < 1.0:
                            continue
                        del me.skill_progress[key]
                        new = sk.copy()
                        new.status, new.received_at, new.received_from = "RECEIVED", self.t, peer.id
                        new.validate_left = self.cfg.validation_ticks
                        me.skills[name] = new
                        self.stats["skillTransfers"] += 1
                        self.emit("SKILL_TRANSFERRED", True, sourceNodeId=peer.id, targetNodeId=me.id, skillId=sk.id,
                                  version=sk.version, rfQuality=l["rfQuality"], bandwidthFactor=l["bandwidthFactor"])  # fmt: skip
                        self.emit(
                            "SKILL_RECEIVED", False, nodeId=me.id, skillId=sk.id, fromNodeId=peer.id
                        )

    def _skill_lifecycle(self) -> None:
        for u in self.uavs:
            if not u.alive or not self.cfg.skills_enabled:
                continue
            for sk in u.skills.values():
                if sk.status == "RECEIVED":
                    sk.status = "VALIDATING"
                elif sk.status == "VALIDATING":
                    sk.validate_left -= 1
                    if sk.validate_left <= 0:
                        if sk.utility >= self.cfg.min_adopt_utility and sk.confidence >= 0.5:
                            sk.status = "ADOPTED"
                            self.stats["skillAdoptions"] += 1
                            self.emit(
                                "SKILL_ADOPTED",
                                True,
                                nodeId=u.id,
                                skillId=sk.id,
                                version=sk.version,
                                fromNodeId=sk.received_from,
                            )
                        else:
                            sk.status = "REJECTED"
                            u.rejected.add(sk.id)
                            self.stats["skillRejections"] += 1
                            self.emit(
                                "SKILL_REJECTED",
                                True,
                                nodeId=u.id,
                                skillId=sk.id,
                                reason="utility below adoption threshold",
                            )
            if SKILL not in u.skills and u.redundancy_hits >= u.learn_threshold:
                util = round(min(1.0, 0.55 + 0.05 * u.redundancy_hits), 2)
                sk = Skill(SKILL, 1, u.id, round(self.t, 2), 0.8, util, "SEARCH_REGION_SELECTION",
                           {"spacing_m": 80_000.0, "excludes_peer_covered_cells": True, "excludes_peer_claimed_cells": True,
                            "trigger": f"{u.redundancy_hits} redundant search selections"})  # fmt: skip
                u.skills[SKILL] = sk
                self.stats["skillsLearned"] += 1
                self.emit("SKILL_LEARNED", True, nodeId=u.id, skillId=sk.id, version=1, utilityScore=util,
                          reason=f"Re-searched {u.redundancy_hits} cells already covered by peers; learned spacing/coordination strategy.")  # fmt: skip

    # ---------------------------------------------------------------- mission state
    def _fleet(self) -> dict:
        ops = [u for u in self.uavs if u.alive]
        thr = self.cfg.verify_conf
        pois, ver_ids = [], set()
        for p in self.pois:
            views = {u.id: poi_view(u, p["id"], thr) for u in ops}
            known = {k: v for k, v in views.items() if v}
            ver = sorted(k for k, v in known.items() if v["verified"])
            best = max(known.items(), key=lambda kv: (kv[1]["conf"], kv[0]), default=(None, None))[
                1
            ]
            if ver:
                ver_ids.add(p["id"])
            pois.append({"id": p["id"], "position": {"x": round(p["x"], 1), "y": round(p["y"], 1)}, "trueType": p["trueType"],
                         "state": "VERIFIED" if ver else "DISCOVERED" if known else "UNKNOWN",
                         "discovered": bool(known), "verified": bool(ver),
                         "classification": best["cls"] if best else "UNKNOWN", "confidence": round(best["conf"], 3) if best else 0.0,
                         "observationCount": max((v["n"] for v in known.values()), default=0),
                         "lastObserved": max((v["last"] for v in known.values()), default=None),
                         "knownBy": sorted(known), "verifiedBy": ver})  # fmt: skip
        cov = 0.0
        if ver_ids and ops:
            cov = sum(
                len(ver_ids & {p for p, v in self._local_pois(u).items() if v["verified"]})
                / len(ver_ids)
                for u in ops
            ) / len(ops)
        return {
            "pois": pois,
            "verified": len(ver_ids),
            "discovered": sum(p["discovered"] for p in pois),
            "coverage": cov,
            "ops": len(ops),
        }

    def _update_status(self, f: dict) -> None:
        for p in f["pois"]:
            if p["discovered"] and p["id"] not in self._seen["disc"]:
                self._seen["disc"].add(p["id"])
                self.emit(
                    "POI_DISCOVERED",
                    True,
                    poiId=p["id"],
                    nodeId=p["knownBy"][0],
                    confidence=p["confidence"],
                )
            if p["verified"] and p["id"] not in self._seen["ver"]:
                self._seen["ver"].add(p["id"])
                self.emit("POI_VERIFIED", True, poiId=p["id"], nodeId=p["verifiedBy"][0], confidence=p["confidence"],
                          classification=p["classification"])  # fmt: skip
        if self.status != "RUNNING":
            return
        if f["verified"] >= self.required and f["coverage"] >= self.cfg.knowledge_threshold:
            self.status = "SUCCESS"
            self.emit(
                "MISSION_SUCCESS",
                True,
                elapsedTime=round(self.t, 2),
                verifiedPois=f["verified"],
                fleetKnowledgeCoverage=round(f["coverage"], 3),
            )
        elif self.t >= self.cfg.time_limit or f["ops"] == 0:
            self.status = "FAILED"
            self.emit(
                "MISSION_FAILED",
                True,
                elapsedTime=round(self.t, 2),
                verifiedPois=f["verified"],
                fleetKnowledgeCoverage=round(f["coverage"], 3),
            )

    def step(self) -> None:
        if self.status != "RUNNING":
            return
        self.tick += 1
        self.t = round(self.tick * self.cfg.dt, 6)
        self._update_disruptions()
        rng = random.Random(f"{self.cfg.seed}:nav:{self.tick}")
        for u in self.uavs:
            if u.alive:
                self._decide(u, rng)
                self._sense(u)
        self._exchange_and_links()
        self._skill_lifecycle()
        self.frames.append(self.frame())

    # ---------------------------------------------------------------- frontend-facing frame
    def frame(self) -> dict:
        f = self._fleet()
        self._update_status(f)
        mission = {"seed": self.cfg.seed, "status": self.status, "elapsedTime": round(self.t, 2), "timeLimit": self.cfg.time_limit,
                   "totalPois": len(self.pois), "requiredPois": self.required, "discoveredPois": f["discovered"],
                   "verifiedPois": f["verified"], "fleetKnowledgeCoverage": round(f["coverage"], 3),
                   "knowledgeThreshold": self.cfg.knowledge_threshold, "operationalNodes": f["ops"], "totalNodes": len(self.uavs)}  # fmt: skip
        uavs = []
        for u in self.uavs:
            loc = self._local_pois(u)
            sk = u.active_skill() if self.cfg.skills_enabled else None
            uavs.append({"id": u.id, "status": u.status, "position": {"x": round(u.x, 1), "y": round(u.y, 1)},
                         "heading": round(u.heading, 3), "speed": round(u.speed, 1), "health": u.health,
                         "sensorRadius": u.sensor_r, "altitudeMeters": u.alt, "commRadius": RF_PROFILE.nominal_range_m, "currentObjective": u.objective if u.alive else "NONE",
                         "currentAction": u.action if u.alive else "failed", "sensorState": u.sensor_state if u.alive else "OFFLINE",
                         "communicationState": u.comm_state, "neighbors": sorted(u.neighbors), "networkComponent": u.comp,
                         "activeSkill": sk.id if sk else None, "skills": [s.to_dict() for _, s in sorted(u.skills.items())],
                         "localKnowledgeCount": len(u.obs), "knownPois": sorted(loc), "verifiedPois": sorted(p for p, v in loc.items() if v["verified"]),
                         "searchedCells": len(u.own_cells), "lastSync": {k: v for k, v in sorted(u.last_sync.items())}})  # fmt: skip
        dis = [{"id": d["id"], "type": d["type"], "active": d["active"], "startTime": round(d["startTime"], 2), "endTime": d["endTime"] and round(d["endTime"], 2),
                "position": {"x": round(d["x"], 1), "y": round(d["y"], 1)} if "radius" in d else None, "radius": d.get("radius"),
                "velocity": {"x": d["vx"], "y": d["vy"]} if "radius" in d else None, "severity": d["severity"], "nodeId": d.get("node")}
               for d in self.disruptions]  # fmt: skip
        return {"tick": self.tick, "time": round(self.t, 2), "mission": mission, "uavs": uavs, "pois": f["pois"],
                "links": self.links, "disruptions": dis, "eventCount": len(self.events), "decisionCount": len(self.decisions)}  # fmt: skip

    def spec(self) -> dict:
        """Static platform data for the UAV spec panel (identical for every UAV)."""
        c = self.cfg
        return {
            "count": c.n_uavs,
            "platformClass": "Abstract fixed-wing recon UAV (all units identical)",
            "cruiseSpeedMps": UAV_SPEED_MPS,
            "cruiseSpeedKmh": round(UAV_SPEED_MPS * 3.6, 1),
            "cruiseAltitudeAglMeters": UAV_ALT_M,
            "maxAltitudeAglMeters": ALT_MAX_M,
            "climbRateMetersPerTick": CLIMB_M_PER_TICK,
            "climbRateMps": CLIMB_M_PER_TICK / c.dt,
            "nominalSpeedInNavDegradationFactor": 0.7,
            "sensor": {
                "type": "Wide-area EO/IR (abstract)",
                "radiusMeters": UAV_SENSOR_M,
                "radiusInNavDegradationFactor": 0.64,
                "detection": "Per-tick detection probability from terrain line-of-sight and vegetation concealment; confidence 0.4-0.98 rises as range closes.",
                "searchCellMeters": [CW, CH],
            },
            "comms": {
                "nominalRangeMeters": RF_PROFILE.nominal_range_m,
                "extendedRangeMeters": RF_PROFILE.extended_range_m,
                "horizonAtCruiseMeters": geometric_horizon_m(UAV_ALT_M, UAV_ALT_M),
                "horizonAtMaxAltitudeMeters": geometric_horizon_m(ALT_MAX_M, ALT_MAX_M),
            },
            "autonomy": "Local decisions only: objective priority STAY_OPERATIONAL > VERIFY_POI > SHARE_INFORMATION > MAINTAIN_CONNECTIVITY > DISCOVER_POI",
            "learnedSkills": [SKILL],
        }

    def rf_model(self) -> dict:
        rc = self.rf.cfg
        return {
            "connectedThreshold": rc.connected_threshold,
            "maxRoutineRangeMeters": rc.max_routine_range_m,
            "reportRangeMeters": rc.report_range_m,
            "stateThresholds": {
                "EXCELLENT": rc.state_thresholds[0],
                "GOOD": rc.state_thresholds[1],
                "DEGRADED": rc.state_thresholds[2],
                "MARGINAL": rc.state_thresholds[3],
            },
            "horizonFormulaKm": "4.12 * (sqrt(h1_m) + sqrt(h2_m))",
            "updateIntervalSeconds": self.cfg.dt,
        }

    def rules(self) -> dict:
        c = self.cfg
        return {
            "timeLimitSeconds": c.time_limit,
            "tickSeconds": c.dt,
            "totalPois": c.n_pois,
            "requiredPois": self.required,
            "knowledgeThreshold": c.knowledge_threshold,
            "verifyConfidence": c.verify_conf,
            "skillTransferSecondsAtFullBandwidth": c.skill_transfer_s,
            "skillValidationTicks": c.validation_ticks,
            "minAdoptUtility": c.min_adopt_utility,
            "poiTypes": list(POI_TYPES),
            "disruptionTypes": [
                "COMMUNICATION_DEGRADATION",
                "NAVIGATION_DEGRADATION",
                "PLATFORM_FAILURE",
            ],
        }

    def result(self) -> dict:
        last = self.frames[-1]["mission"]
        st = dict(self.stats)
        tot = st["redundantCellMarks"] + st["uniqueCellMarks"]
        st["redundancyRatio"] = round(st["redundantCellMarks"] / tot, 3) if tot else 0.0
        st["missionStatus"], st["elapsedTime"] = last["status"], last["elapsedTime"]
        st["firstSkillLearnedAt"] = next(
            (e["timestamp"] for e in self.events if e["type"] == "SKILL_LEARNED"), None
        )
        st["finalSkillHolders"] = sum(1 for u in self.uavs if u.active_skill() and u.alive)
        return {"meta": {"seed": self.cfg.seed, "dt": self.cfg.dt, "skillsEnabled": self.cfg.skills_enabled, "world": {"width": W, "height": H, "tileMeters": TILE_M, "tilesX": TILES_X, "tilesY": TILES_Y, "units": "meters"},
                         "searchGrid": {"nx": NX, "ny": NY}, "uavSpec": self.spec(), "rfModel": self.rf_model(), "missionRules": self.rules(), "config": {k: v for k, v in self.cfg.__dict__.items()}},
                "frames": self.frames, "events": self.events, "decisions": self.decisions, "stats": st}  # fmt: skip


def round_floats(o, n: int = 3):
    if isinstance(o, float):
        return round(o, n)
    if isinstance(o, dict):
        return {k: round_floats(v, n) for k, v in o.items()}
    if isinstance(o, list):
        return [round_floats(v, n) for v in o]
    return o


def run_mission(cfg: MissionConfig) -> dict:
    sim = MissionSim(cfg)
    while sim.status == "RUNNING":
        sim.step()
    return sim.result()
