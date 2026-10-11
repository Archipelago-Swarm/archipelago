import type { Offer } from "./live";
import { RATES, TICK_S, type Playback } from "./replay";

const mmss = (s: number) => { const t = Math.max(0, Math.round(s)); return `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`; };
const btn = (on = false) => ({ background: on ? "#2f5fb3" : "#16213a", color: "#e3eaf5", border: "1px solid #33476e", borderRadius: 4, padding: "3px 8px", cursor: "pointer", font: "inherit" }) as const;

// Replay bar attached under the map. Markers are real offer decisions from the event stream only.
export function Timeline({ pb, offers, onFocus }: { pb: Playback; offers: Offer[]; onFocus: (ids: string[]) => void }) {
  const span = Math.max(pb.head - pb.start, 1e-6), pct = (t: number) => `${Math.min(100, Math.max(0, ((t - pb.start) / span) * 100))}%`;
  const markers = offers.map((o) => ({ o, t: o.tick * TICK_S })).filter((m) => m.t >= pb.start && m.t <= pb.head);
  const click = (o: Offer, t: number) => { pb.seek(Math.max(pb.start, t - 2 * TICK_S)); onFocus([o.node, ...(o.sender ? [o.sender] : [])]); };
  return (
    <div aria-label="Playback timeline" style={{ background: "#0b1224", color: "#e3eaf5", font: "12px system-ui, sans-serif", padding: "8px 10px", borderRadius: "0 0 6px 6px", borderTop: "1px solid #1e2c4a" }}>
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
        <button style={btn()} aria-label="Jump to start" onClick={() => pb.seek(pb.start)}>⏮</button>
        <button style={btn()} aria-label={pb.playing ? "Pause" : "Play"} onClick={pb.toggle}>{pb.playing ? "❚❚" : "▶"}</button>
        {RATES.map((r) => <button key={r} style={btn(!pb.live && pb.rate === r)} onClick={() => pb.setRate(r)}>{r}×</button>)}
        <span style={{ flex: 1 }} />
        <button style={{ ...btn(pb.live), borderColor: pb.live ? "#e53935" : "#33476e", background: pb.live ? "#b71c1c" : "#16213a" }} onClick={pb.goLive}>● LIVE</button>
      </div>
      <div style={{ position: "relative", height: 16, marginTop: 6 }}>
        {markers.map(({ o, t }) => (
          <button key={o.sequence} title={`${o.sender ?? "peer"} → ${o.node}: v${o.version} ${o.transfer} @ ${mmss(t)}`} onClick={() => click(o, t)}
            style={{ position: "absolute", left: pct(t), top: 0, transform: "translateX(-50%)", background: "none", border: 0, padding: 0, cursor: "pointer", color: o.transfer === "accepted" ? "#66bb6a" : "#ffa726", font: "12px system-ui" }}>
            {o.transfer === "accepted" ? "✓" : "⇄"}
          </button>
        ))}
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <span>{mmss(pb.time)}</span>
        <input type="range" aria-label="Playback position" style={{ flex: 1 }} min={pb.start} max={Math.max(pb.head, pb.start + 1e-6)} step={0.1} value={pb.time} onChange={(e) => pb.seek(+e.target.value)} />
        <span>{mmss(pb.head)}</span>
      </div>
      <div style={{ color: "#90a4ae", marginTop: 4 }}>
        Sim compute: {pb.computeRate.toFixed(1)}× realtime · Viewing: {pb.live ? "LIVE (head)" : pb.playing ? `${pb.rate.toFixed(2).replace(/\.?0+$/, "")}× realtime` : "paused"} · {Math.max(0, pb.head - pb.time).toFixed(0)}s behind head
      </div>
    </div>
  );
}
