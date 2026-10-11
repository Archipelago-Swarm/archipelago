import { useEffect, useMemo, useRef, useState } from "react";
import type { WorldSnapshot } from "@archipelago/contracts";
import { FlightMap } from "./FlightMap";
import {
  BASE, SERVER_CMD, applyMessage, decisionText, demoFeed, disruptionLabel, emptyBuffer, explainLink, feedAt, feedText, frameAt, hms, km, loadOfflineReplay, pct,
  type Buffer, type MapSummary, type Meta, type RFLink, type UavState, type View,
} from "./missionReplay";

type Origin = "loading" | "live" | "offline" | "error";
const RATES = [15, 60, 120, 300];
const MARKERS = new Set(["POI_VERIFIED", "NETWORK_PARTITIONED", "SKILL_LEARNED", "DISRUPTION_STARTED", "UAV_FAILED", "MISSION_SUCCESS", "MISSION_FAILED"]);

/** Live SSE buffer; falls back to the committed replay (seed 1002, 6 UAVs only), else an error panel. Never synthetic data. */
function useMissionBuffer(seed: number, uavs: number) {
  const [buf, setBuf] = useState<Buffer>(emptyBuffer), [origin, setOrigin] = useState<Origin>("loading"), [err, setErr] = useState("");
  useEffect(() => {
    let closed = false;
    setBuf(emptyBuffer()); setOrigin("loading"); setErr("");
    const es = new EventSource(`${BASE}/api/mission/stream?seed=${seed}&uavs=${uavs}&tps=30`);
    const on = (name: "meta" | "tick" | "end") => es.addEventListener(name, (e) => {
      setOrigin("live"); setBuf((b) => applyMessage(b, name, JSON.parse((e as MessageEvent).data)));
      if (name === "end") { closed = true; es.close(); } // else EventSource would restart the mission
    });
    on("meta"); on("tick"); on("end");
    es.onerror = () => {
      es.close();
      if (closed) return;
      (uavs === 6 ? loadOfflineReplay(seed) : Promise.reject(new Error("offline replays exist for 6 UAVs only")))
        .then((b) => { setBuf(b); setOrigin("offline"); })
        .catch((e) => { setErr(String(e.message ?? e)); setOrigin("error"); });
    };
    return () => { closed = true; es.close(); };
  }, [seed, uavs]);
  return { buf, origin, err };
}

/** The mission frame as a contracts snapshot, so the mission viewer uses the same 3D terrain renderer as the fixture. */
/** Fog of war: terrain cells within any live UAV's sensor radius in frames 0..i. Memoised so playback only scans new frames. */
function useObserved(buf: Buffer, meta: Meta | null, t: number) {
  const memo = useRef<{ key: unknown; i: number; seen: Uint8Array; str: string }>({ key: null, i: -1, seen: new Uint8Array(0), str: "" });
  const ter = meta?.world.terrain;
  if (!ter || !meta || !buf.frames.length) return "";
  const i = Math.min(buf.frames.length - 1, Math.floor(t / meta.dt)), m = memo.current, cell = meta.world.cellMeters;
  if (m.key !== meta || i < m.i) Object.assign(m, { key: meta, i: -1, seen: new Uint8Array(ter.size * ter.height), str: "" });
  if (i === m.i) return m.str;
  for (let f = m.i + 1; f <= i; f++) for (const u of buf.frames[f].uavs) {
    if (u.status === "FAILED") continue;
    const r = u.sensorRadius, x0 = Math.max(0, Math.floor((u.position.x - r) / cell)), x1 = Math.min(ter.size - 1, Math.floor((u.position.x + r) / cell));
    const y0 = Math.max(0, Math.floor((u.position.y - r) / cell)), y1 = Math.min(ter.height - 1, Math.floor((u.position.y + r) / cell));
    for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) if (((x + 0.5) * cell - u.position.x) ** 2 + ((y + 0.5) * cell - u.position.y) ** 2 <= r * r) m.seen[y * ter.size + x] = 1;
  }
  m.i = i; m.str = Array.from(m.seen, (b) => (b ? "1" : "0")).join("");
  return m.str;
}

/** Active disruption zones (area denial) as the contract's obstacle polygons, which FlightMap already draws. */
const hazards = (v: View) => v.floor.disruptions.filter((d) => d.active && d.position && d.radius).map((d) => ({
  id: d.id, points: Array.from({ length: 36 }, (_, i) => [d.position!.x + d.radius! * Math.cos((i * Math.PI) / 18), d.position!.y + d.radius! * Math.sin((i * Math.PI) / 18)]),
}));

function snapshotOf(meta: Meta, v: View, seed: number, observed: string): WorldSnapshot {
  const poses = Object.fromEntries(v.uavs.map((u) => [u.id, { x: u.position.x, y: u.position.y, z: 0, heading_rad: u.heading, speed_mps: u.speed }]));
  return {
    schema_version: "0.1.0", event_id: `m-${seed}`, run_id: `mission-${seed}`, source_node_id: null, sim_tick: Math.round(v.t * 100), emitted_at_utc: "1970-01-01T00:00:00Z", sequence: 0,
    kind: "world_snapshot", run_status: "running", poses, obstacles: [], coverage: v.floor.mission.fleetKnowledgeCoverage,
    topology: { links: v.floor.links.filter((l) => l.connected).map((l) => [l.sourceNodeId, l.targetNodeId]) },
    world: { width_m: meta.world.width, height_m: meta.world.height, cell_m: meta.world.cellMeters, sensor_radius_m: meta.uavSpec.sensor.radiusMeters, shapes: hazards(v), targets_found: v.floor.pois.filter((p) => p.state !== "UNKNOWN").map((p) => ({ x: p.position.x, y: p.position.y, radius: 0 })), terrain: { ...meta.world.terrain, observed } },
  } as unknown as WorldSnapshot;
}

function Spec({ meta }: { meta: Meta }) {
  const u = meta.uavSpec, r = meta.rfModel, m = meta.missionRules, n = u.autonomy.split(": ")[1]?.split(" > ") ?? [];
  const rows: [string, string][] = [
    ["Platform", `${u.count} x ${u.platformClass}`],
    ["Cruise speed", `${u.cruiseSpeedMps} m/s (${u.cruiseSpeedKmh} km/h); in nav zone ${(u.cruiseSpeedMps * u.nominalSpeedInNavDegradationFactor).toFixed(0)} m/s`],
    ["Altitude", `cruise ${u.cruiseAltitudeAglMeters} m AGL, max ${u.maxAltitudeAglMeters} m; climb ${u.climbRateMps} m/s`],
    ["Sensor", `${u.sensor.type}, radius ${km(u.sensor.radiusMeters)} km (${km(u.sensor.radiusMeters * u.sensor.radiusInNavDegradationFactor)} km degraded)`],
    ["Detection", u.sensor.detection],
    ["Search cell", `${km(u.sensor.searchCellMeters[0])} x ${km(u.sensor.searchCellMeters[1])} km (grid ${meta.searchGrid.nx} x ${meta.searchGrid.ny})`],
    ["Radio", `nominal ${km(u.comms.nominalRangeMeters)} km, extended ${km(u.comms.extendedRangeMeters)} km; horizon ${km(u.comms.horizonAtCruiseMeters)} km at cruise, ${km(u.comms.horizonAtMaxAltitudeMeters)} km at max altitude`],
    ["RF states", `${Object.entries(r.stateThresholds).map(([k, v]) => `${k} >= ${v}`).join(", ")}; connected at >= ${r.connectedThreshold}`],
    ["RF update", `every ${r.updateIntervalSeconds} s; listed to ${km(r.reportRangeMeters)} km; routine max ${km(r.maxRoutineRangeMeters)} km`],
    ["Autonomy", u.autonomy.split(": ")[0] + (n.length ? ` (priority: ${n.join(" > ")})` : "")],
    ["Skills", u.learnedSkills.join(", ")],
    ["Rules", `limit ${hms(m.timeLimitSeconds)}; ${m.totalPois} POIs, ${m.requiredPois} required; verify at ${pct(m.verifyConfidence)}; knowledge threshold ${pct(m.knowledgeThreshold)}; skill transfer ${m.skillTransferSecondsAtFullBandwidth} s at full bandwidth; adopt if utility >= ${m.minAdoptUtility}; tick ${m.tickSeconds} s`],
    ["POI types", m.poiTypes.join(", ")],
    ["Disruptions", m.disruptionTypes.map(disruptionLabel).join(", ")],
  ];
  return <dl className="m-spec">{rows.map(([k, v]) => <div key={k} style={{ display: "contents" }}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>;
}

function Bars({ c }: { c: MapSummary }) {
  const rows: [string, number, number][] = [["Redundancy ratio", c.on.stats.redundancyRatio, c.off.stats.redundancyRatio], ["POIs verified", c.on.mission.verifiedPois / c.on.mission.totalPois, c.off.mission.verifiedPois / c.off.mission.totalPois]];
  return (
    <div>
      <p>Skills on: <b>{c.on.mission.status}</b> at {hms(c.on.mission.elapsedTime)} · skills off: <b>{c.off.mission.status}</b> at {hms(c.off.mission.elapsedTime)}</p>
      {rows.map(([k, a, b]) => (
        <div key={k} className="m-bars"><span>{k}</span>
          <div><i style={{ width: pct(a) }} className="on" />{pct(a)} on</div>
          <div><i style={{ width: pct(b) }} className="off" />{pct(b)} off</div>
        </div>
      ))}
    </div>
  );
}

function NodeInspector({ u, v, buf, onSpec }: { u: UavState; v: View; buf: Buffer; onSpec(): void }) {
  const my = v.floor.links.filter((l) => l.sourceNodeId === u.id || l.targetNodeId === u.id), conn = my.filter((l) => l.connected);
  const other = (l: RFLink) => (l.sourceNodeId === u.id ? l.targetNodeId : l.sourceNodeId);
  const best = conn.reduce<RFLink | null>((a, l) => (!a || l.rfQuality > a.rfQuality ? l : a), null);
  const worst = conn.reduce<RFLink | null>((a, l) => (!a || l.rfQuality < a.rfQuality ? l : a), null);
  const nearest = my.filter((l) => !l.connected).sort((a, b) => a.distanceKm - b.distanceKm)[0];
  const spec = buf.meta!.uavSpec, eff = u.sensorState === "DEGRADED" ? spec.sensor.radiusMeters * spec.sensor.radiusInNavDegradationFactor : u.sensorState === "NOMINAL" ? spec.sensor.radiusMeters : null;
  const decs = feedAt(buf.decisions, v.t).filter((d) => d.nodeId === u.id), last = decs[decs.length - 1];
  const lk = (l: RFLink | null) => (l ? `${other(l)} ${l.state} q=${l.rfQuality.toFixed(3)} ${l.distanceKm.toFixed(1)} km bw ${l.bandwidthFactor.toFixed(2)}` : "-");
  return (
    <section aria-label="Node inspector"><h3>{u.id} <button onClick={onSpec}>Platform spec</button></h3>
      <p>{u.status} · {Math.round(u.altitudeMeters)} m AGL · {Math.round(u.speed)} m/s · sensor {u.sensorState}{eff ? ` (${km(eff)} km)` : ""} · comm {u.communicationState} · component {u.networkComponent}</p>
      <p>Objective {u.currentObjective} / {u.currentAction}</p>
      {conn.length ? <p>Peers ({conn.length}): {u.neighbors.join(", ")}<br />Best: {lk(best)}<br />Worst: {lk(worst)}</p>
        : <p><b>Isolated</b> at {Math.round(u.altitudeMeters)} m{nearest ? `; nearest pair ${nearest.debug.rejectReason ?? "weak signal"}` : ""}</p>}
      <p>Skill: {u.skills.map((s) => `${s.name} ${s.status}${s.receivedFrom ? ` from ${s.receivedFrom}` : " (learned)"}`).join("; ") || "none"}</p>
      <p>Knows {u.knownPois.length} POIs, verified {u.verifiedPois.length}; {u.localKnowledgeCount} observations; {u.searchedCells} of {buf.meta!.searchGrid.nx * buf.meta!.searchGrid.ny} cells</p>
      <p>Sync ages: {Object.entries(u.lastSync).map(([k, s]) => `${k} ${hms(v.t - s)}`).join(", ") || "-"}</p>
      {last && <p><b>Why:</b> {decisionText(last)}</p>}
    </section>
  );
}

function LinkInspector({ l, cfgTransfer }: { l: RFLink; cfgTransfer: number }) {
  const rows: [string, string][] = [
    ["state", `${l.state}${l.connected ? " (connected)" : ""}`], ["distance", `${l.distanceKm.toFixed(2)} km (horizontal ${km(l.horizontalDistanceMeters)} km; altitudes ${Math.round(l.sourceAltitudeMeters)} / ${Math.round(l.targetAltitudeMeters)} m)`],
    ["rfQuality / bandwidth", `${l.rfQuality.toFixed(3)} / ${pct(l.bandwidthFactor)}`], ["LOS", `${l.lineOfSight}${l.debug.minClearanceMeters != null ? ` (min clearance ${Math.round(l.debug.minClearanceMeters)} m)` : ""}`],
    ["horizon", `${km(l.geometricHorizonMeters)} km, attenuation ${l.attenuationFactor}`], ["disruption / platform", `${l.disruptionFactor} / ${l.debug.platformFactor}; class ${l.debug.linkClass}`],
    ...(l.connected ? [["skill transfer", `~${Math.round(cfgTransfer / l.bandwidthFactor)} s`] as [string, string]] : []),
  ];
  return <section aria-label="Link inspector"><h3>{l.sourceNodeId} ↔ {l.targetNodeId}</h3>
    <dl className="m-spec">{rows.map(([k, x]) => <div key={k} style={{ display: "contents" }}><dt>{k}</dt><dd>{x}</dd></div>)}</dl><p>{explainLink(l)}</p></section>;
}

export function MissionViewer({ seed, uavs, compare, onBack }: { seed: number; uavs: number; compare?: MapSummary; onBack(): void }) {
  const { buf, origin, err } = useMissionBuffer(seed, uavs);
  const [t, setT] = useState(0), [playing, setPlaying] = useState(true), [rate, setRate] = useState(60);
  const [selUav, setSelUav] = useState<string | null>(null), [selLink, setSelLink] = useState<string | null>(null);
  const [showWeak, setShowWeak] = useState(false), [rings, setRings] = useState(false), [debug, setDebug] = useState(false), [spec, setSpec] = useState(false);
  const tmax = buf.frames.length ? buf.frames[buf.frames.length - 1].time : 0, tmaxRef = useRef(tmax);
  tmaxRef.current = tmax;
  useEffect(() => { setT(0); setPlaying(true); setSelUav(null); setSelLink(null); }, [seed, uavs]);
  useEffect(() => {
    if (!playing) return;
    let raf = 0, prev = performance.now();
    const loop = (now: number) => { const d = (now - prev) / 1000; prev = now; setT((x) => Math.min(tmaxRef.current, x + rate * d)); raf = requestAnimationFrame(loop); };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [playing, rate]);

  const meta = buf.meta, observed = useObserved(buf, buf.meta, t), view = useMemo(() => (meta ? frameAt(buf.frames, meta.dt, t) : null), [buf.frames, meta, t]);
  if (origin === "error") return <div role="alert" className="m-err"><p>Mission server not reachable and no offline replay ({err}).</p><p>Start the server from the repo root:</p><pre>{SERVER_CMD}</pre><button onClick={onBack}>Back</button></div>;
  if (!meta || !view) return <p>Connecting to the mission server… <button onClick={onBack}>Cancel</button></p>;

  const m = view.floor.mission, feed = (debug ? feedAt(buf.events, t) : demoFeed(buf.events, t)).slice(-40).reverse();
  const u = view.uavs.find((x) => x.id === selUav), link = view.floor.links.find((x) => x.id === selLink);
  const holders = view.uavs.filter((x) => x.skills.length);
  const snap = snapshotOf(meta, view, seed, observed), ended = m.status !== "RUNNING";
  return (
    <div className="m-view">
      <div className="row"><button onClick={onBack}>← Setup</button>
        <button onClick={() => setSpec(!spec)} aria-pressed={spec}>{meta.config.n_uavs} identical UAVs · {meta.uavSpec.cruiseSpeedMps} m/s · {km(meta.uavSpec.sensor.radiusMeters)} km sensor · {km(meta.uavSpec.comms.nominalRangeMeters)} km radio</button>
        <span className="pill">seed {seed}</span>{origin === "offline" && <span className="pill" role="status">offline replay</span>}
        <span className="note">{meta.world.tilesX} x {meta.world.tilesY} tiles · {km(meta.world.width)} x {km(meta.world.height)} km · skills {meta.skillsEnabled ? "on" : "off"}</span></div>
      {spec && <aside aria-label="Platform spec"><Spec meta={meta} /></aside>}
      <section aria-label="Mission HUD" className={`m-hud ${m.status}`}>
        <b className="m-status">{m.status}</b>
        <span>Clock {hms(m.elapsedTime)} · remaining {hms(m.timeLimit - m.elapsedTime)}</span>
        <span>{m.verifiedPois} / {m.requiredPois} verified · {m.discoveredPois} / {m.totalPois} discovered</span>
        <span className="m-cov">Coverage {pct(m.fleetKnowledgeCoverage)}<i><b style={{ width: pct(m.fleetKnowledgeCoverage) }} className={m.fleetKnowledgeCoverage >= m.knowledgeThreshold ? "ok" : ""} /><em style={{ left: pct(m.knowledgeThreshold) }} /></i></span>
        <span>{m.operationalNodes} / {m.totalNodes} UAVs</span>
      </section>
      <div className="m-grid">
        <div>
          <FlightMap snap={snap} height="88vh" instant />
          <div className="row" role="group" aria-label="Select UAV">{view.uavs.map((x) => <button key={x.id} aria-pressed={x.id === selUav} onClick={() => { setSelUav(x.id); setSelLink(null); }}>{x.id.replace("UAV-", "U")}</button>)}</div>
          <div className="row" role="group" aria-label="Playback">
            <button onClick={() => { if (ended && t >= tmax) setT(0); setPlaying(!playing); }}>{playing ? "Pause" : "Play"}</button>
            {RATES.map((r) => <button key={r} aria-pressed={r === rate} onClick={() => setRate(r)}>{r}x</button>)}
            <label><input type="checkbox" checked={showWeak} onChange={(e) => setShowWeak(e.target.checked)} /> weak pairs</label>
            <label><input type="checkbox" checked={rings} onChange={(e) => setRings(e.target.checked)} /> sensor rings</label>
          </div>
          <div className="m-scrub">
            <input type="range" aria-label="Seek" min={0} max={Math.max(tmax, 1)} step={meta.dt} value={t} onChange={(e) => { setT(+e.target.value); setPlaying(false); }} />
            {buf.events.filter((e) => MARKERS.has(e.type)).map((e) => <i key={e.id} title={`${hms(e.timestamp)} ${feedText(e)}`} style={{ left: `${(100 * e.timestamp) / Math.max(tmax, 1)}%` }} className={e.type} />)}
          </div>
          {!buf.stats && origin === "live" && <p className="note">streaming… buffered to {hms(tmax)}</p>}
        </div>
        <div>
          {u ? <NodeInspector u={u} v={view} buf={buf} onSpec={() => setSpec(true)} /> : link ? <LinkInspector l={link} cfgTransfer={meta.config.skill_transfer_s} /> : <p className="note">Select a UAV or a link on the map.</p>}
          <section aria-label="Skill lineage"><h3>Skill lineage</h3>
            {holders.length ? <ul>{holders.map((x) => <li key={x.id}>{x.id}: {x.skills.map((s) => `${s.status}${s.receivedFrom ? ` ← ${s.receivedFrom}` : ` (learned ${hms(s.createdAt)})`}`).join(", ")}</li>)}</ul> : <p className="note">No skill yet.</p>}
          </section>
          <section aria-label="Event feed"><h3>Events <label className="note"><input type="checkbox" checked={debug} onChange={(e) => setDebug(e.target.checked)} /> debug</label></h3>
            <ul className="m-feed">{feed.map((e) => <li key={e.id} className={e.type} onClick={() => { if (e.type === "SKILL_TRANSFERRED") { setSelLink([e.sourceNodeId, e.targetNodeId].sort().join("~")); setSelUav(null); } }}><code>{hms(e.timestamp)}</code> {feedText(e)}</li>)}</ul>
          </section>
        </div>
      </div>
      <details><summary>Judge facts</summary>
        <ol><li>All UAVs are identical: same platform, sensor and radio (see the spec card); no roles, no leader.</li>
          <li>No global comms: data and skills travel only over connected RF links of the current graph; partitions isolate nodes.</li>
          <li>Deterministic, not scripted: same code and seed give the same run; only disruptions, POIs and UAV starts come from the seed.</li>
          <li>A skill (adaptive search spacing) changes search-cell selection; the redundancy ratio measures the effect.</li>
          <li>Rule-triggered behaviour change with measurable effect, not a trained RL policy.</li></ol>
        {compare ? <Bars c={compare} /> : <p className="note">Run this map from the setup page to compare skills on vs off.</p>}
      </details>
    </div>
  );
}
