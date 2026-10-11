// Terrain model: DEM (real elevation reference) + deterministic ridge detail, line of sight and viewshed.
import { COAST_B64, DEM_B64, DEM_H, DEM_W } from "./dem";

/** world units are DEM cells (~5.2 km); height is in cells at ZS cells per metre (vertically exaggerated) */
export const ZS = 1.5 / 1000;
export const GRID = { w: DEM_W, h: DEM_H };

const dem = (() => {
  const bin = atob(DEM_B64);
  const a = new Float32Array(DEM_W * DEM_H);
  for (let i = 0; i < a.length; i++) a[i] = bin.charCodeAt(2 * i) | (bin.charCodeAt(2 * i + 1) << 8);
  return a;
})();

const coast = (() => {
  const bin = atob(COAST_B64);
  const a = new Float32Array(DEM_W * DEM_H);
  for (let i = 0; i < a.length; i++) a[i] = bin.charCodeAt(i) / 255;
  return a;
})();
// beyond the data the terrain is mirrored (and faded out by the renderer) so the world has no visible edge
const refl = (i: number, n: number) => { const p = 2 * (n - 1); const m = ((i % p) + p) % p; return m < n ? m : p - m; };
const atC = (i: number, j: number) => coast[refl(j, DEM_H) * DEM_W + refl(i, DEM_W)];

const at = (i: number, j: number) => dem[refl(j, DEM_H) * DEM_W + refl(i, DEM_W)];

const hash = (ix: number, iy: number) => {
  const h = Math.imul(ix, 374761393) ^ Math.imul(iy, 668265263);
  let x = Math.imul(h ^ (h >>> 13), 1274126177);
  x ^= x >>> 16;
  return (x >>> 0) / 4294967296;
};
const sm = (f: number) => f * f * (3 - 2 * f);
function noise(x: number, y: number) {
  const ix = Math.floor(x), iy = Math.floor(y);
  const fx = sm(x - ix), fy = sm(y - iy);
  const a = hash(ix, iy), b = hash(ix + 1, iy), c = hash(ix, iy + 1), d = hash(ix + 1, iy + 1);
  return a + (b - a) * fx + (c - a) * fy + (a - b - c + d) * fx * fy;
}

/** elevation in metres (bilinear DEM + ridged detail on land) */
export function elevM(x: number, y: number, detail = 1): number {
  const i = Math.floor(x), j = Math.floor(y);
  const fx = x - i, fy = y - j;
  const m0 = at(i, j) * (1 - fx) * (1 - fy) + at(i + 1, j) * fx * (1 - fy) + at(i, j + 1) * (1 - fx) * fy + at(i + 1, j + 1) * fx * fy;
  const c = atC(i, j) * (1 - fx) * (1 - fy) + atC(i + 1, j) * fx * (1 - fy) + atC(i, j + 1) * (1 - fx) * fy + atC(i + 1, j + 1) * fx * fy;
  if (c <= 0.5) return 0;
  const m = Math.max(4, m0 * Math.min(1, (c - 0.5) / 0.3));
  if (detail <= 0) return m;
  const u = x * 0.8 - y * 0.6, v = x * 0.6 + y * 0.8; // rotated so ridge detail is not grid-aligned
  const n = 1 - Math.abs(2 * (noise(u * 0.3, v * 0.5) * 0.62 + noise(u * 0.7, v * 0.9) * 0.28 + noise(u * 1.5, v * 1.9) * 0.1) - 1);
  return Math.max(4, m + (n - 0.5) * 2 * 95 * detail * Math.min(1, m / 200));
}
/** terrain height in world cells */
export const H = (x: number, y: number) => elevM(x, y) * ZS;

/** smoothed terrain height (for flight altitude) */
export const Hs = (x: number, y: number) => {
  let m = 0;
  for (const [dx, dy] of [[0, 0], [1.2, 0], [-1.2, 0], [0, 1.2], [0, -1.2], [0.9, 0.9], [-0.9, -0.9], [0.9, -0.9], [-0.9, 0.9]]) m = Math.max(m, H(x + dx, y + dy));
  return m;
};

export type V3 = { x: number; y: number; z: number };

/** Straight-line visibility between two 3D points over terrain. t = fraction along the ray where it is blocked. */
export function los(a: V3, b: V3): { clear: boolean; t: number } {
  const d = Math.hypot(b.x - a.x, b.y - a.y);
  const n = Math.max(2, Math.ceil(d * 3));
  for (let i = 1; i < n; i++) {
    const t = i / n;
    if (H(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t) > a.z + (b.z - a.z) * t) return { clear: false, t };
  }
  return { clear: true, t: 1 };
}

export const EYE = 0.06; // ground sensor height above terrain, cells

export type Viewshed = { x0: number; y0: number; n: number; res: number; vis: Float32Array };
/** Ground cells a ground-level observer at (tx,ty) can see within `range` (the "line-of-sight risk" layer). */
export function viewshed(tx: number, ty: number, range: number, res = 0.15): Viewshed {
  const n = Math.ceil((range * 2) / res) + 1;
  const x0 = tx - range, y0 = ty - range;
  const vis = new Float32Array(n * n);
  const o = { x: tx, y: ty, z: H(tx, ty) + EYE };
  for (let j = 0; j < n; j++)
    for (let i = 0; i < n; i++) {
      const x = x0 + i * res, y = y0 + j * res;
      const d = Math.hypot(x - tx, y - ty);
      if (d > range) continue;
      vis[j * n + i] = los(o, { x, y, z: H(x, y) + 0.02 }).clear ? 1 - d / range : 0;
    }
  return { x0, y0, n, res, vis };
}
export const sampleVis = (v: Viewshed, x: number, y: number) => {
  const fi = (x - v.x0) / v.res, fj = (y - v.y0) / v.res;
  const i = Math.floor(fi), j = Math.floor(fj);
  if (i < 0 || j < 0 || i >= v.n - 1 || j >= v.n - 1) return 0;
  const fx = fi - i, fy = fj - j;
  const g = (a: number, b: number) => v.vis[b * v.n + a];
  return g(i, j) * (1 - fx) * (1 - fy) + g(i + 1, j) * fx * (1 - fy) + g(i, j + 1) * (1 - fx) * fy + g(i + 1, j + 1) * fx * fy;
};

/** land fraction 0..1 (shoreline at 0.5), bilinear */
export function coastAt(x: number, y: number): number {
  const i = Math.floor(x), j = Math.floor(y), fx = x - i, fy = y - j;
  return atC(i, j) * (1 - fx) * (1 - fy) + atC(i + 1, j) * fx * (1 - fy) + atC(i, j + 1) * (1 - fx) * fy + atC(i + 1, j + 1) * fx * fy;
}
