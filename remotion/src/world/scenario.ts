// Mission scenario: moving tracks + the autonomy that reacts to terrain. Everything is precomputed once, deterministically,
// by stepping a simple controller at 30 Hz, so a given frame always renders the same.
import { EYE, H, Hs, los, V3 } from "./geo";
import { DURATION_S as D, FPS, loopPos, P, win } from "./paths";

const K = (v: number[][]): P[] => v.map(([x, y]) => ({ x, y }));

// Least-cost valley routes through the DEM (see scratchpad/route.py); closed loops, one key every D/16 s.
const KEYS_A = K([[78, 40], [83.3, 41.3], [87, 46.6], [86.1, 52.9], [80.8, 56.2], [75.2, 59], [68.4, 59], [62.1, 58.1], [57.3, 53.3], [54, 48], [50, 42.9], [53, 37.4], [56, 32], [62, 30], [67.4, 33], [73.2, 35.2]]);
const KEYS_B = K([[62, 76], [58.4, 76.6], [54.8, 79], [52, 82], [50, 85.7], [46.5, 88], [43.1, 85.1], [41.2, 81.2], [38, 78], [41.8, 76], [46, 77], [50.5, 76.5], [52, 72.6], [52.1, 68], [56.2, 69.2], [59.4, 72.4]]);

export const trackA = (t: number) => loopPos(KEYS_A, t);
export const trackB = (t: number) => loopPos(KEYS_B, t);

const ring = (cx: number, cy: number, rx: number, ry: number, n = 8, ph = 0): P[] =>
  Array.from({ length: n }, (_, i) => ({ x: cx + rx * Math.cos(ph + (i / n) * 2 * Math.PI), y: cy + ry * Math.sin(ph + (i / n) * 2 * Math.PI) }));

export const CMD = { x: 112, y: 97 }; // command node, Taiwan west coast
export const PATROL: P[][] = [
  ring(97, 66, 12, 9, 8, 0.4), // NODE-01 comms bridge, mid-strait
  ring(101, 48, 7, 9, 8, 2.2), // NODE-02
  ring(96, 88, 10, 8, 8, 1.0), // NODE-03
  ring(92, 31, 8, 6, 8, 3.0), // NODE-04
];
// three laps per 72 s so patrol speed (~2 cells/s) is above the fixed-wing minimum and rejoining never forces a loiter circle
export const patrolPos = (i: number, t: number) => loopPos(PATROL[i], 3 * t);

export const THREAT_R = 8; // cells: hostile sensor picture
export const SENSOR_R = 26; // cells: our standoff sensor
const AGL_LOW = 0.03; // terrain-hugging pursuit
const AGL_HIGH = 1.1; // ridge overwatch
const VMAX = 3.0;
const VMIN = 1.7; // fixed-wing: cannot hover, so it loiters instead
const TURN = 0.6; // rad/s max turn rate
/** fixed-wing kinematics: heading turns at a bounded rate toward the goal, speed never drops below VMIN */
function fly(a: Agent, dx: number, dy: number, dt: number) {
  const ex = dx - a.x, ey = dy - a.y;
  const e = wrapPi(Math.atan2(ey, ex) - a.hdg);
  a.hdg += Math.max(-TURN * dt, Math.min(TURN * dt, e));
  a.spd += (Math.max(VMIN, Math.min(VMAX, Math.hypot(ex, ey) * 0.5)) - a.spd) * Math.min(1, dt * 1.5);
  a.x += Math.cos(a.hdg) * a.spd * dt;
  a.y += Math.sin(a.hdg) * a.spd * dt;
}

export type Phase = "patrol" | "chase" | "standoff" | "return";
export type Sample = { x: number; y: number; z: number; hx: number; hy: number; tracked: boolean; exposed: boolean; conf: number; phase: Phase };

const NF = D * FPS;
const dir = (f: (t: number) => P, t: number) => {
  const a = f(t - 0.5), b = f(t + 0.5);
  const l = Math.hypot(b.x - a.x, b.y - a.y) || 1;
  return { x: (b.x - a.x) / l, y: (b.y - a.y) / l };
};
const wrapPi = (a: number) => Math.atan2(Math.sin(a), Math.cos(a));

type Policy = "chase" | "standoff";
type Agent = { R: number; x: number; y: number; hdg: number; spd: number; ang: number; conf: number };

/** One controller step: pick a desired point for the policy, fly toward it with a speed limit. */
function step(a: Agent, policy: Policy, target: (t: number) => P, t: number, dt: number): { tracked: boolean; exposed: boolean } {
  const tg = target(t);
  let dx: number, dy: number;
  if (policy === "chase") {
    // naive: tail the track a few cells behind, cutting straight across terrain
    const d = dir(target, t);
    dx = tg.x - d.x * 4.5 + -d.y * 1.5;
    dy = tg.y - d.y * 4.5 + d.x * 1.5;
  } else {
    // learned: stand off on a ridge at ~12 cells, on the side where terrain keeps line of sight to where the track is going
    const pr = target(t + 2.5);
    if (Number.isNaN(a.ang)) a.ang = Math.atan2(a.y - pr.y, a.x - pr.x);
    let best = -1e9, bestAng = a.ang, bestR = 14;
    for (const R of [11.5, 14, 17])
      for (let k = 0; k < 24; k++) {
        const ang = (k / 24) * 2 * Math.PI;
        const px = pr.x + R * Math.cos(ang), py = pr.y + R * Math.sin(ang);
        const up = { x: px, y: py, z: Hs(px, py) + AGL_HIGH };
        const clear = los(up, { x: tg.x, y: tg.y, z: H(tg.x, tg.y) + 0.03 }).clear && los(up, { x: pr.x, y: pr.y, z: H(pr.x, pr.y) + 0.03 }).clear;
        const score = (clear ? 100 : 0) - (Math.hypot(px - tg.x, py - tg.y) < 11 || Math.hypot(px - pr.x, py - pr.y) < 11 ? 1000 : 0) - Math.abs(wrapPi(ang - a.ang)) * 40 - Math.abs(R - 14) * 3 + Hs(px, py) * 6;
        if (score > best) { best = score; bestAng = ang; bestR = R; }
      }
    a.ang += Math.max(-0.6 * dt, Math.min(0.6 * dt, wrapPi(bestAng - a.ang))); // slew: never swing through the track
    a.R += (bestR - a.R) * Math.min(1, dt * 1.5);
    dx = pr.x + a.R * Math.cos(a.ang);
    dy = pr.y + a.R * Math.sin(a.ang);
  }
  fly(a, dx, dy, dt);
  const agl = policy === "chase" ? AGL_LOW : AGL_HIGH;
  const u: V3 = { x: a.x, y: a.y, z: Hs(a.x, a.y) + agl };
  const g: V3 = { x: tg.x, y: tg.y, z: H(tg.x, tg.y) + EYE };
  const range = Math.hypot(tg.x - a.x, tg.y - a.y);
  const seen = los(u, g).clear;
  const tracked = seen && range < SENSOR_R;
  const exposed = seen && range < THREAT_R;
  a.conf = Math.min(1, Math.max(0, a.conf + (tracked ? 0.8 : -1.1) * dt));
  return { tracked, exposed };
}

type Plan = { from: number; to: number; target: (t: number) => P; policy: (t: number) => Policy };
const mk = (): Agent => ({ R: 14, x: 0, y: 0, hdg: 0, spd: 0, ang: NaN, conf: 0 });

function simulate(i: number, plans: Plan[], retHold: number) {
  const out: Sample[] = [];
  const ag = mk();
  let live = false;
  for (let f = 0; f < NF; f++) {
    const t = f / FPS;
    const pat = patrolPos(i, t);
    const plan = plans.find((p) => t >= p.from && t < p.to);
    let phase: Phase = "patrol";
    let tracked = false, exposed = false;
    if (plan) {
      if (!live) {
        const q = patrolPos(i, t + 0.1);
        ag.x = pat.x; ag.y = pat.y; ag.hdg = Math.atan2(q.y - pat.y, q.x - pat.x); ag.spd = Math.hypot(q.x - pat.x, q.y - pat.y) / 0.1; live = true;
      }
      const pol = plan.policy(t);
      ({ tracked, exposed } = step(ag, pol, plan.target, t, 1 / FPS));
      phase = pol;
    } else if (live) {
      // rejoin the patrol loop (aim a little ahead of the slow-moving patrol point), then blend onto it so the video loops
      const lead = patrolPos(i, t + 0.8);
      fly(ag, lead.x, lead.y, 1 / FPS);
      phase = "return";
    }
    const bl = win(t, 70, 72);
    const x = live ? ag.x + (pat.x - ag.x) * bl : pat.x, y = live ? ag.y + (pat.y - ag.y) * bl : pat.y;
    const prev = out[f - 1];
    const p3 = out[f - 3] ?? prev;
    const hx = p3 ? x - p3.x : 1, hy = p3 ? y - p3.y : 0;
    out.push({
      x, y, z: Hs(x, y) + (phase === "chase" ? AGL_LOW : AGL_HIGH),
      hx: Math.hypot(hx, hy) > 1e-4 ? hx : prev?.hx ?? 1, hy: Math.hypot(hx, hy) > 1e-4 ? hy : prev?.hy ?? 0,
      tracked, exposed, conf: ag.conf, phase,
    });
  }
  return out;
}

// phase boundaries (seconds), shared with the scenes
export const T = {
  contact: 7, baseline: 14, learn: 25, transfer: 32, general: 40, comms: 48, loss: 54.5, handoff: 57, relay: 61, wrap: 67,
};

const chaseThenStandoff = (switchAt: number) => (t: number): Policy => (t < switchAt ? "chase" : "standoff");

export const SIM = [
  null as unknown as Sample[], // NODE-01: pure patrol
  simulate(1, [{ from: 6, to: T.loss + 0.8, target: trackA, policy: chaseThenStandoff(T.learn) }], 0),
  simulate(2, [{ from: 27, to: 54, target: trackB, policy: (t) => (t < 36.5 ? "chase" : "standoff") }], 56),
  simulate(3, [{ from: 49, to: 62, target: trackA, policy: () => "standoff" }], 67),
];
SIM[0] = Array.from({ length: NF }, (_, f) => {
  const p = patrolPos(0, f / FPS), q = patrolPos(0, f / FPS - 0.05);
  return { x: p.x, y: p.y, z: Hs(p.x, p.y) + 0.9, hx: p.x - q.x, hy: p.y - q.y, tracked: false, exposed: false, conf: 0, phase: "patrol" as Phase };
});

/** NODE-03 without the transferred capability: keeps chasing the second track (drawn as a ghost for comparison). */
export const GHOST = simulate(2, [{ from: 27, to: 54, target: trackB, policy: () => "chase" }], 56);

export const sampleAt = (i: number, t: number): Sample => SIM[i][Math.min(NF - 1, Math.max(0, Math.round(t * FPS)))];
export const ghostAt = (t: number): Sample => GHOST[Math.min(NF - 1, Math.max(0, Math.round(t * FPS)))];

/** blend sim <-> patrol so frame 0 and the last frame coincide (loop) */
export const alive = (i: number, t: number) => (i === 1 ? 1 - win(t, 54.5, 55.3) + win(t, 69, 72) : 1);
void win;
