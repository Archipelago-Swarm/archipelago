import type { TerrainGrid } from "@archipelago/contracts";
import { CONTOUR_M, INDEX_EVERY, detailElev } from "./terrainTexture";
import { project3, type Cam3 } from "./terrain3d";

// Elevation labels on the bold index contours, and km numbers on the grid. They are drawn as text on the overlay canvas each
// frame (not baked into a bitmap), so they are razor sharp at any zoom; candidates are computed once per terrain.
export interface ContourLabel { x: number; y: number; z: number; tx: number; ty: number; text: string; pri: number }

const STEP = 0.5; // cells between elevation samples while scanning for index-contour crossings
export function contourLabels(t: TerrainGrid, cellM: number): ContourLabel[] {
  const idxM = CONTOUR_M * INDEX_EVERY, nx = Math.floor(t.size / STEP), ny = Math.floor(t.height / STEP);
  const z = new Float32Array((nx + 1) * (ny + 1));
  for (let j = 0; j <= ny; j++) for (let i = 0; i <= nx; i++) z[j * (nx + 1) + i] = detailElev(t, i * STEP, j * STEP);
  const seen = new Set<string>(), out: ContourLabel[] = [];
  const at = (i: number, j: number) => z[Math.min(ny, Math.max(0, j)) * (nx + 1) + Math.min(nx, Math.max(0, i))];
  for (let j = 0; j <= ny; j++) for (let i = 0; i < nx; i++) {
    const z0 = at(i, j), z1 = at(i + 1, j), l0 = Math.floor(z0 / idxM), l1 = Math.floor(z1 / idxM);
    if (l0 === l1) continue;
    const lvl = Math.max(l0, l1) * idxM, f = (lvl - z0) / (z1 - z0), u = (i + f) * STEP, v = j * STEP;
    const key = `${lvl}:${Math.round(u / 3)}:${Math.round(v / 3)}`; // at most one label per level per 3x3 cells
    if (seen.has(key)) continue; seen.add(key);
    const gx = at(i + 1, j) - at(i - 1, j), gy = at(i, j + 1) - at(i, j - 1);
    if (Math.hypot(gx, gy) < 1e-3) continue;
    const l = Math.hypot(gx, gy); // contour tangent is perpendicular to the gradient
    out.push({ x: u * cellM, y: v * cellM, z: lvl, tx: -gy / l, ty: gx / l, text: String(lvl), pri: Math.sin(u * 12.9898 + v * 78.233) * 0.5 + 0.5 });
  }
  return out.sort((a, b) => a.pri - b.pri);
}

const MONO = "Consolas, 'Courier New', monospace";
export function drawTopoLabels(g: CanvasRenderingContext2D, cam: Cam3, labels: ContourLabel[], world: { w: number; h: number }, elev: (x: number, y: number) => number, explored: (x: number, y: number) => boolean) {
  g.save(); g.textAlign = "center"; g.textBaseline = "middle"; g.lineJoin = "round";
  const placed: [number, number][] = [];
  g.font = `bold 11px ${MONO}`;
  for (const l of labels) {
    if (placed.length >= 48) break;
    if (!explored(l.x, l.y)) continue; // never reveal elevations over ground nobody has seen
    const [px, py] = project3(cam, l.x, l.y, l.z);
    if (!(px > 20 && py > 20 && px < cam.W - 20 && py < cam.H - 20)) continue;
    if (placed.some(([x, y]) => (x - px) ** 2 + (y - py) ** 2 < 150 * 150)) continue; // keep labels well separated on screen
    const [qx, qy] = project3(cam, l.x + l.tx * 60, l.y + l.ty * 60, l.z);
    let a = Math.atan2(qy - py, qx - px); if (a > Math.PI / 2) a -= Math.PI; else if (a < -Math.PI / 2) a += Math.PI; // keep text upright
    placed.push([px, py]);
    g.save(); g.translate(px, py); g.rotate(a);
    g.strokeStyle = "rgba(10,10,10,0.85)"; g.lineWidth = 4; g.strokeText(l.text, 0, 0);
    g.fillStyle = "#EDE7DF"; g.fillText(l.text, 0, 0); g.restore();
  }
  g.font = `10px ${MONO}`; g.fillStyle = "rgba(138,138,138,0.95)"; // km numbers along the north and west edges
  for (let k = 1; k * 1000 < world.w; k++) { const [x, y] = project3(cam, k * 1000, 0, elev(k * 1000, 0)); if (x > 10 && x < cam.W - 10 && y > 8 && y < cam.H - 8) g.fillText(String(k), x, y - 7); }
  for (let k = 1; k * 1000 < world.h; k++) { const [x, y] = project3(cam, 0, k * 1000, elev(0, k * 1000)); if (x > 14 && x < cam.W - 10 && y > 8 && y < cam.H - 8) g.fillText(String(k), x - 9, y); }
  g.restore();
}
