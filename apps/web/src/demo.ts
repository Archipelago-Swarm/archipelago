import type { LiveEvent } from "./status";
import { CANYON, eventsAt, sceneAt, type DemoController } from "./demoScriptController";

// Local stand-in for the run stream (?demo=1): no API, Vultr or TigerData. Emits a snapshot every 100ms = 75x realtime at TICK_S 7.5.
export function startDemo(dispatch: (e: LiveEvent) => void, intervalMs = 100, ctl?: DemoController): () => void {
  const run_id = "demo-run", ids = ["node-01", "node-02", "node-03", "node-04"];
  const revealed = new Set<number>();
  let tick = 0, seq = 0, version = 0;
  const held: Record<string, { id: string; gen: number }> = Object.fromEntries(ids.map((i) => [i, { id: `root-${i}`, gen: 0 }]));
  const send = (r: object) => dispatch({ t: "message", data: JSON.stringify({ ...r, run_id, sequence: ++seq, schema_version: "0.1.0", emitted_at_utc: new Date().toISOString(), event_id: `ev-${seq}` }) });
  dispatch({ t: "open" });
  const iv = setInterval(() => {
    tick++;
    const t = tick * 7.5;
    let poses: Record<string, object> = {};
    const visited = ctl?.step() ?? [], scene = ctl && sceneAt(ctl.get().t);
    visited.forEach((v) => eventsAt(v).forEach(send));
    if (scene) poses = scene.poses; else ids.forEach((id, i) => {
      const r = 1500 + i * 700, w = (0.06 + i * 0.01) * (i % 2 ? -1 : 1) * 0.2, a = w * t + i;
      poses[id] = { x: 5000 + r * Math.cos(a), y: 3000 + r * 0.6 * Math.sin(a), z: 100, heading_rad: a + (w > 0 ? Math.PI / 2 : -Math.PI / 2), speed_mps: Math.abs(w) * r };
    });
    if (!ctl && tick % 6 === 0) {
      const to = ids[(tick / 6) % 4], from = ids[(tick / 6 + 1) % 4], ok = (tick / 6) % 3 !== 0;
      send({ kind: "peer_envelope", sender: from, recipient: to, model_version: ++version });
      const cand = held[from], mine = held[to], gen = Math.max(cand.gen, mine.gen) + 1;
      const lin = ok ? { policy_id: `p${version}`, parent_ids: [mine.id, cand.id], origin_node: from, generation_count: gen } : { policy_id: `bad${version}`, parent_ids: [cand.id], origin_node: from, generation_count: cand.gen + 1, flagged_peer: from };
      if (ok) held[to] = { id: lin.policy_id, gen };
      send({ kind: "learning_event", sim_tick: tick, source_node_id: to, new_version: version, update_count: version, loss: 0.1, transfer: ok ? "accepted" : "rejected", reason: ok ? null : "output outside safety envelope", bytes: 2048, ...lin });
    }
    const N = 40, NH = 24; // synthetic terrain: 40x24 cells of 250 m (10 x 6 km), observed near the flight paths
    for (const p of Object.values(poses) as { x: number; y: number }[]) {
      const cx = Math.floor(p.x / 250), cy = Math.floor(p.y / 250);
      for (let dx = -2; dx <= 2; dx++) for (let dy = -2; dy <= 2; dy++) revealed.add((cy + dy) * N + cx + dx);
    }
    // organic canyon outline: a rounded, wobbling blob inside the scripted CANYON box (<1 = inside), not the box itself
    const ccx = (CANYON.x0 + CANYON.x1) / 500, ccy = (CANYON.y0 + CANYON.y1) / 500, chx = (CANYON.x1 - CANYON.x0) / 500, chy = (CANYON.y1 - CANYON.y0) / 500;
    const canyon = (x: number, y: number) => (Math.abs((x - ccx) / chx) ** 2.4 + Math.abs((y - ccy) / chy) ** 2.4) ** (1 / 2.4) * (1 + 0.22 * Math.sin(x / 1.7 + y / 2.3) + 0.12 * Math.cos(y / 1.3 - x / 3));
    const idx = Array.from({ length: N * NH }, (_, i) => i), at = (i: number) => [i % N, Math.floor(i / N)];
    const terrain = {
      size: N,
      height: NH,
      biome: idx.map((i) => { const [x, y] = at(i); if (ctl) return canyon(x, y) < 1 ? 0 : 1 + (Math.sin(x / 7) + Math.cos(y / 6) > 0 ? 1 : 0); return Math.floor(((Math.sin(x / 7) + Math.cos(y / 6) + 2) / 4) * 2.99); }).join(""),
      observed: idx.map((i) => (revealed.has(i) ? "1" : "0")).join(""),
      elev_m: idx.map((i) => { // massifs + warped ridge chains; the canyon is a low basin so its walls rise around it
        const [x, y] = at(i), wx = x + 3 * Math.sin(y / 5), wy = y + 3 * Math.cos(x / 6);
        const ridge = (1 - Math.abs(Math.sin(wx / 4.5 + Math.sin(wy / 7)) * Math.cos(wy / 5.5))) ** 3;
        const mass = [[8, 15, 5], [20, 6, 4], [33, 19, 5]].reduce((a, [px, py, s]) => a + Math.exp(-((x - px) ** 2 + (y - py) ** 2) / (2 * s * s)), 0);
        const open = 120 + 650 * ridge + 900 * mass, floor = 30 + 60 * ridge, k = ctl ? Math.min(1, Math.max(0, (canyon(x, y) - 0.6) / 0.7)) : 1; // smooth basin, walls rise gradually
        return Math.round(floor + (open - floor) * k * k * (3 - 2 * k));
      }),
      veg_pct: idx.map(() => 50),
    };
    send({
      kind: "world_snapshot", sim_tick: tick, source_node_id: null, run_status: "running", poses, obstacles: [], coverage: Math.min(1, tick / 800),
      topology: { links: scene ? scene.links : [["node-01", "node-02"], ["node-03", "node-04"]] },
      world: { width_m: 10000, height_m: 6000, cell_m: 250, sensor_radius_m: 400, shapes: [], targets_found: [], terrain },
    });
  }, intervalMs);
  return () => clearInterval(iv);
}
