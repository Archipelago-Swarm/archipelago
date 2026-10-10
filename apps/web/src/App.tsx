import { useEffect, useRef } from "react";
import type { WorldSnapshot } from "@archipelago/contracts";
import snapshot from "../../../packages/contracts/fixtures/good/world_snapshot.json";
import { statusLabel } from "./model";

// JSON imports widen tuples; the fixture is schema-validated by the contracts tests.
const record = snapshot as unknown as WorldSnapshot;
const SCALE = 40;

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
  useEffect(() => { if (ref.current) draw(ref.current, record); }, []);
  // Fixture replay only: no API/stream yet, so source is always "replay".
  const label = statusLabel("replay", true);
  return (
    <main>
      <h1>Archipelago</h1>
      <p role="status">{label} · run {record.run_id} · tick {record.sim_tick} · status {record.run_status}</p>
      <p>Coverage: {(record.coverage * 100).toFixed(1)} % of free cells</p>
      <canvas ref={ref} width={400} height={240} role="img"
        aria-label={`World with ${Object.keys(record.poses).length} drones and ${record.topology.links.length} links`} />
      <div>
        <button disabled>Start</button> <button disabled>Pause</button>{" "}
        <button disabled>Step</button> <button disabled>Stop</button>
        <small> Controls need the T03/T04 API.</small>
      </div>
    </main>
  );
}
