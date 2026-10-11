import { useEffect, useRef, useState } from "react";
import type { LearningEvent, WorldSnapshot } from "@archipelago/contracts";
import { nodeHealth } from "./client";
import { FlightMap } from "./FlightMap";
import { Timeline } from "./Timeline";
import type { Playback } from "./replay";
import { Curves, LivePanels } from "./Panels";
import { panelLabel, type Panels } from "./live";
import type { Spotlight } from "./demoScriptController";
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

export function View({ playback, source, conn, snap, runId, learning = {}, status, panels, now = 0, present = false, details = true, spotlight }: { spotlight?: Spotlight; playback?: Playback; present?: boolean; details?: boolean; panels?: Panels; now?: number; status?: string; source: Source; conn: Conn; snap: WorldSnapshot | null; runId?: string | null; learning?: Record<string, LearningEvent> }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [focus, setFocus] = useState({ ids: [] as string[], n: 0 });
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
          {snap.world
            ? <div style={{ width: "min(96vw, 1800px)", position: "relative", left: "50%", transform: "translateX(-50%)" }}>
                <FlightMap snap={snap} panels={panels} instant={source === "replay"} height={present ? "74vh" : "66vh"} getPoses={playback?.getPoses} focus={focus} spotlight={spotlight} />
                {playback && <Timeline pb={playback} offers={panels?.offers ?? []} onFocus={(ids) => setFocus((f) => ({ ids, n: f.n + 1 }))} />}
              </div>
            : <canvas ref={canvas} width={20 * CELL} height={20 * CELL} aria-label="World map: drones, obstacles, links" style={{ maxWidth: "100%" }} />}
          {present && panels && <Curves train={panels.train} ev={panels.eval} />}
          {details && <ul aria-label="Drones">
            {Object.entries(snap.poses).map(([id, p]) => (
              <li key={id}>{id}: ({p.x}, {p.y}) cells · link: {health[id]} · {learning[id] ? `policy version: ${learning[id].new_version} · last transfer: ${learning[id].transfer}${learning[id].reason ? ` (${learning[id].reason})` : ""}` : "policy version: not reported"}</li>
            ))}
          </ul>}
        </>
      ) : <p>No state: waiting for the server to send a snapshot.</p>}
      {details && panels && source !== "fixture" && (source === "live" && conn !== "connected"
        ? <p>Panels hidden: no live data while disconnected.</p>
        : <LivePanels p={panels} now={now} recorded={source !== "live"} />)}
    </>
  );
}
