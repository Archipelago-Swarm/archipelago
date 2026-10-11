import type { TerrainGrid } from "@archipelago/contracts";

const BASE = [[150, 178, 100], [64, 120, 60], [26, 82, 44]]; // grass, forest, jungle
const FOG = [13, 20, 36]; // unobserved terrain is mixed toward the background so it reads as dim, not gone
const UP = 8;

// One texel per cell with hillshading, then upscaled with smoothing so the map has no visible grid.
export function buildTerrainTexture(t: TerrainGrid): HTMLCanvasElement {
  const w = t.size, h = t.height, small = document.createElement("canvas");
  small.width = w; small.height = h;
  const g = small.getContext("2d")!, img = g.createImageData(w, h);
  const at = (x: number, y: number) => Math.min(h - 1, Math.max(0, y)) * w + Math.min(w - 1, Math.max(0, x));
  const e = (x: number, y: number) => t.elev_m[at(x, y)];
  const obs = (x: number, y: number) => (t.observed[at(x, y)] === "1" ? 1 : 0);
  const seen = (x: number, y: number) => { let a = 0; for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) a += obs(x + dx, y + dy); return a / 9; }; // soft fog edge
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = y * w + x, base = BASE[+t.biome[i]] ?? BASE[0];
    const hill = Math.max(-0.4, Math.min(0.4, (e(x - 1, y) + e(x, y - 1) - e(x + 1, y) - e(x, y + 1)) / 160)); // light from the north-west
    const k = 0.75 + 0.45 * Math.min(1, e(x, y) / 500) + hill, fog = 0.62 * (1 - seen(x, y));
    for (let c = 0; c < 3; c++) img.data[i * 4 + c] = Math.max(0, Math.min(255, base[c] * k)) * (1 - fog) + FOG[c] * fog;
    img.data[i * 4 + 3] = 255;
  }
  g.putImageData(img, 0, 0);
  const big = document.createElement("canvas");
  big.width = w * UP; big.height = h * UP;
  const b = big.getContext("2d")!;
  b.imageSmoothingEnabled = true; b.imageSmoothingQuality = "high";
  b.drawImage(small, 0, 0, w * UP, h * UP);
  return big;
}
