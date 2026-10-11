import { LineagePanel } from "./Lineage";
import { MissionHUD } from "./MissionHUD";
import { freshness, type Curve, type Panels } from "./live";

const MIB = 1024 * 1024;
const fmt = (v: number | null | undefined, digits = 0, unit = "") => (v == null ? "not reported" : `${v.toFixed(digits)}${unit}`);
const age = (at: number | undefined, now: number) => (at == null ? "no events" : `${Math.max(0, Math.round((now - at) / 1000))} s ago`);

const W = 320, H = 150, PAD = { l: 44, r: 8, t: 8, b: 30 };

export function Curves({ train, ev }: { train: Curve; ev: Curve }) {
  const all = [...train.points, ...ev.points];
  const unit = train.unit || ev.unit || "value";
  if (!all.length) return <p>Training vs frozen evaluation: no episode_return samples yet.</p>;
  const xs = all.map((p) => p.tick), ys = all.map((p) => p.value);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const sx = (v: number) => PAD.l + (x1 === x0 ? 0.5 : (v - x0) / (x1 - x0)) * (W - PAD.l - PAD.r);
  const sy = (v: number) => H - PAD.b - (y1 === y0 ? 0.5 : (v - y0) / (y1 - y0)) * (H - PAD.t - PAD.b);
  const line = (c: Curve) => c.points.map((p) => `${sx(p.tick).toFixed(1)},${sy(p.value).toFixed(1)}`).join(" ");
  return (
    <figure style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} style={{ maxWidth: "100%" }} role="img" aria-label={`Training and frozen evaluation episode return (${unit}) against simulation tick`}>
        <line x1={PAD.l} y1={H - PAD.b} x2={W - PAD.r} y2={H - PAD.b} stroke="#8a8a8a" />
        <line x1={PAD.l} y1={PAD.t} x2={PAD.l} y2={H - PAD.b} stroke="#8a8a8a" />
        <text fill="#ede7df" x={PAD.l - 4} y={PAD.t + 8} fontSize="10" textAnchor="end">{y1.toFixed(2)}</text>
        <text fill="#ede7df" x={PAD.l - 4} y={H - PAD.b} fontSize="10" textAnchor="end">{y0.toFixed(2)}</text>
        <text fill="#ede7df" x={PAD.l} y={H - PAD.b + 12} fontSize="10">{x0}</text>
        <text fill="#ede7df" x={W - PAD.r} y={H - PAD.b + 12} fontSize="10" textAnchor="end">{x1}</text>
        <text fill="#ede7df" x={(PAD.l + W - PAD.r) / 2} y={H - 4} fontSize="10" textAnchor="middle">sim tick</text>
        <text fill="#ede7df" x={4} y={H / 2} fontSize="10" transform={`rotate(-90 4 ${H / 2})`} textAnchor="middle">{unit}</text>
        {train.points.length > 0 && <polyline data-series="train" points={line(train)} fill="none" stroke="#f47b3c" strokeWidth="2" />}
        {ev.points.length > 0 && <polyline data-series="eval" points={line(ev)} fill="none" stroke="#ede7df" strokeWidth="2" strokeDasharray="5 3" />}
      </svg>
      <figcaption>Solid orange: training ({train.points.length} samples) · dashed stone: frozen evaluation ({ev.points.length} samples) · y: {unit}</figcaption>
    </figure>
  );
}

// Live panels built only from received event records; every value shows "not reported" until a record supplies it.
export function LivePanels({ p, now, recorded }: { p: Panels; now: number; recorded?: boolean }) {
  const ids = Object.keys(p.nodes).sort();
  const offers = [...p.offers].reverse();
  const rss = ids.map((i) => p.nodes[i].rssBytes).filter((v): v is number => v != null);
  const sum = (k: "dropped") => ids.reduce((a, i) => a + (p.nodes[i][k] ?? 0), 0);
  const maxBacklog = ids.reduce((a, i) => Math.max(a, p.nodes[i].backlog ?? 0), 0);
  const fresh = (at?: number) => (recorded ? "recorded" : freshness(at, now));
  return (
    <section aria-label="Live panels">
      <MissionHUD p={p} />
      <p role="status" aria-label="Fault phase" data-phase={p.faultPhase ?? "unknown"}>
        Network: <strong>{p.faultPhase ?? "not reported"}</strong> · links: {p.links.length ? p.links.map(([a, b]) => `${a}↔${b}`).join(", ") : "none"}
      </p>
      <h2>Nodes</h2>
      {ids.length ? (
        <table aria-label="Per-node status">
          <thead><tr><th>Node</th><th>Policy version</th><th>Updates</th><th>Loss</th><th>Replay size (transitions)</th><th>RSS (MiB)</th><th>Last action</th><th>Telemetry</th><th>Backlog (events)</th><th>Dropped (events)</th></tr></thead>
          <tbody>
            {ids.map((i) => { const n = p.nodes[i]; return (
              <tr key={i}>
                <td>{i}</td><td>{fmt(n.policyVersion)}</td><td>{fmt(n.updateCount)}</td><td>{fmt(n.loss, 3)}</td><td>{fmt(n.replaySize)}</td>
                <td>{n.rssBytes == null ? "not reported" : (n.rssBytes / MIB).toFixed(1)}</td><td>{n.lastAction ?? "not reported"}</td>
                <td>{fresh(n.lastEventAt)}{recorded ? "" : ` (${age(n.lastEventAt, now)})`}</td><td>{fmt(n.backlog)}</td><td>{fmt(n.dropped)}</td>
              </tr>); })}
          </tbody>
        </table>
      ) : <p>No node data received yet.</p>}
      <h2>Policy candidate offers (peer exchange)</h2>
      <table aria-label="Peer offers">
        <thead><tr><th>Tick</th><th>Sender → recipient</th><th>Version</th><th>Decision</th><th>Reason</th><th>Candidate score</th><th>Size (bytes)</th></tr></thead>
        <tbody>
          {offers.length ? offers.map((o) => (
            <tr key={o.sequence}>
              <td>{o.tick}</td><td>{o.sender ?? "not reported"} → {o.node}</td><td>{o.version}</td><td>{o.transfer}</td><td>{o.reason ?? "none"}</td><td>{fmt(o.score, 2)}</td><td>{fmt(o.bytes)}</td>
            </tr>
          )) : <tr><td colSpan={7}>No offers recorded.</td></tr>}
        </tbody>
      </table>
      <LineagePanel lineage={p.lineage} />
      <h2>Training vs frozen evaluation</h2>
      <Curves train={p.train} ev={p.eval} />
      <h2>Resources</h2>
      <p aria-label="Resources">
        Total RSS: {rss.length ? `${(rss.reduce((a, b) => a + b, 0) / MIB).toFixed(1)} MiB` : "not reported"} · max telemetry backlog: {ids.length ? `${maxBacklog} events` : "not reported"} · telemetry dropped: {ids.length ? `${sum("dropped")} events` : "not reported"} · deadlines missed: {fmt(p.counters.deadlineMissed)} · nodes unavailable: {fmt(p.counters.nodeUnavailable)}
      </p>
    </section>
  );
}
