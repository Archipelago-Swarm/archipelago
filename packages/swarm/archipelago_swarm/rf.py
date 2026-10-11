"""Terrain-sensitive RF link model (interpretable, not an EM simulator).

link(a, b) = f(3D distance, terrain between the two airframes, radio constants):

    PL   = FSPL(d, f) + obstruction_loss(depth)       FSPL = 32.44 + 20log10(d_km) + 20log10(f_MHz)
    RSSI = tx_dbm - PL
    SNR  = RSSI - noise_dbm
    margin = SNR - snr_req_db
    state  = UP (margin >= up_margin_db) | DEGRADED (0 <= margin < up_margin_db) | DOWN (margin < 0)

``depth`` is how far the terrain pokes above the straight 3D line between the two airframes
(each flies ``agl_m`` above ground at its own cell); obstruction_loss = 0 for depth <= 0, else
min(max_obs_db, obs_base_db + obs_db_per_m * depth). No diffraction/Fresnel/multipath/fading.
Pure function of positions + terrain, so the same inputs always give the same link.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace

UP, DEGRADED, DOWN = "UP", "DEGRADED", "DOWN"


@dataclass(frozen=True)
class RFConfig:
    freq_mhz: float = 2400.0
    tx_dbm: float = 14.0
    noise_dbm: float = -95.0
    snr_req_db: float = 10.0
    up_margin_db: float = 3.0
    obs_base_db: float = 8.0
    obs_db_per_m: float = 0.2
    max_obs_db: float = 60.0
    max_bw_kbps: float = 250.0  # bandwidth at margin >= bw_full_margin_db
    bw_full_margin_db: float = 12.0
    sample_step_cells: float = 0.5
    hysteresis_db: float = 1.5  # applied by Network (needs the previous state), not by link()


@dataclass(frozen=True)
class Link:
    a: str
    b: str
    distance_m: float
    terrain_los: bool
    obstruction_depth_m: float
    obstruction_db: float
    path_loss_db: float
    rssi_dbm: float
    snr_db: float
    margin_db: float
    link_quality: float  # clamp(margin / bw_full_margin_db, 0, 1)
    bandwidth_kbps: float
    state: str

    def as_dict(self) -> dict:
        return asdict(self)


def _elev(terrain, x: float, y: float) -> float:
    """Bilinear ground elevation at fractional cell coordinates (clamped to the map)."""
    x = min(max(x, 0.0), terrain.size - 1.0)
    y = min(max(y, 0.0), terrain.height - 1.0)
    x0, y0 = int(x), int(y)
    x1, y1 = min(x0 + 1, terrain.size - 1), min(y0 + 1, terrain.height - 1)
    fx, fy = x - x0, y - y0
    e = terrain.elev
    top = e[x0][y0] * (1 - fx) + e[x1][y0] * fx
    bot = e[x0][y1] * (1 - fx) + e[x1][y1] * fx
    return top * (1 - fy) + bot * fy


def link(
    terrain, a: str, pa: tuple[int, int], b: str, pb: tuple[int, int], cfg: RFConfig | None = None
) -> Link:
    cfg = cfg or RFConfig()
    ha, hb = terrain.drone_alt(pa), terrain.drone_alt(pb)
    dxy = math.hypot(pb[0] - pa[0], pb[1] - pa[1]) * terrain.cell_m
    d = max(math.hypot(dxy, hb - ha), 1.0)
    depth = -1e9
    n = max(2, int(math.hypot(pb[0] - pa[0], pb[1] - pa[1]) / cfg.sample_step_cells))
    for k in range(1, n):
        t = k / n
        x, y = pa[0] + (pb[0] - pa[0]) * t, pa[1] + (pb[1] - pa[1]) * t
        depth = max(depth, _elev(terrain, x, y) - (ha + (hb - ha) * t))
    los = depth <= 0
    obs = 0.0 if los else min(cfg.max_obs_db, cfg.obs_base_db + cfg.obs_db_per_m * depth)
    pl = 32.44 + 20 * math.log10(d / 1000.0) + 20 * math.log10(cfg.freq_mhz) + obs
    rssi = cfg.tx_dbm - pl
    snr = rssi - cfg.noise_dbm
    margin = snr - cfg.snr_req_db
    state = UP if margin >= cfg.up_margin_db else DEGRADED if margin >= 0 else DOWN
    q = min(1.0, max(0.0, margin / cfg.bw_full_margin_db))
    bw = 0.0 if state == DOWN else cfg.max_bw_kbps * max(q, 0.05)
    return Link(
        *sorted_pair(a, b),
        round(d, 1),
        los,
        round(max(depth, 0.0), 1),
        round(obs, 2),
        round(pl, 2),
        round(rssi, 2),
        round(snr, 2),
        round(margin, 2),
        round(q, 3),
        round(bw, 1),
        state,
    )


def with_hysteresis(lk: Link, prev: str, cfg: RFConfig) -> Link:
    """Debounce: entering a better state needs hysteresis_db of extra margin than staying in it."""
    h, m = cfg.hysteresis_db, lk.margin_db
    up = m >= cfg.up_margin_db + (-h if prev == UP else h)
    alive = m >= (-h if prev != DOWN else h)
    state = UP if up else DEGRADED if alive else DOWN
    if state == lk.state:
        return lk
    bw = 0.0 if state == DOWN else cfg.max_bw_kbps * max(lk.link_quality, 0.05)
    return replace(lk, state=state, bandwidth_kbps=round(bw, 1))


def sorted_pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)
