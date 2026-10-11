import { CY, W as SW, lerp, P, smooth } from "./paths";
import { H, V3 } from "./geo";
import { CMD, sampleAt, trackA, trackB } from "./scenario";

export type View = { cx: number; cy: number; dist: number; pitch: number; yaw: number };
export type Cam = View & { eye: V3; target: V3; fovDeg: number; project: (p: V3) => { x: number; y: number; d: number }; scale: (d: number) => number };

const FOCAL = 1500;

export function makeCam(v: View): Cam {
  const fz = H(v.cx, v.cy);
  const p = (v.pitch * Math.PI) / 180, y = (v.yaw * Math.PI) / 180;
  const off = { x: Math.cos(p) * Math.sin(y), y: Math.cos(p) * Math.cos(y), z: Math.sin(p) };
  const C = { x: v.cx + off.x * v.dist, y: v.cy + off.y * v.dist, z: fz + off.z * v.dist };
  const f = { x: -off.x, y: -off.y, z: -off.z };
  const r = { x: Math.cos(y), y: -Math.sin(y), z: 0 };
  const u = { x: f.y * r.z - f.z * r.y, y: f.z * r.x - f.x * r.z, z: f.x * r.y - f.y * r.x };
  return {
    ...v,
    eye: C,
    target: { x: v.cx, y: v.cy, z: fz },
    fovDeg: (2 * Math.atan(540 / FOCAL) * 180) / Math.PI,
    project: (q) => {
      const dx = q.x - C.x, dy = q.y - C.y, dz = q.z - C.z;
      const d = dx * f.x + dy * f.y + dz * f.z;
      const k = FOCAL / Math.max(0.01, d);
      return { x: SW / 2 + (dx * r.x + dy * r.y + dz * r.z) * k, y: CY - (dx * u.x + dy * u.y + dz * u.z) * k, d };
    },
    scale: (d) => FOCAL / Math.max(0.01, d),
  };
}

type Focus = "south" | "strait" | "a" | "n2" | "mid" | "b" | "n3" | "relay" | "coast";
const focusAt = (f: Focus, t: number): P => {
  const n2 = sampleAt(1, t), n3 = sampleAt(2, t), n4 = sampleAt(3, t);
  switch (f) {
    case "strait": return { x: 88, y: 74 };
    case "south": return { x: 90, y: 79 };
    case "coast": return { x: 76, y: 52 };
    case "a": { const w = smooth((t - 54) / 3), a = trackA(t), k = { x: lerp(n2.x, n4.x, w), y: lerp(n2.y, n4.y, w) }; return { x: (a.x + k.x) / 2, y: (a.y + k.y) / 2 }; }
    case "n2": return { x: n2.x, y: n2.y };
    case "b": return { x: (trackB(t).x + n3.x) / 2, y: (trackB(t).y + n3.y) / 2 };
    case "n3": return { x: n3.x, y: n3.y };
    case "mid": return { x: (n2.x + n3.x) / 2, y: (n2.y + n3.y) / 2 };
    case "relay": { const n1 = sampleAt(0, t); return { x: (n4.x + n1.x + CMD.x) / 3, y: (n4.y + n1.y + CMD.y) / 3 }; }
  }
};

// camera path: strait overview -> coast -> over the first track -> across to NODE-03 -> second track -> comms zone -> relay -> back
const KEYS: { t: number; f: Focus; dist: number; pitch: number; yaw: number }[] = [
  { t: 0, f: "strait", dist: 118, pitch: 52, yaw: 0 },
  { t: 6, f: "strait", dist: 112, pitch: 50, yaw: -6 },
  { t: 12, f: "a", dist: 46, pitch: 44, yaw: -18 },
  { t: 20, f: "a", dist: 40, pitch: 38, yaw: 8 },
  { t: 28, f: "a", dist: 44, pitch: 42, yaw: 24 },
  { t: 33, f: "mid", dist: 78, pitch: 48, yaw: 6 },
  { t: 38, f: "b", dist: 52, pitch: 42, yaw: -14 },
  { t: 46, f: "b", dist: 46, pitch: 38, yaw: 10 },
  { t: 50, f: "south", dist: 104, pitch: 50, yaw: 0 },
  { t: 55, f: "a", dist: 56, pitch: 44, yaw: -10 },
  { t: 60, f: "relay", dist: 100, pitch: 48, yaw: -6 },
  { t: 65, f: "relay", dist: 100, pitch: 50, yaw: -8 },
  { t: 69, f: "strait", dist: 120, pitch: 52, yaw: -2 },
  { t: 72, f: "strait", dist: 118, pitch: 52, yaw: 0 },
];

export function viewAt(t: number): View {
  let i = 0;
  while (i < KEYS.length - 2 && t >= KEYS[i + 1].t) i++;
  const a = KEYS[i], b = KEYS[i + 1];
  const f = smooth((t - a.t) / (b.t - a.t));
  const pa = focusAt(a.f, t), pb = focusAt(b.f, t);
  return {
    cx: lerp(pa.x, pb.x, f), cy: lerp(pa.y, pb.y, f),
    dist: Math.exp(lerp(Math.log(a.dist), Math.log(b.dist), f)),
    pitch: lerp(a.pitch, b.pitch, f), yaw: lerp(a.yaw, b.yaw, f),
  };
}
