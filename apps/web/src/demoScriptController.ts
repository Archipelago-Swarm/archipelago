import { TICK_S } from "./replay";

// Guided 5-act showcase (?demo=guided). Everything is a pure function of one script clock `t` (ticks), so
// jumping to an act is just setting t. The run is SCRIPTED and synthetic: it illustrates the mechanism, it is not a measurement.
export const ALPHA = "node-01", BETA = "node-02", GAMMA = "node-03", DELTA = "node-04";
export const NAMES: Record<string, string> = { [ALPHA]: "Alpha", [BETA]: "Beta", [GAMMA]: "Gamma", [DELTA]: "Delta" };
export const POLICY = "Canyon_Nav_v1";
export const CANYON = { x0: 6500, x1: 9500, y0: 500, y1: 2500 }; // metres; the terrain generator paints this biome 0

const TRAINED = 240, LINK_AB = [350, 430], VALIDATING = [380, 410], ADOPT_B = 410, DEAD = 470, LINK_BG = [520, 560], ADOPT_G = 540;
export const END = 600;
export const ACTS = [
  { name: "Asymmetric baseline", start: 0 }, { name: "Local discovery", start: 100 }, { name: "P2P exchange", start: 250 },
  { name: "Node attrition", start: 450 }, { name: "Provenance", start: END },
];
const CALLOUTS: [number, string][] = [
  [0, "Act 1: Alpha starts in the canyon with a generic policy and struggles; Beta flies the open lowlands where that policy works."],
  [100, "Act 2: Alpha trains locally on canyon data (accelerated). Its updates specialise the policy."],
  [TRAINED, `Act 2: Alpha has specialised a canyon policy: ${POLICY}.`],
  [250, "Act 3: Beta heads toward the canyon, where its own policy has never been tested."],
  [LINK_AB[0], "Act 3: Node Beta receives policy delta weights over P2P link"],
  [VALIDATING[0], "Act 3: Beta validates the delta on its side (lineage, encoder, canyon check) before adopting anything."],
  [ADOPT_B, `Act 3: Validation passed. Beta adopts ${POLICY} without ever training in the canyon.`],
  [450, "Act 4: Node attrition test. Alpha is about to be lost."],
  [DEAD, `Act 4: Alpha is gone. The capability survives: Beta carries ${POLICY} into the canyon.`],
  [LINK_BG[0], "Act 4: Beta passes the delta on to Gamma, a second hop that never touched Alpha."],
  [END, "Act 5: Provenance. The simulation is paused; every adoption is traceable to its origin."],
];

export interface Spotlight { dim: boolean; links: [string, string][]; pills: Record<string, string> }
export interface Scene {
  act: number; callout: string; poses: Record<string, object>; links: [string, string][]; spotlight: Spotlight;
  validation: "" | "checking" | "passed";
}

export const actAt = (t: number) => ACTS.reduce((a, x, i) => (t >= x.start ? i : a), 0);
const inside = (t: number, [a, b]: number[]) => t >= a && t < b;

// Linear interpolation through [t, x, y] waypoints plus a small wobble (amplitude m).
function at(wp: [number, number, number][], t: number, amp = 0, k = 0): [number, number] {
  let i = wp.findIndex((w) => w[0] > t);
  if (i < 0) i = wp.length - 1; else if (i === 0) i = 1;
  const [t0, x0, y0] = wp[i - 1], [t1, x1, y1] = wp[i], u = Math.min(1, Math.max(0, (t - t0) / (t1 - t0)));
  return [x0 + (x1 - x0) * u + amp * Math.sin(t / 7 + k), y0 + (y1 - y0) * u + amp * Math.cos(t / 9 + k)];
}

const PATHS: Record<string, { wp: [number, number, number][]; amp: (t: number) => number }> = {
  [ALPHA]: { wp: [[0, 7400, 1600], [100, 7700, 1500], [TRAINED, 7300, 1800], [350, 6800, 1950], [END, 6800, 1950]], amp: (t) => (t < 100 ? 380 : t < TRAINED ? 150 : 40) }, // erratic until trained
  [BETA]: { wp: [[0, 2400, 4100], [250, 2800, 3900], [350, 6300, 2100], [ADOPT_B, 6500, 2000], [END, 8100, 1300]], amp: (t) => (t < 250 ? 200 : 60) },
  [GAMMA]: { wp: [[0, 3500, 2600], [450, 3800, 2800], [LINK_BG[0], 6300, 2400], [END, 7000, 2200]], amp: () => 150 },
  [DELTA]: { wp: [[0, 5000, 4500], [END, 4600, 4700]], amp: () => 200 },
};

export function sceneAt(t: number): Scene {
  const act = actAt(t), poses: Record<string, object> = {}, linkAB = inside(t, LINK_AB), linkBG = inside(t, LINK_BG);
  Object.entries(PATHS).forEach(([id, { wp, amp }], k) => {
    if (id === ALPHA && t >= DEAD) return;
    const [x, y] = at(wp, t, amp(t), k), [nx, ny] = at(wp, t + 1, amp(t + 1), k);
    poses[id] = { x, y, z: 100, heading_rad: Math.atan2(ny - y, nx - x), speed_mps: Math.hypot(nx - x, ny - y) / TICK_S };
  });
  const links: [string, string][] = [[GAMMA, DELTA]];
  if (linkAB) links.push([ALPHA, BETA]);
  if (linkBG) links.push([BETA, GAMMA]);

  const pills: Record<string, string> = {};
  if (act === 0) { pills[ALPHA] = "Unadapted: struggling"; pills[BETA] = "Lowlands policy"; }
  else if (t < TRAINED) pills[ALPHA] = `Training: update ${Math.floor((t - 100) / 10) + 1}`;
  else if (t < DEAD) pills[ALPHA] = POLICY;
  if (t >= LINK_AB[0] && t < ADOPT_B) pills[BETA] = t < VALIDATING[0] ? "Receiving delta…" : "Validating…";
  else if (t >= ADOPT_B) pills[BETA] = `${POLICY} ✓`;
  if (t >= ADOPT_G) pills[GAMMA] = `${POLICY} ✓`; else if (linkBG) pills[GAMMA] = "Receiving delta…";

  const validation = inside(t, [VALIDATING[0], ADOPT_B + 40]) ? (t < ADOPT_B ? "checking" : "passed") : "";
  const callout = CALLOUTS.reduce((c, [at, s]) => (t >= at ? s : c), CALLOUTS[0][1]);
  return { act, callout, poses, links, validation, spotlight: { dim: act < 4, links: [...(linkAB ? [[ALPHA, BETA] as [string, string]] : []), ...(linkBG ? [[BETA, GAMMA] as [string, string]] : [])], pills } };
}

// Records emitted exactly when the clock reaches tick t.
export function eventsAt(t: number): object[] {
  const out: object[] = [];
  const ev = (node: string, o: object) => out.push({ kind: "learning_event", source_node_id: node, sim_tick: t, loss: null, update_count: 0, previous_version: 0, new_version: 1, bytes: 2048, origin_node: ALPHA, ...o });
  if (t >= 100 && t < TRAINED && t % 10 === 0) { const k = (t - 100) / 10 + 1; ev(ALPHA, { update_count: k, loss: 1 / (1 + k), new_version: 0, transfer: "none" }); }
  // Alpha's own result is the lineage root; "accepted" here means it adopted its locally trained policy.
  if (t === TRAINED) ev(ALPHA, { update_count: 15, transfer: "accepted", reason: "trained locally", policy_id: POLICY, parent_ids: [], generation_count: 1 });
  if (t === ADOPT_B) { out.push({ kind: "peer_envelope", sender: ALPHA, recipient: BETA, model_version: 1 }); ev(BETA, { transfer: "accepted", policy_id: `${POLICY}-b`, parent_ids: [POLICY], generation_count: 2 }); }
  if (t === ADOPT_G) { out.push({ kind: "peer_envelope", sender: BETA, recipient: GAMMA, model_version: 1 }); ev(GAMMA, { transfer: "accepted", policy_id: `${POLICY}-g`, parent_ids: [`${POLICY}-b`], generation_count: 3 }); }
  return out;
}

export interface DemoState { t: number; playing: boolean; speed: 1 | 2 | 5 }
export interface DemoController {
  get(): DemoState; subscribe(fn: (s: DemoState) => void): () => void;
  play(): void; pause(): void; setSpeed(s: 1 | 2 | 5): void; jump(act: number): void;
  step(): number[]; // advances by the speed if playing; returns every tick visited (so events are not skipped at 5x)
}

export function createDemoController(): DemoController {
  let s: DemoState = { t: 0, playing: true, speed: 1 };
  const subs = new Set<(s: DemoState) => void>();
  const set = (p: Partial<DemoState>) => { s = { ...s, ...p }; subs.forEach((f) => f(s)); };
  return {
    get: () => s,
    subscribe: (f) => { subs.add(f); return () => { subs.delete(f); }; },
    play: () => set({ playing: s.t < END }),
    pause: () => set({ playing: false }),
    setSpeed: (speed) => set({ speed }),
    jump: (act) => set({ t: ACTS[act].start, playing: act < ACTS.length - 1 }),
    step() {
      if (!s.playing) return [];
      const visited: number[] = [];
      for (let k = 0; k < s.speed && s.t + visited.length < END; k++) visited.push(s.t + visited.length + 1);
      const t = visited.length ? visited[visited.length - 1] : s.t;
      set({ t, playing: t < END });
      return visited;
    },
  };
}
