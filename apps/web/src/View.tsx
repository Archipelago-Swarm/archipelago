import { useEffect, useRef } from "react";
import type { LearningEvent, WorldSnapshot } from "@archipelago/contracts";
import { nodeHealth } from "./client";
import { sourceLabel, type Conn, type Source } from "./status";

const CELL = 24;

function draw(c: HTMLCanvasElement, s: WorldSnapshot) {
  const g = c.getContext("2d");
  if (!g) return;
  g.clearRect(0, 0, c.width, c.height);
  g.fillStyle = "#555";
  for (const [x, y] of s.obstacles as [number, number][]) g.fillRect(x * CELL, y * CELL, CELL, CELL);
  g.strokeStyle = "#08c";
  for (const [a, b] of s.topology.links as [string, string][]) {
    const p = s.poses[a], q = s.poses[b];
    if (!p || !q) continue;
    g.beginPath();
    g.moveTo((p.x + 0.5) * CELL, (p.y + 0.5) * CELL);
    g.lineTo((q.x + 0.5) * CELL, (q.y + 0.5) * CELL);
    g.stroke();
  }
  g.fillStyle = "#d33";
  for (const p of Object.values(s.poses)) {
    g.beginPath();
    g.arc((p.x + 0.5) * CELL, (p.y + 0.5) * CELL, CELL / 3, 0, 2 * Math.PI);
    g.fill();
  }
}

export function View({ source, conn, snap, runId, learning = {} }: { source: Source; conn: Conn; snap: WorldSnapshot | null; runId?: string | null; learning?: Record<string, LearningEvent> }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => { if (canvas.current && snap) draw(canvas.current, snap); }, [snap]);
  const health = snap ? nodeHealth(snap) : {};
  return (
    <>
      <p role="status" aria-live="polite"><strong>{sourceLabel(source, conn)}</strong></p>
      {snap ? (
        <>
          <p>Run: {runId ?? snap.run_id} · status: {snap.run_status} · tick: {snap.sim_tick} · coverage: {(snap.coverage * 100).toFixed(1)}% of free cells</p>
          <canvas ref={canvas} width={20 * CELL} height={20 * CELL} aria-label="World map: drones, obstacles, links" style={{ maxWidth: "100%" }} />
          <ul aria-label="Drones">
            {Object.entries(snap.poses).map(([id, p]) => (
              <li key={id}>{id}: ({p.x}, {p.y}) cells · link: {health[id]} · {learning[id] ? `policy version: ${learning[id].new_version} · last transfer: ${learning[id].transfer}${learning[id].reason ? ` (${learning[id].reason})` : ""}` : "policy version: not reported"}</li>
            ))}
          </ul>
        </>
      ) : <p>No state: waiting for the server to send a snapshot.</p>}
    </>
  );
}
