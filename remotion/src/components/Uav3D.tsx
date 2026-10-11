import { Cam } from "../world/camera3d";
import { V3 } from "../world/geo";

// Low-poly loyal-wingman style UAV (long pointed nose, swept tapered wings, canted twin tails). Model units, nose toward +x, y = right wing, z = up.
type M = [number, number, number];
const mirror = (v: M): M => [v[0], -v[1], v[2]];
const NOSE: M = [31, 0, -0.2];
const U1: M = [14, 0, 3.4], U2: M = [-8, 0, 4.6], UT: M = [-31, 0, 2.6];
const D1: M = [14, 0, -2.4], D2: M = [-8, 0, -3.4], DT: M = [-31, 0, -1.6];
const R1: M = [14, 3.6, 0.4], R2: M = [-8, 4.8, 0.4], RT: M = [-31, 2.8, 0.3];
const WLE: M = [10, 4.4, 0.4], WTLE: M = [-10, 25, 1.4], WTTE: M = [-17, 25.5, 1.4], WTE: M = [-14, 5.6, 0.4];
const FB1: M = [-17, 3.2, 3], FB2: M = [-30, 2.8, 2.8], FTIP: M = [-31, 9.5, 11.5];
const ENG: M = [-31, 0, 0.2];

type Face = { v: M[]; tone: number };
const half = (s: (v: M) => M): Face[] => [
  { v: [NOSE, U1, s(R1)], tone: 1.0 },
  { v: [U1, U2, s(R2), s(R1)], tone: 1.0 },
  { v: [U2, UT, s(RT), s(R2)], tone: 0.92 },
  { v: [NOSE, s(R1), D1], tone: 0.75 },
  { v: [D1, s(R1), s(R2), D2], tone: 0.75 },
  { v: [D2, s(R2), s(RT), DT], tone: 0.7 },
  { v: [s(WLE), s(WTLE), s(WTTE), s(WTE)], tone: 1.05 }, // wing, upper
  { v: [s(WLE), s(WTE), s(WTTE), s(WTLE)], tone: 0.78 }, // wing, lower
  { v: [s(FB1), s(FB2), s(FTIP)], tone: 0.8 }, // tail fin
  { v: [s(FB2), s(FB1), s(FTIP)], tone: 0.7 },
];
const FACES: Face[] = [...half((v) => v), ...half(mirror), { v: [UT, DT, ENG, UT], tone: 0.35 }];
const LIGHT = (() => { const v = [-0.5, -0.5, 0.7]; const n = Math.hypot(...v); return v.map((c) => c / n); })();

type Props = {
  cam: Cam;
  pos: V3;
  /** heading in world (x east, y south) radians */
  yaw: number;
  bank?: number;
  /** body length in world cells */
  len: number;
  color?: [number, number, number];
  opacity?: number;
};

export const Uav3D: React.FC<Props> = ({ cam, pos, yaw, bank = 0, len, color = [237, 231, 223], opacity = 1 }) => {
  const s = len / 62;
  const cy = Math.cos(yaw), sy = Math.sin(yaw), cb = Math.cos(bank), sb = Math.sin(bank);
  const world = (m: M): V3 => {
    const x = m[0] * s, y0 = m[1] * s, z0 = m[2] * s;
    const y1 = y0 * cb - z0 * sb, z1 = y0 * sb + z0 * cb;
    return { x: pos.x + x * cy - y1 * sy, y: pos.y + x * sy + y1 * cy, z: pos.z + z1 };
  };
  const faces = FACES.map((f) => {
    const w = f.v.map(world);
    const p = w.map((q) => cam.project(q));
    const e1 = { x: w[1].x - w[0].x, y: w[1].y - w[0].y, z: w[1].z - w[0].z };
    const e2 = { x: w[2].x - w[0].x, y: w[2].y - w[0].y, z: w[2].z - w[0].z };
    let n = [e1.y * e2.z - e1.z * e2.y, e1.z * e2.x - e1.x * e2.z, e1.x * e2.y - e1.y * e2.x];
    const nl = Math.hypot(n[0], n[1], n[2]) || 1;
    n = n.map((c) => c / nl);
    const lit = 0.5 + 0.5 * Math.abs(n[0] * LIGHT[0] + n[1] * LIGHT[1] + n[2] * LIGHT[2]);
    const k = lit * f.tone;
    return { p, d: p.reduce((a, q) => a + q.d, 0) / p.length, fill: `rgb(${(color[0] * k) | 0},${(color[1] * k) | 0},${(color[2] * k) | 0})` };
  }).sort((a, b) => b.d - a.d);
  return (
    <g opacity={opacity} strokeLinejoin="round">
      {faces.map((f, i) => (
        <polygon key={i} points={f.p.map((q) => `${q.x.toFixed(1)},${q.y.toFixed(1)}`).join(" ")} fill={f.fill} stroke="rgba(10,10,10,0.55)" strokeWidth={0.5} />
      ))}
    </g>
  );
};
