"""Deterministic RF link model: distance, horizon, terrain LOS, attenuation, disruption zones."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class RFConfig:
    connected_threshold: float = 0.15
    max_routine_range_m: float = 120_000.0
    report_range_m: float = 150_000.0
    los_step_m: float = 5_000.0
    los_max_samples: int = 64
    los_clear_margin_m: float = 30.0
    partial_margin_m: float = 150.0
    partial_factor: float = 0.55
    blocked_factor: float = 0.08
    state_thresholds: tuple = (0.80, 0.60, 0.35, 0.10)  # EXCELLENT/GOOD/DEGRADED/MARGINAL
    los_cache_quant_m: float = 500.0


@dataclass(frozen=True)
class RFProfile:
    nominal_range_m: float
    extended_range_m: float
    quality_multiplier: float = 1.0
    relay_capable: bool = False


PROFILES = {
    "SCOUT": RFProfile(30e3, 90e3),
    "SENSOR": RFProfile(40e3, 100e3),
    "GENERAL": RFProfile(40e3, 100e3),
    "RELAY": RFProfile(60e3, 120e3, 1.0, True),
    "HIGH_ALTITUDE_RELAY": RFProfile(80e3, 120e3, 1.0, True),
}


@dataclass
class RFNode:
    id: str
    x: float
    y: float
    alt_agl_m: float
    profile: RFProfile


def geometric_horizon_m(h1_m: float, h2_m: float) -> float:
    return 4.12 * (math.sqrt(max(h1_m, 0.0)) + math.sqrt(max(h2_m, 0.0))) * 1000.0


def _smooth(a: float, b: float, x: float) -> float:
    if b <= a:
        return 1.0 if x >= b else 0.0
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


_KNOTS = ((0.0, 1.0), (20e3, 0.85), (40e3, 0.65), (60e3, 0.35), (80e3, 0.10))
_BW = ((0.10, 0.05), (0.35, 0.35), (0.60, 0.65), (0.80, 0.90), (1.0, 1.0))


def _distance_quality(dist: float, nominal: float, ext: float, tail_ok: bool) -> float:
    ref = dist * 40_000.0 / nominal
    for (a, qa), (b, qb) in zip(_KNOTS, _KNOTS[1:], strict=False):
        if ref <= b:
            return qa + (qb - qa) * _smooth(a, b, ref)
    if not tail_ok:
        return 0.0
    start = 80_000.0 * nominal / 40_000.0
    if ext <= start or dist >= ext:
        return 0.0
    return 0.10 * (1 - _smooth(start, ext, dist))


def _bandwidth(q: float) -> float:
    if q < _BW[0][0]:
        return 0.0
    for (a, fa), (b, fb) in zip(_BW, _BW[1:], strict=False):
        if q <= b:
            return fa + (fb - fa) * (q - a) / (b - a)
    return 1.0


def _link_class(d: float) -> str:
    return (
        "SHORT"
        if d < 20e3
        else "NORMAL"
        if d < 50e3
        else "STRONG_LOS"
        if d < 80e3
        else "EXTENDED_LOS"
    )


class RFEngine:
    def __init__(self, ground_elev: Callable[[float, float], float], cfg: RFConfig | None = None):
        self.ground_elev = ground_elev
        self.cfg = cfg or RFConfig()
        self.use_cache = True
        self._cache: dict = {}

    def _los(self, a: RFNode, b: RFNode):
        """Returns (label, factor, min_clearance). Works on quantized geometry so cache is exact."""
        q = self.cfg.los_cache_quant_m

        def qz(v):
            return round(v / q)

        key = (a.id, b.id, qz(a.x), qz(a.y), qz(a.alt_agl_m), qz(b.x), qz(b.y), qz(b.alt_agl_m))
        if self.use_cache and key in self._cache:
            return self._cache[key]
        ax, ay, bx, by = (qz(a.x) * q, qz(a.y) * q, qz(b.x) * q, qz(b.y) * q)
        za = self.ground_elev(ax, ay) + qz(a.alt_agl_m) * q
        zb = self.ground_elev(bx, by) + qz(b.alt_agl_m) * q
        n = min(
            self.cfg.los_max_samples,
            max(3, math.ceil(math.hypot(bx - ax, by - ay) / self.cfg.los_step_m) + 1),
        )
        c = min(
            (za + (zb - za) * t) - self.ground_elev(ax + (bx - ax) * t, ay + (by - ay) * t)
            for t in (i / (n - 1) for i in range(n))
        )
        cfg = self.cfg
        if c >= cfg.los_clear_margin_m:
            res = ("CLEAR", 1.0, c)
        elif c >= -cfg.partial_margin_m:
            res = ("PARTIAL", cfg.partial_factor, c)
        else:
            res = ("BLOCKED", cfg.blocked_factor, c)
        if self.use_cache:
            if len(self._cache) > 20000:
                self._cache.clear()
            self._cache[key] = res
        return res

    @staticmethod
    def _disruption(a: RFNode, b: RFNode, zones: list) -> float:
        f = 1.0
        for z in zones:
            inside = 0
            for i in range(16):
                t = i / 15
                if (
                    math.hypot(a.x + (b.x - a.x) * t - z["x"], a.y + (b.y - a.y) * t - z["y"])
                    <= z["radius"]
                ):
                    inside += 1
            cov = inside / 16
            if cov > 0:
                f *= 1 - z["severity"] * min(1.0, 0.4 + cov)
        return f

    def _state(self, q: float, connected: bool) -> str:
        if not connected:
            return "DISCONNECTED"
        for name, th in zip(
            ("EXCELLENT", "GOOD", "DEGRADED", "MARGINAL"), self.cfg.state_thresholds, strict=False
        ):
            if q >= th:
                return name
        return "MARGINAL"

    def compute_links(self, nodes: list, zones: list, t: float) -> list:
        cfg = self.cfg
        ns = sorted(nodes, key=lambda n: n.id)
        out = []
        for i, a in enumerate(ns):
            for b in ns[i + 1 :]:
                hd = math.hypot(a.x - b.x, a.y - b.y)
                d = math.sqrt(hd * hd + (a.alt_agl_m - b.alt_agl_m) ** 2)
                if d > cfg.report_range_m:
                    continue
                pa, pb = a.profile, b.profile
                ext = min(pa.extended_range_m, pb.extended_range_m)
                nominal = min(pa.nominal_range_m, pb.nominal_range_m)
                horizon = geometric_horizon_m(a.alt_agl_m, b.alt_agl_m)
                reject = (
                    "BEYOND_MAX_RANGE"
                    if d > min(cfg.max_routine_range_m, ext)
                    else "BEYOND_HORIZON"
                    if d > horizon
                    else None
                )
                dq = tf = pf = 0.0
                att = dis = 1.0
                los, minc = "NOT_EVALUATED", None
                if reject is None:
                    los, tf, minc = self._los(a, b)
                    dq = _distance_quality(d, nominal, ext, los == "CLEAR" and horizon >= 1.5 * d)
                    pf = pa.quality_multiplier * pb.quality_multiplier
                    att = 1 - 0.5 * _smooth(0.5 * horizon, horizon, d)
                    dis = self._disruption(a, b, zones)
                    q = min(1.0, max(0.0, dq * tf * att * dis * pf))
                else:
                    q = 0.0
                q = round(q, 4)
                conn = q >= cfg.connected_threshold
                out.append(
                    {
                        "id": f"{a.id}~{b.id}",
                        "sourceNodeId": a.id,
                        "targetNodeId": b.id,
                        "distanceMeters": d,
                        "horizontalDistanceMeters": hd,
                        "distanceKm": d / 1000.0,
                        "sourceAltitudeMeters": a.alt_agl_m,
                        "targetAltitudeMeters": b.alt_agl_m,
                        "geometricHorizonMeters": horizon,
                        "lineOfSight": los,
                        "rfQuality": q,
                        "bandwidthFactor": _bandwidth(q) if conn else 0.0,
                        "state": self._state(q, conn),
                        "connected": conn,
                        "attenuationFactor": att,
                        "disruptionFactor": dis,
                        "lastUpdated": t,
                        "debug": {
                            "distanceQuality": dq,
                            "terrainFactor": tf,
                            "platformFactor": pf,
                            "minClearanceMeters": minc,
                            "linkClass": _link_class(d),
                            "rejectReason": reject,
                        },
                    }
                )
        return out
