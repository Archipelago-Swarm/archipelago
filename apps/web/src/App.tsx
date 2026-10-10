import { useEffect, useRef, useState } from "react";
import type { WorldSnapshot } from "@archipelago/contracts";
import snapshot from "../../../packages/contracts/fixtures/good/world_snapshot.json";
import { sourceLabel, type Conn, type Source } from "./status";

// JSON imports widen tuples; the fixture is schema-validated by the contracts tests.
const fixture = snapshot as unknown as WorldSnapshot;
const CELL = 24;
const COMMANDS = ["resume", "pause", "step", "stop"] as const;

function draw(c: HTMLCanvasElement, s: WorldSnapshot) {
  const g = c.getContext("2d");
  if (!g) return; // jsdom/no-canvas environments
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

export function App() {
  const params = new URLSearchParams(location.search);
  const runId = params.get("run");
  const source: Source = runId ? (params.get("replay") ? "replay" : "live") : "fixture";
  const [snap, setSnap] = useState<WorldSnapshot>(fixture);
  const [conn, setConn] = useState<Conn>(runId ? "disconnected" : "connected");
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => { if (canvas.current) draw(canvas.current, snap); }, [snap]);

  useEffect(() => {
    if (!runId || source !== "live") return;
    let ws: WebSocket | undefined, timer: number, closed = false;
    const open = () => {
      ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/v1/runs/${runId}/stream`);
      ws.onopen = () => setConn("connected");
      ws.onmessage = (e) => {
        const m = JSON.parse(e.data);
        if (m.snapshot?.kind === "world_snapshot") setSnap(m.snapshot);
      };
      ws.onclose = () => { setConn("disconnected"); if (!closed) timer = window.setTimeout(open, 2000); };
    };
    open();
    fetch(`/v1/runs/${runId}`).then((r) => r.json()).then((v) => setRevision(v.revision)).catch(() => {});
    return () => { closed = true; clearTimeout(timer); ws?.close(); };
  }, [runId, source]);

  async function send(command: string) {
    setError("");
    const r = await fetch(`/v1/runs/${runId}/commands`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ command, command_id: crypto.randomUUID(), expected_revision: revision }),
    }).catch(() => null);
    if (!r?.ok) return setError(`${command} failed`);
    setRevision((await r.json()).revision ?? revision);
  }

  const stale = source === "live" && conn !== "connected";
  return (
    <main>
      <h1>Archipelago</h1>
      <p role="status" aria-live="polite"><strong>{sourceLabel(source, conn)}</strong></p>
      <p>Run: {snap.run_id} · status: {snap.run_status} · tick: {snap.sim_tick} · coverage: {(snap.coverage * 100).toFixed(1)}% of free cells</p>
      <canvas ref={canvas} width={20 * CELL} height={20 * CELL} aria-label="World map: drones, obstacles, links" style={{ maxWidth: "100%", opacity: stale ? 0.4 : 1 }} />
      <div role="group" aria-label="Run controls">
        {COMMANDS.map((c) => (
          <button key={c} disabled={source !== "live" || stale} onClick={() => send(c)}>{c}</button>
        ))}
      </div>
      {error && <p role="alert">{error}</p>}
      <ul aria-label="Drones">
        {Object.entries(snap.poses).map(([id, p]) => <li key={id}>{id}: ({p.x}, {p.y}) cells</li>)}
      </ul>
    </main>
  );
}
