// Replay buffer + presentation clock. The backend free-runs; playbackTime (sim seconds) advances by wall delta * rate.
import { useEffect, useRef, useState } from "react";
import type { WorldSnapshot } from "@archipelago/contracts";
import { interpPose, type Pose2 } from "./camera";

// shortcut: snapshots carry sim_tick only; sim_time = tick * TICK_S (FlightWorld default tick_s). Upgrade: add sim_time to the contract.
export const TICK_S = 7.5;
export const RATES = [0.25, 0.5, 1, 2, 4] as const;
const MAX_FRAMES = 5000; // bounded ring: oldest snapshots are dropped, playback clamps forward

export interface Frame { t: number; snap: WorldSnapshot; at: number }
export const simTime = (s: WorldSnapshot) => s.sim_tick * TICK_S;

const toPoses = (s: WorldSnapshot): Record<string, Pose2> => {
  const o: Record<string, Pose2> = {};
  for (const [id, p] of Object.entries(s.poses)) o[id] = { x: p.x, y: p.y, heading: p.heading_rad ?? 0, speed: p.speed_mps ?? 0 };
  return o;
};

// Index of the last frame with t <= time (0 if time precedes the buffer).
export function floorIndex(frames: Frame[], time: number): number {
  let lo = 0, hi = frames.length - 1;
  while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (frames[mid].t <= time) lo = mid; else hi = mid - 1; }
  return lo;
}

export function posesAt(frames: Frame[], time: number): Record<string, Pose2> | null {
  if (!frames.length) return null;
  const i = floorIndex(frames, time), a = frames[i], b = frames[i + 1];
  const pa = toPoses(a.snap);
  if (!b || time <= a.t) return pa;
  const pb = toPoses(b.snap), u = Math.min(1, (time - a.t) / (b.t - a.t));
  const out: Record<string, Pose2> = {};
  for (const [id, p0] of Object.entries(pa)) out[id] = pb[id] ? interpPose(p0, pb[id], u) : p0;
  return out;
}

export interface Playback {
  visible: WorldSnapshot | null;
  getPoses: () => Record<string, Pose2> | null;
  start: number; head: number; time: number;
  rate: number; playing: boolean; live: boolean; computeRate: number;
  setRate: (r: number) => void; toggle: () => void; goLive: () => void; seek: (t: number) => void;
}

export function usePlayback(snap: WorldSnapshot | null): Playback {
  const frames = useRef<Frame[]>([]);
  const run = useRef<string | null>(null);
  const st = useRef({ time: 0, rate: 1, playing: true, live: false });
  const [, bump] = useState(0);

  useEffect(() => {
    if (!snap) return;
    const f = frames.current;
    if (run.current !== snap.run_id) { frames.current.length = 0; run.current = snap.run_id; st.current = { time: simTime(snap), rate: 1, playing: true, live: false }; }
    const t = simTime(snap);
    if (f.length && t <= f[f.length - 1].t) return;
    f.push({ t, snap, at: performance.now() });
    if (f.length > MAX_FRAMES) f.shift();
    bump((n) => n + 1);
  }, [snap]);

  useEffect(() => {
    let raf = 0, last = performance.now();
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      const dt = now - last; last = now;
      const f = frames.current, s = st.current;
      if (!f.length) return;
      const head = f[f.length - 1].t;
      if (s.live) s.time = head;
      else if (s.playing) s.time += (dt / 1000) * s.rate;
      s.time = Math.min(head, Math.max(f[0].t, s.time)); // underrun stops at head; overrun jumps to oldest kept
    };
    raf = requestAnimationFrame(loop);
    const iv = setInterval(() => bump((n) => n + 1), 100); // UI refresh only; the canvas reads getPoses() every frame
    return () => { cancelAnimationFrame(raf); clearInterval(iv); };
  }, []);

  const f = frames.current, s = st.current;
  const head = f.length ? f[f.length - 1].t : 0, start = f.length ? f[0].t : 0;
  const k = Math.max(0, f.length - 30), a = f[k], z = f[f.length - 1];
  const computeRate = a && z && z.at > a.at ? (z.t - a.t) / ((z.at - a.at) / 1000) : 0;
  return {
    visible: f.length ? f[floorIndex(f, s.time)].snap : snap,
    getPoses: () => posesAt(frames.current, st.current.time),
    start, head, time: s.time, rate: s.rate, playing: s.playing, live: s.live, computeRate,
    setRate: (r) => { st.current.rate = r; st.current.live = false; bump((n) => n + 1); },
    toggle: () => { const x = st.current; x.playing = !x.playing; if (x.playing && x.time >= head) x.live = true; else if (!x.playing) x.live = false; bump((n) => n + 1); },
    goLive: () => { st.current.live = true; st.current.playing = true; bump((n) => n + 1); },
    seek: (t) => { st.current.live = false; st.current.time = t; bump((n) => n + 1); },
  };
}
