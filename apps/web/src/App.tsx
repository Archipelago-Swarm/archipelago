import { useEffect, useRef, useState } from "react";
import { apply, initial, label, onClose, type View } from "./state";

// No credentials here: auth is the API's httponly cookie set by POST /v1/login.
const runId = new URLSearchParams(location.search).get("run") ?? "";
const CMDS = ["pause", "resume", "step", "stop"] as const;

export function App() {
  const [v, setV] = useState<View>(initial(runId));
  const [err, setErr] = useState("");
  const canvas = useRef<HTMLCanvasElement>(null);
  const replay = useRef<unknown[]>([]);

  useEffect(() => {
    if (!runId) return;
    const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/v1/runs/${runId}/stream`);
    ws.onopen = () => setV((p) => ({ ...p, conn: "live" }));
    ws.onmessage = (e) => {
      setV((p) => (p.conn === "replay" ? p : apply(p, JSON.parse(e.data))));
      // stream events omit the run revision commands need; refetch it
      fetch(`/v1/runs/${runId}`).then((r) => r.json()).then((r) => setV((p) => ({ ...p, revision: r.revision })));
    };
    ws.onclose = ws.onerror = () => setV(onClose);
    return () => ws.close();
  }, []);

  useEffect(() => {
    const c = canvas.current, s = v.snap;
    const g = c?.getContext("2d");
    if (!c || !g) return;
    g.clearRect(0, 0, c.width, c.height);
    if (!s) return;
    const k = 20;
    g.globalAlpha = v.conn === "live" || v.conn === "replay" ? 1 : 0.4; // dim stale state
    g.fillStyle = "#555";
    s.obstacles.forEach(([x, y]) => g.fillRect((x as number) * k, (y as number) * k, k, k));
    g.strokeStyle = "#07c";
    s.topology.links.forEach(([a, b]) => {
      const p = s.poses[a as string], q = s.poses[b as string];
      if (p && q) { g.beginPath(); g.moveTo(p.x * k + k / 2, p.y * k + k / 2); g.lineTo(q.x * k + k / 2, q.y * k + k / 2); g.stroke(); }
    });
    g.fillStyle = "#d50";
    Object.entries(s.poses).forEach(([id, p]) => { g.fillRect(p.x * k + 3, p.y * k + 3, k - 6, k - 6); g.fillText(id, p.x * k, p.y * k); });
  }, [v]);

  const send = async (command: string) => {
    setErr("");
    const r = await fetch(`/v1/runs/${runId}/commands`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ command, command_id: crypto.randomUUID(), expected_revision: v.revision }),
    });
    if (!r.ok) setErr(`${command} failed: ${r.status}`);
  };

  const startReplay = async () => {
    const r = await fetch(`/v1/runs/${runId}/events?limit=500`);
    if (!r.ok) return setErr(`replay failed: ${r.status}`);
    replay.current = (await r.json()).events.filter((e: { snapshot?: unknown }) => e.snapshot);
    setV((p) => ({ ...p, conn: "replay", seq: 0 }));
  };
  const stepReplay = () => {
    const e = replay.current.shift() as Parameters<typeof apply>[1] | undefined;
    if (e) setV((p) => apply(p, e));
  };

  if (!runId) return <main><h1>Archipelago</h1><p>Open with <code>?run=&lt;run_id&gt;</code>.</p></main>;
  const live = v.conn === "live";
  return (
    <main>
      <h1>Archipelago</h1>
      <p role="status" aria-live="polite">
        <strong>{label(v)}</strong> · run {v.runId} · status {v.status} · tick {v.tick} (sim ticks)
        {v.snap && <> · coverage {(v.snap.coverage * 100).toFixed(1)}% of free cells</>}
      </p>
      <canvas ref={canvas} width={400} height={400} role="img" aria-label="World map with drones and links" style={{ maxWidth: "100%" }} />
      <div>
        {CMDS.map((c) => <button key={c} disabled={!live} onClick={() => send(c)}>{c}</button>)}
        <button onClick={startReplay}>replay</button>
        <button disabled={v.conn !== "replay"} onClick={stepReplay}>next replay frame</button>
      </div>
      {err && <p role="alert">{err}</p>}
      {v.snap && <ul>{Object.keys(v.snap.poses).map((id) => <li key={id}>{id}</li>)}</ul>}
    </main>
  );
}
