# ruff: noqa: E501  (long prose and SVG/f-string lines)
"""Demo artifact generator: canonical recorded events in, files out. Pure stdlib, no I/O except `write_artifacts`.

Input is the list of canonical v0 records of one run (``WorldSnapshot``, ``MetricSample``,
``LearningEvent``, ``PeerEnvelope`` dicts, the shape of ``apps/web/src/fixtures/partition_run.json`` and
``GET /v1/runs/{id}/events``). ``meta`` carries what the records cannot: run/plan/commit/image digests/seeds
/wall time, ``max_ticks`` (to split ``sim_tick = episode * max_ticks + tick``, amendment A7) and
``episodes`` (list of ``{"kind": train|validation|test}`` in plan order).

Outputs (see ``build_artifacts``): summary.json, curves.csv, peer_decisions.csv, topology_snapshots.json,
node_timeline.json, learning_curve.svg, coverage_return.svg, partition_timeline.svg.
"""

from __future__ import annotations

import csv
import io
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

Event = Mapping[str, Any]
FAULT_PHASES = {0: "normal", 1: "partition", 2: "recovery"}
RETURN_PHASES = ("train", "eval", "partition", "recovery", "other")
MAX_TOPOLOGY_SNAPSHOTS = 12
# Okabe-Ito: distinguishable for common colour-vision deficiencies. Shapes/dashes duplicate colour.
PALETTE = ("#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#F0E442", "#000000")


# ----------------------------------------------------------------------------------------------
# normalisation
# ----------------------------------------------------------------------------------------------
def normalize(events: Iterable[Event] | Mapping[str, Any]) -> list[dict[str, Any]]:
    """Accept a list or ``{"events": [...]}``; drop duplicate event ids; order by (sequence, sim_tick)."""
    if isinstance(events, Mapping):
        events = events.get("events", [])
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for e in events:
        eid = e.get("event_id")
        if eid is not None:
            if eid in seen:
                continue
            seen.add(str(eid))
        out.append(dict(e))
    out.sort(key=lambda e: (e.get("sequence", 0), e.get("sim_tick", 0)))
    return out


def split_tick(sim_tick: int, max_ticks: int | None) -> tuple[int, int]:
    """Global index -> (episode, tick within episode)."""
    if not max_ticks or max_ticks <= 0:
        return 0, int(sim_tick)
    return int(sim_tick) // max_ticks, int(sim_tick) % max_ticks


def episode_kind(meta: Mapping[str, Any], episode: int) -> str | None:
    eps = meta.get("episodes") or []
    if 0 <= episode < len(eps):
        return str(eps[episode].get("kind"))
    return None


def _nodes(events: Sequence[Event]) -> list[str]:
    found: set[str] = set()
    for e in events:
        if e.get("source_node_id"):
            found.add(str(e["source_node_id"]))
        if e.get("kind") == "world_snapshot":
            found.update(e.get("poses", {}))
    return sorted(found)


def _mean(xs: Sequence[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _link_key(a: str, b: str) -> frozenset[str]:
    return frozenset((a, b))


# ----------------------------------------------------------------------------------------------
# fault phases and topology
# ----------------------------------------------------------------------------------------------
def fault_phase_intervals(
    events: Sequence[Event], max_ticks: int | None = None
) -> list[dict[str, Any]]:
    """Intervals ``{phase, start, end}`` (sim ticks, per episode) from ``fault_phase`` metric samples."""
    samples = sorted(
        (
            e
            for e in events
            if e.get("kind") == "metric_sample" and e.get("metric") == "fault_phase"
        ),
        key=lambda e: e["sim_tick"],
    )
    last_tick = max((e.get("sim_tick", 0) for e in events), default=0)
    out: list[dict[str, Any]] = []
    for s in samples:
        phase = FAULT_PHASES.get(int(s["value"]), f"state-{int(s['value'])}")
        if out and out[-1]["phase"] == phase:
            continue
        if out:
            out[-1]["end"] = s["sim_tick"]
        out.append({"phase": phase, "start": s["sim_tick"], "end": last_tick})
    return out


def _phase_at(intervals: Sequence[Mapping[str, Any]], sim_tick: int) -> str:
    phase = "normal"
    for iv in intervals:
        if iv["start"] <= sim_tick:
            phase = iv["phase"]
    return phase


def topology_snapshots(
    events: Sequence[Event], meta: Mapping[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Links/phase at several ticks: every change of the link set, topped up with evenly spaced ticks."""
    meta = meta or {}
    mt = meta.get("max_ticks")
    snaps = [e for e in events if e.get("kind") == "world_snapshot"]
    if not snaps:
        return []
    intervals = fault_phase_intervals(events, mt)
    chosen: dict[int, Event] = {}
    prev: frozenset[frozenset[str]] | None = None
    for i, s in enumerate(snaps):
        links = frozenset(_link_key(a, b) for a, b in s["topology"]["links"])
        if i == 0 or i == len(snaps) - 1 or links != prev:
            chosen[i] = s
        prev = links
    budget = MAX_TOPOLOGY_SNAPSHOTS - len(chosen)
    if budget > 0 and len(snaps) > len(chosen):
        step = max(1, len(snaps) // budget)
        for i in range(0, len(snaps), step):
            if len(chosen) >= MAX_TOPOLOGY_SNAPSHOTS:
                break
            chosen.setdefault(i, snaps[i])
    if (
        len(chosen) > MAX_TOPOLOGY_SNAPSHOTS
    ):  # many link changes: keep first, last and an even sample
        keys = sorted(chosen)
        keep = {
            keys[round(j * (len(keys) - 1) / (MAX_TOPOLOGY_SNAPSHOTS - 1))]
            for j in range(MAX_TOPOLOGY_SNAPSHOTS)
        }
        chosen = {k: chosen[k] for k in keep}
    out = []
    for i in sorted(chosen):
        s = chosen[i]
        ep, tick = split_tick(s["sim_tick"], mt)
        out.append(
            {
                "sim_tick": s["sim_tick"],
                "episode": ep,
                "tick": tick,
                "phase": _phase_at(intervals, s["sim_tick"]),
                "links": [list(p) for p in s["topology"]["links"]],
                "poses": {
                    k: {"x": v.get("x"), "y": v.get("y")} for k, v in s.get("poses", {}).items()
                },
                "coverage": s.get("coverage"),
                "run_status": s.get("run_status"),
            }
        )
    return out


# ----------------------------------------------------------------------------------------------
# tables
# ----------------------------------------------------------------------------------------------
CURVE_COLUMNS = [
    "node_id", "sim_tick", "episode", "tick", "episode_kind", "loss", "update_count", "policy_version",
    "coverage", *[f"return_{p}" for p in RETURN_PHASES],
]  # fmt: skip


def curve_rows(
    events: Sequence[Event], meta: Mapping[str, Any] | None = None
) -> list[dict[str, Any]]:
    """One row per (node, sim_tick) that has a learning event or an episode return.

    ``coverage`` is the world coverage of the latest snapshot at or before that tick (it is a world value, not
    a per-node one). ``return_<phase>`` is the node's ``episode_return`` sample with that phase.
    """
    meta = meta or {}
    mt = meta.get("max_ticks")
    cov_points = sorted(
        (e["sim_tick"], e["coverage"]) for e in events if e.get("kind") == "world_snapshot"
    )

    def coverage_at(t: int) -> float | None:
        val = None
        for ct, cv in cov_points:
            if ct > t:
                break
            val = cv
        return val

    rows: dict[tuple[str, int], dict[str, Any]] = {}

    def row(node: str, t: int) -> dict[str, Any]:
        r = rows.get((node, t))
        if r is None:
            ep, tick = split_tick(t, mt)
            r = {c: "" for c in CURVE_COLUMNS}
            r.update(
                node_id=node,
                sim_tick=t,
                episode=ep,
                tick=tick,
                episode_kind=episode_kind(meta, ep) or "",
            )
            cov = coverage_at(t)
            r["coverage"] = "" if cov is None else cov
            rows[(node, t)] = r
        return r

    for e in events:
        node = e.get("source_node_id")
        if not node:
            continue
        if e["kind"] == "learning_event":
            r = row(node, e["sim_tick"])
            r["loss"] = "" if e.get("loss") is None else e["loss"]
            r["update_count"] = e["update_count"]
            r["policy_version"] = e["new_version"]
        elif e["kind"] == "metric_sample" and e.get("metric") == "episode_return":
            row(node, e["sim_tick"])[f"return_{e['phase']}"] = e["value"]
    return [rows[k] for k in sorted(rows, key=lambda k: (k[0], k[1]))]


DECISION_COLUMNS = [
    "sim_tick", "episode", "tick", "event", "node_id", "peer", "model_version", "transfer", "reason",
    "candidate_score", "bytes", "wall_seconds", "previous_version", "new_version", "event_id",
]  # fmt: skip


def peer_decision_rows(
    events: Sequence[Event], meta: Mapping[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Offers (``event=offer``, node = sender) and accept/reject decisions (``event=decision``, node = receiver)."""
    mt = (meta or {}).get("max_ticks")
    rows = []
    for e in events:
        k = e.get("kind")
        if k not in ("peer_envelope", "learning_event"):
            continue
        ep, tick = split_tick(e["sim_tick"], mt)
        r: dict[str, Any] = {c: "" for c in DECISION_COLUMNS}
        r.update(sim_tick=e["sim_tick"], episode=ep, tick=tick, event_id=e.get("event_id", ""))
        if k == "peer_envelope":
            r.update(
                event="offer" if e.get("type") == "model_offer" else str(e.get("type")),
                node_id=e.get("sender", ""),
                peer=e.get("recipient", ""),
                model_version=e.get("model_version", ""),
                bytes=e.get("payload_length", ""),
            )
        else:
            if e.get("transfer") == "none":
                continue  # a local update, not a peer decision
            r.update(
                event="decision",
                node_id=e.get("source_node_id") or "",
                transfer=e["transfer"],
                reason=e.get("reason") or "",
                candidate_score="" if e.get("candidate_score") is None else e["candidate_score"],
                bytes=e.get("bytes", ""),
                wall_seconds=e.get("wall_seconds", ""),
                previous_version=e.get("previous_version", ""),
                new_version=e.get("new_version", ""),
            )
        rows.append(r)
    return rows


def to_csv(columns: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(columns), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


# ----------------------------------------------------------------------------------------------
# timeline and summary
# ----------------------------------------------------------------------------------------------
def node_timeline(events: Sequence[Event], meta: Mapping[str, Any] | None = None) -> dict[str, Any]:
    meta = meta or {}
    mt = meta.get("max_ticks")
    nodes: dict[str, dict[str, Any]] = {
        n: {"first_sim_tick": None, "last_sim_tick": None, "events": [], "counts": Counter()}
        for n in _nodes(events)
    }

    def add(node: str | None, t: int, typ: str, **detail: Any) -> None:
        if not node or node not in nodes:
            return
        n = nodes[node]
        n["first_sim_tick"] = t if n["first_sim_tick"] is None else min(n["first_sim_tick"], t)
        n["last_sim_tick"] = t if n["last_sim_tick"] is None else max(n["last_sim_tick"], t)
        n["counts"][typ] += 1
        ep, tick = split_tick(t, mt)
        n["events"].append({"sim_tick": t, "episode": ep, "tick": tick, "type": typ, **detail})

    for e in events:
        node, t, k = e.get("source_node_id"), e["sim_tick"], e.get("kind")
        if k == "learning_event":
            if e["transfer"] == "accepted":
                add(node, t, "peer_accepted", new_version=e["new_version"], reason=e.get("reason"))
            elif e["transfer"] == "rejected":
                add(node, t, "peer_rejected", reason=e.get("reason"))
            elif e["new_version"] != e["previous_version"]:
                add(node, t, "policy_version", new_version=e["new_version"])
        elif k == "peer_envelope" and e.get("type") == "model_offer":
            add(node, t, "offer_sent", to=e.get("recipient"), model_version=e.get("model_version"))
        elif k == "metric_sample" and e.get("metric") in (
            "node_unavailable",
            "node_killed",
            "deadline_missed",
        ):
            if node and float(e["value"]) > 0:
                add(node, t, str(e["metric"]), value=e["value"])
    for n in nodes.values():
        n["events"].sort(key=lambda x: x["sim_tick"])
        n["counts"] = dict(n["counts"])
    return {"fault_phases": fault_phase_intervals(events, mt), "nodes": nodes}


def _offers_over_cut_links(events: Sequence[Event]) -> dict[str, int]:
    """Offers whose (sender, recipient) pair was absent from the latest snapshot's link set."""
    snaps = sorted(
        ((e["sim_tick"], e.get("sequence", 0), frozenset(_link_key(a, b) for a, b in e["topology"]["links"]))
         for e in events if e.get("kind") == "world_snapshot"),
        key=lambda x: (x[0], x[1]),
    )  # fmt: skip
    total = over = 0
    for e in events:
        if e.get("kind") != "peer_envelope" or e.get("type") != "model_offer":
            continue
        links = None
        for st, _, lk in snaps:
            if st > e["sim_tick"]:
                break
            links = lk
        if links is None:
            continue
        total += 1
        if _link_key(e["sender"], e["recipient"]) not in links:
            over += 1
    return {"offers_checked": total, "offers_over_cut_links": over}


def summarize(events: Sequence[Event], meta: Mapping[str, Any] | None = None) -> dict[str, Any]:
    meta = dict(meta or {})
    mt = meta.get("max_ticks")
    nodes = _nodes(events)
    per_node: dict[str, dict[str, Any]] = {n: {} for n in nodes}
    accepted: Counter[str] = Counter()
    rejected: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    bytes_acc = bytes_rej = 0
    offers = 0
    offer_bytes = 0
    returns: dict[str, dict[str, list[float]]] = {n: defaultdict(list) for n in nodes}
    by_episode: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    last_loss: dict[str, float] = {}
    deadline_missed: Counter[str] = Counter()
    # Nodes report cumulative offer counters as metrics (peer_offers_sent / peer_offers_cut); keep the last.
    node_counters: dict[str, dict[str, float]] = defaultdict(dict)
    for e in events:
        node, k = e.get("source_node_id"), e.get("kind")
        if k == "learning_event" and node:
            pn = per_node.setdefault(node, {})
            pn["update_count"] = max(pn.get("update_count", 0), e["update_count"])
            pn["policy_version"] = e["new_version"]
            if e.get("loss") is not None:
                last_loss[node] = e["loss"]
            if e["transfer"] == "accepted":
                accepted[node] += 1
                bytes_acc += e.get("bytes", 0)
            elif e["transfer"] == "rejected":
                rejected[node] += 1
                bytes_rej += e.get("bytes", 0)
                reasons[str(e.get("reason"))] += 1
        elif k == "peer_envelope" and e.get("type") == "model_offer":
            offers += 1
            offer_bytes += e.get("payload_length", 0)
        elif k == "metric_sample":
            if e["metric"] == "episode_return" and node:
                returns.setdefault(node, defaultdict(list))[e["phase"]].append(e["value"])
                ep, _ = split_tick(e["sim_tick"], mt)
                by_episode[ep][e["phase"]].append(e["value"])
            elif e["metric"] == "deadline_missed" and node:
                deadline_missed[node] += int(e["value"])
            elif e["metric"] in ("peer_offers_sent", "peer_offers_cut") and node:
                node_counters[node][e["metric"]] = e["value"]
    covs = [e["coverage"] for e in events if e.get("kind") == "world_snapshot"]
    for n in nodes:
        pn = per_node[n]
        pn["final_loss"] = last_loss.get(n)
        pn["peer_accepted"], pn["peer_rejected"] = accepted[n], rejected[n]
        pn["deadline_missed"] = deadline_missed[n]
        pn["mean_return"] = {p: _mean(v) for p, v in returns.get(n, {}).items()}
        pn["last_return"] = {p: v[-1] for p, v in returns.get(n, {}).items() if v}
    ticks = [e["sim_tick"] for e in events]
    run_config = meta.get("run_config") or {}
    return {
        "run_id": meta.get("run_id") or (events[0].get("run_id") if events else None),
        "plan": meta.get("plan"),
        "modes": meta.get("modes")
        or {"learner": run_config.get("learner"), "run_mode": run_config.get("mode")},
        "commit": meta.get("commit"),
        "image_digests": meta.get("image_digests", {}),
        "seeds": meta.get("seeds") or run_config.get("seeds"),
        "wall_seconds": meta.get("wall_seconds"),
        "events": len(events),
        "sim_tick_range": [min(ticks), max(ticks)] if ticks else None,
        "nodes": per_node,
        "final_coverage": covs[-1] if covs else None,
        "max_coverage": max(covs) if covs else None,
        "peer": {
            "accepted": sum(accepted.values()),
            "rejected": sum(rejected.values()),
            "rejection_reasons": dict(reasons),
            "offers": offers,
            "bytes_accepted": bytes_acc,
            "bytes_rejected": bytes_rej,
            "offer_payload_bytes": offer_bytes,
            "offers_sent_by_nodes": int(
                sum(c.get("peer_offers_sent", 0) for c in node_counters.values())
            ),
            "offers_blocked_by_cut": int(
                sum(c.get("peer_offers_cut", 0) for c in node_counters.values())
            ),
            **_offers_over_cut_links(events),
        },
        "episode_returns": [
            {
                "episode": ep,
                "kind": episode_kind(meta, ep),
                **{f"mean_{p}": _mean(v) for p, v in sorted(by_ph.items())},
            }
            for ep, by_ph in sorted(by_episode.items())
        ],
        "fault_phases": fault_phase_intervals(events, mt),
    }


# ----------------------------------------------------------------------------------------------
# SVG (stdlib string building)
# ----------------------------------------------------------------------------------------------
W, H = 880, 340
ML, MR, MT, MB = 64, 150, 36, 44
BAND = {"partition": "#D55E00", "recovery": "#E69F00"}


def _nice(lo: float, hi: float) -> tuple[float, float]:
    if hi <= lo:
        hi = lo + 1.0
    return lo, hi


def _fmt(v: float) -> str:
    return f"{v:.3g}"


def _panel(
    x0: float, y0: float, w: float, h: float, title: str, ylabel: str,
    series: Mapping[str, Sequence[tuple[float, float]]],
    bands: Sequence[Mapping[str, Any]], xmax: float, styles: Mapping[str, tuple[str, str, str]],
) -> str:  # fmt: skip
    """One line-chart panel. ``styles[name] = (colour, dasharray, marker)``."""
    pts = [p for s in series.values() for p in s]
    out = [f'<text x="{x0}" y="{y0 - 14}" class="t">{escape(title)}</text>']
    out.append(f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" class="plot"/>')
    if not pts:
        out.append(
            f'<text x="{x0 + w / 2}" y="{y0 + h / 2}" text-anchor="middle" class="a">no data</text>'
        )
        return "\n".join(out)
    ymin, ymax = _nice(min(p[1] for p in pts), max(p[1] for p in pts))
    pad = (ymax - ymin) * 0.08
    ymin, ymax = ymin - pad, ymax + pad
    xmax = max(xmax, 1)

    def sx(x: float) -> float:
        return x0 + w * x / xmax

    def sy(y: float) -> float:
        return y0 + h - h * (y - ymin) / (ymax - ymin)

    for b in bands:
        if b["phase"] in BAND and b["end"] > b["start"]:
            out.append(
                f'<rect x="{sx(b["start"]):.1f}" y="{y0}" width="{sx(b["end"]) - sx(b["start"]):.1f}" '
                f'height="{h}" fill="{BAND[b["phase"]]}" opacity="{0.16 if b["phase"] == "partition" else 0.10}"/>'
            )
    for i in range(5):
        yv = ymin + (ymax - ymin) * i / 4
        out.append(f'<line x1="{x0}" x2="{x0 + w}" y1="{sy(yv):.1f}" y2="{sy(yv):.1f}" class="g"/>')
        out.append(
            f'<text x="{x0 - 6}" y="{sy(yv) + 4:.1f}" text-anchor="end" class="a">{_fmt(yv)}</text>'
        )
    for i in range(6):
        xv = xmax * i / 5
        out.append(
            f'<text x="{sx(xv):.1f}" y="{y0 + h + 16}" text-anchor="middle" class="a">{_fmt(xv)}</text>'
        )
    out.append(
        f'<text x="{x0 + w / 2}" y="{y0 + h + 34}" text-anchor="middle" class="a">sim tick</text>'
    )
    out.append(
        f'<text transform="translate({x0 - 46},{y0 + h / 2}) rotate(-90)" text-anchor="middle" class="a">{escape(ylabel)}</text>'
    )
    for j, (name, s) in enumerate(series.items()):
        colour, dash, marker = styles[name]
        if not s:
            continue
        s = sorted(s)
        path = " ".join(
            f"{'M' if i == 0 else 'L'}{sx(x):.1f},{sy(y):.1f}" for i, (x, y) in enumerate(s)
        )
        da = f' stroke-dasharray="{dash}"' if dash else ""
        out.append(f'<path d="{path}" fill="none" stroke="{colour}" stroke-width="1.6"{da}/>')
        if len(s) <= 60:
            for x, y in s:
                out.append(_marker(marker, sx(x), sy(y), colour))
        ly = y0 + 14 + 16 * j
        out.append(
            f'<line x1="{x0 + w + 12}" x2="{x0 + w + 36}" y1="{ly}" y2="{ly}" stroke="{colour}" stroke-width="2"{da}/>'
        )
        out.append(f'<text x="{x0 + w + 42}" y="{ly + 4}" class="a">{escape(name)}</text>')
    return "\n".join(out)


def _marker(kind: str, x: float, y: float, colour: str) -> str:
    if kind == "square":
        return f'<rect x="{x - 3:.1f}" y="{y - 3:.1f}" width="6" height="6" fill="{colour}"/>'
    if kind == "diamond":
        return f'<path d="M{x:.1f},{y - 4:.1f} L{x + 4:.1f},{y:.1f} L{x:.1f},{y + 4:.1f} L{x - 4:.1f},{y:.1f}Z" fill="{colour}"/>'
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="{colour}"/>'


def _svg(width: int, height: int, title: str, body: str, desc: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" '
        f'height="{height}" role="img" aria-label="{escape(title)}" font-family="system-ui, sans-serif">\n'
        f"<title>{escape(title)}</title><desc>{escape(desc)}</desc>\n"
        "<style>.t{font-size:13px;font-weight:600;fill:#222}.a{font-size:11px;fill:#444}"
        ".g{stroke:#ddd;stroke-width:1}.plot{fill:#fff;stroke:#bbb}</style>\n"
        f'<rect width="{width}" height="{height}" fill="#fff"/>\n{body}\n</svg>\n'
    )


def _node_styles(nodes: Sequence[str]) -> dict[str, tuple[str, str, str]]:
    marks = ("circle", "square", "diamond")
    return {n: (PALETTE[i % len(PALETTE)], "", marks[i % len(marks)]) for i, n in enumerate(nodes)}


def learning_curve_svg(events: Sequence[Event], meta: Mapping[str, Any] | None = None) -> str:
    nodes = _nodes(events)
    series: dict[str, list[tuple[float, float]]] = {n: [] for n in nodes}
    for e in events:
        if (
            e.get("kind") == "learning_event"
            and e.get("loss") is not None
            and e.get("source_node_id")
        ):
            series.setdefault(e["source_node_id"], []).append((e["sim_tick"], e["loss"]))
    xmax = max((e["sim_tick"] for e in events), default=1)
    body = _panel(ML, MT, W - ML - MR, H - MT - MB, "Learning curve: loss per node (shaded = partition)", "loss",
                  series, fault_phase_intervals(events, (meta or {}).get("max_ticks")), xmax,
                  _node_styles(list(series)))  # fmt: skip
    return _svg(W, H, "Learning curve", body, "Training loss of each node over simulation ticks.")


def coverage_return_svg(events: Sequence[Event], meta: Mapping[str, Any] | None = None) -> str:
    meta = meta or {}
    nodes = _nodes(events)
    xmax = max((e["sim_tick"] for e in events), default=1)
    bands = fault_phase_intervals(events, meta.get("max_ticks"))
    cov = [(e["sim_tick"], e["coverage"]) for e in events if e.get("kind") == "world_snapshot"]
    ph = 200
    top = _panel(ML, MT, W - ML - MR, ph, "World coverage", "coverage", {"coverage": cov}, bands, xmax,
                 {"coverage": (PALETTE[2], "", "circle")})  # fmt: skip
    series: dict[str, list[tuple[float, float]]] = {}
    styles: dict[str, tuple[str, str, str]] = {}
    base = _node_styles(nodes)
    for e in events:
        if (
            e.get("kind") == "metric_sample"
            and e["metric"] == "episode_return"
            and e.get("source_node_id")
        ):
            n, p = e["source_node_id"], e["phase"]
            key = f"{n} {p}"
            series.setdefault(key, []).append((e["sim_tick"], e["value"]))
            colour, _, marker = base.get(n, (PALETTE[0], "", "circle"))
            styles[key] = (colour, "5,3" if p != "train" else "", marker)
    bottom = _panel(ML, MT + ph + 70, W - ML - MR, ph, "Episode return: train (solid) vs eval (dashed)", "return",
                    series, bands, xmax, styles)  # fmt: skip
    h = MT + 2 * ph + 70 + MB
    return _svg(
        W,
        h,
        "Coverage and return",
        top + "\n" + bottom,
        "World coverage and per-node episode return, train versus eval.",
    )


def partition_timeline_svg(events: Sequence[Event], meta: Mapping[str, Any] | None = None) -> str:
    meta = meta or {}
    nodes = _nodes(events)
    xmax = max((e["sim_tick"] for e in events), default=1) or 1
    row_h = 34
    h = MT + max(1, len(nodes)) * row_h + MB + 30
    x0, w = ML, W - ML - MR

    def sx(t: float) -> float:
        return x0 + w * t / xmax

    body = [
        f'<text x="{x0}" y="{MT - 14}" class="t">Partition timeline (shaded = partition / recovery)</text>'
    ]
    ph_h = max(1, len(nodes)) * row_h
    body.append(f'<rect x="{x0}" y="{MT}" width="{w}" height="{ph_h}" class="plot"/>')
    for iv in fault_phase_intervals(events, meta.get("max_ticks")):
        if iv["phase"] in BAND and iv["end"] > iv["start"]:
            body.append(
                f'<rect x="{sx(iv["start"]):.1f}" y="{MT}" width="{sx(iv["end"]) - sx(iv["start"]):.1f}" height="{ph_h}" '
                f'fill="{BAND[iv["phase"]]}" opacity="{0.16 if iv["phase"] == "partition" else 0.10}"/>'
            )
    for i, n in enumerate(nodes):
        cy = MT + i * row_h + row_h / 2
        body.append(f'<line x1="{x0}" x2="{x0 + w}" y1="{cy}" y2="{cy}" class="g"/>')
        body.append(
            f'<text x="{x0 - 6}" y="{cy + 4}" text-anchor="end" class="a">{escape(n)}</text>'
        )
    idx = {n: i for i, n in enumerate(nodes)}
    for e in events:
        n = e.get("source_node_id")
        if n not in idx:
            continue
        cy = MT + idx[n] * row_h + row_h / 2
        x = sx(e["sim_tick"])
        if e.get("kind") == "peer_envelope" and e.get("type") == "model_offer":
            body.append(
                f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{cy - 12}" y2="{cy - 5}" stroke="#666" stroke-width="1.5"/>'
            )
        elif e.get("kind") == "learning_event" and e["transfer"] == "accepted":
            body.append(_marker("circle", x, cy, PALETTE[2]))
        elif e.get("kind") == "learning_event" and e["transfer"] == "rejected":
            body.append(
                f'<path d="M{x - 3.5:.1f},{cy - 3.5} L{x + 3.5:.1f},{cy + 3.5} M{x - 3.5:.1f},{cy + 3.5} L{x + 3.5:.1f},{cy - 3.5}" stroke="{PALETTE[1]}" stroke-width="2"/>'
            )
        elif (
            e.get("kind") == "metric_sample"
            and e["metric"] in ("node_unavailable", "node_killed")
            and float(e["value"]) > 0
        ):
            body.append(_marker("diamond", x, cy + 10, PALETTE[3]))
    for i in range(6):
        xv = xmax * i / 5
        body.append(
            f'<text x="{sx(xv):.1f}" y="{MT + ph_h + 16}" text-anchor="middle" class="a">{_fmt(xv)}</text>'
        )
    ly = MT + ph_h + 34
    legend = [
        ("offer sent", "tick"),
        ("accepted", "circle"),
        ("rejected", "cross"),
        ("unavailable/killed", "diamond"),
    ]
    lx = x0
    for label, shape in legend:
        if shape == "tick":
            body.append(
                f'<line x1="{lx}" x2="{lx}" y1="{ly - 6}" y2="{ly + 2}" stroke="#666" stroke-width="1.5"/>'
            )
        elif shape == "cross":
            body.append(
                f'<path d="M{lx - 3.5},{ly - 3.5} L{lx + 3.5},{ly + 3.5} M{lx - 3.5},{ly + 3.5} L{lx + 3.5},{ly - 3.5}" stroke="{PALETTE[1]}" stroke-width="2"/>'
            )
        else:
            body.append(_marker(shape, lx, ly - 2, PALETTE[2] if shape == "circle" else PALETTE[3]))
        body.append(f'<text x="{lx + 10}" y="{ly + 2}" class="a">{label}</text>')
        lx += 150
    return _svg(
        W,
        h,
        "Partition timeline",
        "\n".join(body),
        "Per-node peer offers and accept/reject decisions against the partition window.",
    )


# ----------------------------------------------------------------------------------------------
# entry points
# ----------------------------------------------------------------------------------------------
def build_artifacts(
    events: Iterable[Event] | Mapping[str, Any], meta: Mapping[str, Any] | None = None
) -> dict[str, str]:
    """filename -> text content for every demo artifact."""
    evs = normalize(events)
    meta = dict(meta or {})
    dump = lambda o: json.dumps(o, indent=2, sort_keys=True) + "\n"  # noqa: E731
    return {
        "summary.json": dump(summarize(evs, meta)),
        "curves.csv": to_csv(CURVE_COLUMNS, curve_rows(evs, meta)),
        "peer_decisions.csv": to_csv(DECISION_COLUMNS, peer_decision_rows(evs, meta)),
        "topology_snapshots.json": dump(topology_snapshots(evs, meta)),
        "node_timeline.json": dump(node_timeline(evs, meta)),
        "learning_curve.svg": learning_curve_svg(evs, meta),
        "coverage_return.svg": coverage_return_svg(evs, meta),
        "partition_timeline.svg": partition_timeline_svg(evs, meta),
    }


def write_artifacts(
    events: Iterable[Event] | Mapping[str, Any],
    out_dir: Path,
    meta: Mapping[str, Any] | None = None,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, text in build_artifacts(events, meta).items():
        p = out_dir / name
        p.write_text(text, encoding="utf-8")
        paths.append(p)
    return paths
