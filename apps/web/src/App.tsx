import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { WorldSnapshot } from "@archipelago/contracts";
import snapshot from "../../../packages/contracts/fixtures/good/world_snapshot.json";
import peer from "../../../packages/contracts/fixtures/good/peer_envelope.json";
import learn from "../../../packages/contracts/fixtures/good/learning_event.json";
import { statusLabel, type Source } from "./model";
import { createSession, fixtureTransport, type RunControl } from "./session";

// JSON imports widen tuples; the fixture is schema-validated by the contracts tests.
const record = snapshot as unknown as WorldSnapshot;
const SCALE = 40;
// Fixture-backed until the T03/T04 API exists; swap in a real Transport here.
const transport = fixtureTransport(record, [peer], [
  { node: learn.source_node_id, new_version: learn.new_version, transfer: learn.transfer, reason: learn.reason },
]);
const session = createSession(transport);

function draw(c: HTMLCanvasElement, s: WorldSnapshot) {
  const g = c.getContext("2d");
  if (!g) return;
  g.clearRect(0, 0, c.width, c.height);
  g.fillStyle = "#555";
  for (const [x, y] of s.obstacles as [number, number][]) g.fillRect(x * SCALE, y * SCALE, SCALE, SCALE);
  g.strokeStyle = "#08c";
  for (const [a, b] of s.topology.links) {
    const p = s.poses[a as string], q = s.poses[b as string];
    if (!p || !q) continue;
    g.beginPath();
    g.moveTo(p.x * SCALE + SCALE / 2, p.y * SCALE + SCALE / 2);
    g.lineTo(q.x * SCALE + SCALE / 2, q.y * SCALE + SCALE / 2);
    g.stroke();
  }
  g.fillStyle = "#c30";
  for (const p of Object.values(s.poses)) {
    g.beginPath();
    g.arc(p.x * SCALE + SCALE / 2, p.y * SCALE + SCALE / 2, 8, 0, 2 * Math.PI);
    g.fill();
  }
}

export function App() {
  const ref = useRef<HTMLCanvasElement>(null);
  const s = useSyncExternalStore(session.subscribe, session.get);
  const [seed, setSeed] = useState(1);
  const [source, setSource] = useState<Source>("replay");
  const snap = s.frame?.snapshot;
  useEffect(() => { if (ref.current && snap) draw(ref.current, snap); }, [snap]);
  const ctl = (c: RunControl, label: string) => (
    <button onClick={() => session.control(c)} disabled={!s.connected}>{label}</button>
  );
  const links = snap?.topology.links ?? [];
  return (
    <main>
      <h1>Archipelago</h1>
      <form onSubmit={(e) => { e.preventDefault(); session.connect(source, seed); }}>
        <label>Scenario seed <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} /></label>{" "}
        <label>Mode <select value={source} onChange={(e) => setSource(e.target.value as Source)}>
          <option value="replay">Replay</option><option value="live">Live</option></select></label>{" "}
        <button type="submit">Load run</button>{" "}
        <button type="button" onClick={() => session.reconnect()} disabled={s.connected}>Reconnect</button>
      </form>
      <p role="status">
        {snap
          ? `${statusLabel(s.source, s.connected)} · run ${snap.run_id} · tick ${snap.sim_tick} · status ${s.connected ? snap.run_status : "unknown"}`
          : "No run loaded"}
      </p>
      {snap && <p>Coverage: {(snap.coverage * 100).toFixed(1)} % of free cells</p>}
      <canvas ref={ref} width={400} height={240} role="img"
        aria-label={snap ? `World with ${Object.keys(snap.poses).length} drones and ${links.length} links` : "Empty world"} />
      <div>
        {ctl("start", "Start")} {ctl("pause", "Pause")} {ctl("resume", "Resume")} {ctl("step", "Step")} {ctl("stop", "Stop")}{" "}
        <button onClick={() => transport.drop()} disabled={!s.connected}>Simulate disconnect</button>
      </div>
      {snap && (
        <>
          <h2>Nodes</h2>
          <ul aria-label="Node health">
            {Object.keys(snap.poses).map((id) => {
              const n = links.filter(([a, b]) => a === id || b === id).length;
              return <li key={id}>{id}: {n ? `${n} link(s)` : "isolated"}</li>;
            })}
          </ul>
          <h2>Policies and transfers</h2>
          <ul aria-label="Policy versions and transfers">
            {s.frame?.learning.map((l, i) => <li key={i}>{l.node}: policy v{l.new_version}, transfer {l.transfer} ({l.reason})</li>)}
            {s.frame?.transfers.map((t, i) => <li key={`t${i}`}>{t.sender} to {t.recipient}: offered model v{t.model_version}</li>)}
          </ul>
        </>
      )}
    </main>
  );
}
