import { useEffect, useRef } from "react";
import type { LearningEvent, WorldSnapshot } from "@archipelago/contracts";
import { nodeHealth } from "./client";
import { LivePanels } from "./Panels";
import { panelLabel, type Panels } from "./live";
import { sourceLabel, type Conn, type Source } from "./status";

const CELL = 24;

function draw(c: HTMLCanvasElement, s: WorldSnapshot, actions: Record<string, string | undefined>) {
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
  g.fillStyle = "#000";
  g.font = "10px sans-serif";
  for (const [id, p] of Object.entries(s.poses)) g.fillText(`${id}${actions[id] ? `: ${actions[id]}` : ""}`, (p.x + 1) * CELL, (p.y + 0.4) * CELL);
}

export function View({ source, conn, snap, runId, learning = {}, status, panels, now = 0 }: { panels?: Panels; now?: number; status?: string; source: Source; conn: Conn; snap: WorldSnapshot | null; runId?: string | null; learning?: Record<string, LearningEvent> }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const actions = Object.fromEntries(Object.entries(panels?.nodes ?? {}).map(([id, n]) => [id, n.lastAction]));
  const actionKey = JSON.stringify(actions);
  useEffect(() => { if (canvas.current && snap) draw(canvas.current, snap, actions); }, [snap, actionKey]);
  const label = panels && source === "live" ? panelLabel(source, conn, status, panels.lastEventAt, now) : sourceLabel(source, conn, status);
  const health = snap ? nodeHealth(snap) : {};
  return (
    <>
      <p role="status" aria-live="polite"><strong>{label}</strong></p>
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
      {panels && source !== "fixture" && (source === "live" && conn !== "connected"
        ? <p>Panels hidden: no live data while disconnected.</p>
        : <LivePanels p={panels} now={now} recorded={source !== "live"} />)}
    </>
  );
}
