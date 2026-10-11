import type { LiveEvent } from "./status";

// Local stand-in for the run stream (?demo=1): no API, Vultr or TigerData. Emits a snapshot every 100ms = 75x realtime at TICK_S 7.5.
export function startDemo(dispatch: (e: LiveEvent) => void, intervalMs = 100): () => void {
  const run_id = "demo-run", ids = ["node-01", "node-02", "node-03", "node-04"];
  const revealed = new Set<number>();
  let tick = 0, seq = 0, version = 0;
  const send = (r: object) => dispatch({ t: "message", data: JSON.stringify({ ...r, run_id, sequence: ++seq, schema_version: "0.1.0", emitted_at_utc: new Date().toISOString(), event_id: `ev-${seq}` }) });
  dispatch({ t: "open" });
  const iv = setInterval(() => {
    tick++;
    const t = tick * 7.5, poses: Record<string, object> = {};
    ids.forEach((id, i) => {
      const r = 1500 + i * 700, w = (0.06 + i * 0.01) * (i % 2 ? -1 : 1) * 0.2, a = w * t + i;
      poses[id] = { x: 5000 + r * Math.cos(a), y: 3000 + r * 0.6 * Math.sin(a), z: 100, heading_rad: a + (w > 0 ? Math.PI / 2 : -Math.PI / 2), speed_mps: Math.abs(w) * r };
    });
    if (tick % 6 === 0) {
      const to = ids[(tick / 6) % 4], from = ids[(tick / 6 + 1) % 4], ok = (tick / 6) % 3 !== 0;
      send({ kind: "peer_envelope", sender: from, recipient: to, model_version: ++version });
      send({ kind: "learning_event", sim_tick: tick, source_node_id: to, new_version: version, update_count: version, loss: 0.1, transfer: ok ? "accepted" : "rejected", reason: ok ? null : "score below threshold", bytes: 2048 });
    }
    const N = 40, NH = 24; // synthetic terrain: 40x24 cells of 250 m (10 x 6 km), observed near the flight paths
    for (const p of Object.values(poses) as { x: number; y: number }[]) {
      const cx = Math.floor(p.x / 250), cy = Math.floor(p.y / 250);
      for (let dx = -2; dx <= 2; dx++) for (let dy = -2; dy <= 2; dy++) revealed.add((cy + dy) * N + cx + dx);
    }
    const idx = Array.from({ length: N * NH }, (_, i) => i), at = (i: number) => [i % N, Math.floor(i / N)];
    const terrain = {
      size: N,
      height: NH,
      biome: idx.map((i) => { const [x, y] = at(i); return Math.floor(((Math.sin(x / 7) + Math.cos(y / 6) + 2) / 4) * 2.99); }).join(""),
      observed: idx.map((i) => (revealed.has(i) ? "1" : "0")).join(""),
      elev_m: idx.map((i) => { const [x, y] = at(i); return Math.round(250 + 150 * Math.sin(x / 5 + y / 9) + 100 * Math.cos(x / 3)); }),
      veg_pct: idx.map(() => 50),
    };
    send({
      kind: "world_snapshot", sim_tick: tick, source_node_id: null, run_status: "running", poses, obstacles: [], coverage: Math.min(1, tick / 800),
      topology: { links: [["node-01", "node-02"], ["node-03", "node-04"]] },
      world: { width_m: 10000, height_m: 6000, cell_m: 250, sensor_radius_m: 400, shapes: [], targets_found: [], terrain },
    });
  }, intervalMs);
  return () => clearInterval(iv);
}
