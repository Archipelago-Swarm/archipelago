import type { TerrainGrid } from "@archipelago/contracts";

export const AGL_M = 80; // drone height above ground; mirrors Terrain.agl_m in packages/sim terrain.py
const TARGET_H_M = 2;

// Same test as Terrain.los_clear in the simulator: is cell b visible from a drone hovering over cell a?
export function losClear(t: TerrainGrid, a: [number, number], b: [number, number]): boolean {
  const e = (x: number, y: number) => t.elev_m[y * t.size + x];
  const n = Math.max(Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1]));
  if (n <= 1) return true;
  const h0 = e(a[0], a[1]) + AGL_M, h1 = e(b[0], b[1]) + TARGET_H_M;
  for (let k = 1; k < 2 * n; k++) {
    const f = k / (2 * n), x = Math.round(a[0] + (b[0] - a[0]) * f), y = Math.round(a[1] + (b[1] - a[1]) * f);
    if ((x === a[0] && y === a[1]) || (x === b[0] && y === b[1])) continue;
    if (e(x, y) > h0 + (h1 - h0) * f) return false;
  }
  return true;
}

// One texel per cell: 1 = inside a drone's sensor range but hidden behind terrain from every drone, 2 = in view right now.
export function buildViewshed(t: TerrainGrid, drones: [number, number][], radius: number): Uint8Array {
  const out = new Uint8Array(t.size * t.height);
  for (const a of drones) for (let dy = -radius; dy <= radius; dy++) for (let dx = -radius; dx <= radius; dx++) {
    const x = a[0] + dx, y = a[1] + dy;
    if (x < 0 || y < 0 || x >= t.size || y >= t.height) continue;
    const i = y * t.size + x;
    if (losClear(t, a, [x, y])) out[i] = 2; else if (out[i] === 0) out[i] = 1;
  }
  return out;
}

const VS_PX = 6;
let hatchPat: CanvasPattern | null = null;
const hatch = (g: CanvasRenderingContext2D) => { // orange "\" hatch, the brand's comms-denied motif
  if (!hatchPat) {
    const p = document.createElement("canvas"); p.width = p.height = 8;
    const x = p.getContext("2d")!; x.strokeStyle = "rgba(244,123,60,0.6)"; x.lineWidth = 1.4;
    x.beginPath(); x.moveTo(-1, -1); x.lineTo(9, 9); x.moveTo(-1, 7); x.lineTo(1, 9); x.moveTo(7, -1); x.lineTo(9, 1); x.stroke();
    hatchPat = g.createPattern(p, "repeat");
  }
  return hatchPat!;
};

// Cells hidden behind terrain get an orange tint + hatch; cells in live view get a stone wash. Smoothed up from one texel per cell.
export function viewshedCanvas(t: TerrainGrid, vs: Uint8Array): HTMLCanvasElement {
  const W = t.size * VS_PX, H = t.height * VS_PX;
  const mask = (v: number) => { // alpha mask for one visibility class at cell resolution
    const c = document.createElement("canvas"); c.width = t.size; c.height = t.height;
    const g = c.getContext("2d")!, img = g.createImageData(t.size, t.height);
    for (let i = 0; i < vs.length; i++) if (vs[i] === v) img.data[i * 4 + 3] = 255;
    g.putImageData(img, 0, 0); return c;
  };
  const out = document.createElement("canvas"); out.width = W; out.height = H;
  const g = out.getContext("2d")!;
  const layer = (v: number, paint: (x: CanvasRenderingContext2D) => void) => {
    const l = document.createElement("canvas"); l.width = W; l.height = H;
    const x = l.getContext("2d")!; paint(x);
    x.globalCompositeOperation = "destination-in"; x.imageSmoothingEnabled = true; x.drawImage(mask(v), 0, 0, W, H);
    g.drawImage(l, 0, 0);
  };
  layer(2, (x) => { x.fillStyle = "rgba(237,231,223,0.16)"; x.fillRect(0, 0, W, H); });
  layer(1, (x) => { x.fillStyle = "rgba(244,123,60,0.16)"; x.fillRect(0, 0, W, H); x.fillStyle = hatch(x); x.fillRect(0, 0, W, H); });
  return out;
}
