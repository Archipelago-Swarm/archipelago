import type { TerrainGrid } from "@archipelago/contracts";

export type MapStyle = "natural" | "topo";

const BASE = [[150, 178, 100], [64, 120, 60], [26, 82, 44]]; // grass, forest, jungle
// Brand kit (brand-kit/src/tokens.ts): black 60 / stone+white 30 / orange <=10 accent / grey for labels.
const BLACK = [10, 10, 10], STONE = [237, 231, 223], ORANGE = [244, 123, 60], GREY = [138, 138, 138];
// Texels per cell: the grid is only a few dozen cells wide so the detail below is synthesised, deterministically.
// Capped at ~1.1 Mpx so building it (once per run) stays well under a second even on the 80x45 demo world.
const upFor = (t: TerrainGrid) => Math.max(6, Math.min(24, Math.floor(Math.sqrt(1.1e6 / (t.size * t.height)))));
let zCache: { key: string; Z: Float32Array; zMin: number; zMax: number } | null = null; // elevation field is shared by both map styles
const DETAIL_M = 45; // amplitude of fine elevation noise (m), on top of the interpolated sim elevation
export const CONTOUR_M = 50, INDEX_EVERY = 5; // minor contour interval and how many minors per bold, labelled index contour
const HYPSO: [number, number[]][] = [ // brand monochrome relief ramp: black lowlands rising to stone peaks (fraction of the map's relief)
  [0, [40, 39, 37]], [0.25, [72, 70, 65]], [0.5, [112, 108, 100]], [0.75, [156, 151, 141]], [0.93, [206, 200, 190]], [1, [237, 231, 223]],
];
const MONO = "Consolas, 'Courier New', monospace";
const ramp = (f: number) => {
  f = Math.max(0, Math.min(1, f));
  let i = 1; while (i < HYPSO.length - 1 && HYPSO[i][0] < f) i++;
  const [f0, c0] = HYPSO[i - 1], [f1, c1] = HYPSO[i], k = (f - f0) / (f1 - f0);
  return c0.map((v, j) => v + (c1[j] - v) * k);
};

const hash = (x: number, y: number, s: number) => {
  let h = (Math.imul(x, 374761393) + Math.imul(y, 668265263) + Math.imul(s, 2246822519)) | 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967295;
};
const vnoise = (x: number, y: number, s: number) => {
  const ix = Math.floor(x), iy = Math.floor(y);
  let fx = x - ix, fy = y - iy;
  fx = fx * fx * (3 - 2 * fx); fy = fy * fy * (3 - 2 * fy);
  const a = hash(ix, iy, s), b = hash(ix + 1, iy, s), c = hash(ix, iy + 1, s), d = hash(ix + 1, iy + 1, s);
  return a + (b - a) * fx + (c - a) * fy + (a - b - c + d) * fx * fy;
};
const fbm = (x: number, y: number, s: number, oct: number) => {
  let t = 0, n = 0, a = 1;
  for (let o = 0; o < oct; o++, a *= 0.5, x *= 2, y *= 2) { t += a * vnoise(x, y, s + o); n += a; }
  return t / n;
};
const cubic = (p0: number, p1: number, p2: number, p3: number, t: number) => // Catmull-Rom
  p1 + 0.5 * t * (p2 - p0 + t * (2 * p0 - 5 * p1 + 4 * p2 - p3 + t * (3 * (p1 - p2) + p3 - p0)));

// Smooth bicubic elevation (m) at a point given in cell units; shared by the texture and the 2.5D mesh so they line up.
export function sampleElev(t: TerrainGrid, u: number, v: number): number {
  const w = t.size, h = t.height, cl = (a: number, m: number) => Math.min(m - 1, Math.max(0, a));
  const e = (x: number, y: number) => t.elev_m[cl(y, h) * w + cl(x, w)];
  const gx = u - 0.5, gy = v - 0.5, ix = Math.floor(gx), iy = Math.floor(gy), fx = gx - ix, fy = gy - iy;
  const row = (dy: number) => cubic(e(ix - 1, iy + dy), e(ix, iy + dy), e(ix + 1, iy + dy), e(ix + 2, iy + dy), fx);
  return cubic(row(-1), row(0), row(1), row(2), fy);
}

/** Elevation (m) with the same fractal detail the GPU shader adds (shader also adds finer octaves when zoomed in). */
export function detailElev(t: TerrainGrid, u: number, v: number): number {
  const ridged = 1 - Math.abs(2 * fbm(u * 1.6, v * 1.6, 91, 5) - 1);
  return sampleElev(t, u, v) + DETAIL_M * (fbm(u * 3, v * 3, 7, 5) - 0.5) + 0.6 * DETAIL_M * (ridged - 0.5);
}

// Fallback (no WebGL) bitmap terrain. Static, fully lit terrain. "natural" is shaded imagery; "topo" is a military-style map: hypsometric tints, minor and
// bold index contours with elevation labels, and a 1 km grid. Fog is a separate overlay.
function* buildSteps(t: TerrainGrid, cellM: number, style: MapStyle): Generator<void, HTMLCanvasElement> { // yields once per texel row so callers can time-slice

  const UP = upFor(t), w = t.size, h = t.height, W = w * UP, H = h * UP;
  const cl = (v: number, m: number) => Math.min(m - 1, Math.max(0, v));
  const wm = (u: number) => u / UP; // texel -> cell units
  // Bicubic elevation + fractal detail: the sim grid is coarse, so this is what makes ridges/gullies look real.
  const zKey = `${w}x${h}:${UP}:${t.elev_m.reduce((a, b, i) => a + b * ((i % 7) + 1), 0)}`;
  if (zCache?.key !== zKey) {
    const Z = new Float32Array(W * H);
    let zMin = Infinity, zMax = -Infinity;
    for (let py = 0; py < H; py++) {
      yield;
      for (let px = 0; px < W; px++) {
      const z = sampleElev(t, wm(px), wm(py));
      const ridged = 1 - Math.abs(2 * fbm(wm(px) * 1.6, wm(py) * 1.6, 91, 5) - 1);
      const zz = z + DETAIL_M * (fbm(wm(px) * 3, wm(py) * 3, 7, 5) - 0.5) + 0.6 * DETAIL_M * (ridged - 0.5);
      Z[py * W + px] = zz; if (zz < zMin) zMin = zz; if (zz > zMax) zMax = zz;
      }
    }
    zCache = { key: zKey, Z, zMin, zMax };
  }
  const { Z, zMin, zMax } = zCache;
  const canvas = document.createElement("canvas");
  canvas.width = W; canvas.height = H;
  const g = canvas.getContext("2d")!, img = g.createImageData(W, H), d = img.data;
  const zAt = (x: number, y: number) => Z[cl(y, H) * W + cl(x, W)];
  const topo = style === "topo", LBL = 380; // one elevation label per LBL x LBL block, on the index contour nearest its centre
  const lbl = new Map<number, { x: number; y: number; ang: number; lvl: number; dd: number }>();
  for (let py = 0; py < H; py++) {
  yield;
  for (let px = 0; px < W; px++) {
    const u = wm(px), v = wm(py);
    // domain-warped nearest-cell biome so biome borders are organic rather than square
    const bx = cl(Math.floor(u + 0.8 * (fbm(u * 2, v * 2, 3, 3) - 0.5)), w), by = cl(Math.floor(v + 0.8 * (fbm(u * 2, v * 2, 4, 3) - 0.5)), h);
    const ci = by * w + bx, bio = +t.biome[ci] || 0, base = BASE[bio] ?? BASE[0];
    const veg = (t.veg_pct?.[ci] ?? 50) / 100;
    const z = Z[py * W + px];
    // hillshade from the north-west, scaled so relief reads at map scale
    const dzx = (zAt(px + 1, py) - zAt(px - 1, py)) / (2 * cellM / UP), dzy = (zAt(px, py + 1) - zAt(px, py - 1)) / (2 * cellM / UP);
    const shade = Math.max(-0.7, Math.min(0.7, 2.2 * (-dzx - dzy) * 0.7071));
    const o = (py * W + px) * 4;
    d[o + 3] = 255;
    if (topo) {
      const c = ramp((z - zMin) / (zMax - zMin + 1e-9)), k = 0.82 + 0.95 * shade;
      // forest / jungle read as denser stipple, not a colour: the palette stays black / stone / orange
      const sp = bio ? (vnoise(u * 30, v * 30, 61) - 0.5) * (0.25 + 0.5 * veg) * (bio === 2 ? 1.3 : 1) : 0, tex = 1 + 0.08 * (fbm(u * 14, v * 14, 40, 2) - 0.5) + sp;
      const col = [0, 1, 2].map((ch) => Math.max(0, Math.min(255, c[ch] * k * tex)));
      // contour lines: coverage from the distance (in texels) to the nearest contour level
      const gpx = Math.hypot(zAt(px + 1, py) - zAt(px - 1, py), zAt(px, py + 1) - zAt(px, py - 1)) / 2; // m per texel
      const n = z / CONTOUR_M, lvl = Math.round(n), isIndex = ((lvl % INDEX_EVERY) + INDEX_EVERY) % INDEX_EVERY === 0;
      if (gpx > 0.05) {
        const dist = (Math.abs(n - lvl) * CONTOUR_M) / gpx, cov = Math.max(0, Math.min(1, (isIndex ? 1.5 : 0.75) + 0.5 - dist)) * (isIndex ? 0.8 : 0.34);
        const lc = 0.299 * col[0] + 0.587 * col[1] + 0.114 * col[2] > 120 ? BLACK : STONE; // dark lines on bright ground, stone lines on dark
        for (let ch = 0; ch < 3; ch++) col[ch] = col[ch] * (1 - cov) + lc[ch] * cov;
        if (isIndex && dist < 0.8) { // label candidate
          const key = Math.floor(px / LBL) * 1000 + Math.floor(py / LBL), dd = Math.hypot(px % LBL - LBL / 2, py % LBL - LBL / 2), cur = lbl.get(key);
          if (!cur || dd < cur.dd) lbl.set(key, { x: px, y: py, ang: Math.atan2(zAt(px + 1, py) - zAt(px - 1, py), -(zAt(px, py + 1) - zAt(px, py - 1))), lvl: lvl * CONTOUR_M, dd });
        }
      }
      d[o] = col[0]; d[o + 1] = col[1]; d[o + 2] = col[2];
      continue;
    }
    const alt = Math.min(1, Math.max(0, z / 550));
    let k = 0.95 + 0.4 * alt + shade;
    // ground texture + canopy speckle (denser, darker in forest/jungle)
    const tex = fbm(u * 14, v * 14, 40, 3) - 0.5, speck = vnoise(u * 38, v * 38, 55) - 0.5;
    k *= 1 + 0.35 * tex + (0.3 + 0.5 * veg) * 0.45 * speck * (bio ? 1 : 0.5);
    const c = Math.abs(((z % CONTOUR_M) + CONTOUR_M) % CONTOUR_M - CONTOUR_M / 2); // distance to a contour band
    if (c > CONTOUR_M / 2 - 0.9) k *= 0.88;
    const rock = Math.max(0, Math.min(1, (Math.hypot(dzx, dzy) - 0.25) * 2)); // steep faces go grey-brown
    for (let ch = 0; ch < 3; ch++) d[o + ch] = Math.max(0, Math.min(255, (base[ch] * (1 - rock) + [120, 108, 96][ch] * rock) * k));
  }
  }
  g.putImageData(img, 0, 0);
  if (topo) {
    g.save(); // 1 km grid with labels, then elevation labels on the index contours
    const step = (1000 / cellM) * UP;
    g.strokeStyle = "rgba(138,138,138,0.3)"; g.lineWidth = 1.2; g.fillStyle = "rgba(138,138,138,0.95)"; g.font = `bold 20px ${MONO}`; // graticule in brand grey
    g.beginPath();
    for (let k = 1; k * step < W; k++) { g.moveTo(k * step, 0); g.lineTo(k * step, H); g.fillText(String(k), k * step + 4, 20); }
    for (let k = 1; k * step < H; k++) { g.moveTo(0, k * step); g.lineTo(W, k * step); g.fillText(String(k), 4, k * step - 4); }
    g.stroke();
    g.font = `bold 22px ${MONO}`; g.textAlign = "center"; g.textBaseline = "middle"; g.lineJoin = "round";
    for (const l of lbl.values()) {
      if (l.x < 30 || l.y < 30 || l.x > W - 30 || l.y > H - 30) continue;
      let a = l.ang; if (a > Math.PI / 2) a -= Math.PI; else if (a < -Math.PI / 2) a += Math.PI; // keep text upright
      g.save(); g.translate(l.x, l.y); g.rotate(a);
      g.strokeStyle = "rgba(10,10,10,0.9)"; g.lineWidth = 6; g.strokeText(String(l.lvl), 0, 0);
      g.fillStyle = "#EDE7DF"; g.fillText(String(l.lvl), 0, 0); g.restore();
    }
    g.restore();
  }
  return canvas;
}

export function buildTerrainBase(t: TerrainGrid, cellM: number, style: MapStyle = "natural"): HTMLCanvasElement {
  const it = buildSteps(t, cellM, style);
  for (;;) { const r = it.next(); if (r.done) return r.value; }
}

// Same result, built in ~6 ms slices between frames so the page never freezes.
export function buildTerrainBaseAsync(t: TerrainGrid, cellM: number, style: MapStyle = "natural"): Promise<HTMLCanvasElement> {
  const it = buildSteps(t, cellM, style);
  return new Promise((resolve) => {
    const ch = new MessageChannel(), next = () => ch.port2.postMessage(0); // a macrotask without timer clamping/background throttling
    const tick = () => {
      const end = performance.now() + 6;
      for (;;) { const r = it.next(); if (r.done) return resolve(r.value); if (performance.now() > end) break; }
      next();
    };
    ch.port1.onmessage = tick; next();
  });
}

// Unexplored ground: near-black fog, brand-style diagonal hatching, and a dashed orange frontier where explored meets unexplored.
// Built from the per-cell observed mask smoothed up to FOG_PX texels per cell; only rebuilt when the observed set changes.
const FOG_PX = 8;
export function buildFogOverlay(t: TerrainGrid): HTMLCanvasElement {
  const w = t.size, h = t.height, W = w * FOG_PX, H = h * FOG_PX;
  const small = document.createElement("canvas"); small.width = w; small.height = h;
  const sg = small.getContext("2d")!, simg = sg.createImageData(w, h);
  const obs = (x: number, y: number) => (t.observed[Math.min(h - 1, Math.max(0, y)) * w + Math.min(w - 1, Math.max(0, x))] === "1" ? 1 : 0);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { // alpha = how unexplored this cell is (3x3 softened)
    let a = 0; for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) a += obs(x + dx, y + dy);
    simg.data[(y * w + x) * 4 + 3] = 255 * (1 - a / 9);
  }
  sg.putImageData(simg, 0, 0);
  const c = document.createElement("canvas"); c.width = W; c.height = H;
  const g = c.getContext("2d", { willReadFrequently: true })!;
  g.imageSmoothingEnabled = true; g.imageSmoothingQuality = "high"; g.drawImage(small, 0, 0, W, H);
  const m = g.getImageData(0, 0, W, H), d = m.data, A = (x: number, y: number) => d[(Math.min(H - 1, Math.max(0, y)) * W + Math.min(W - 1, Math.max(0, x))) * 4 + 3] / 255;
  const out = g.createImageData(W, H), o = out.data;
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const i = (y * W + x) * 4, a = d[i + 3] / 255; // 0 explored .. 1 unexplored
    let r = BLACK[0], gg = BLACK[1], b = BLACK[2], al = 0.92 * Math.min(1, a * 1.6);
    if (a > 0.5 && ((x + y) % 16) < 2.2) { const k = 0.12 * a; r += (GREY[0] - r) * k; gg += (GREY[1] - gg) * k; b += (GREY[2] - b) * k; } // "/" hatch: lighter lines in the fog, faint so it never fights the frontier
    const gr = (Math.abs(A(x + 1, y) - A(x - 1, y)) + Math.abs(A(x, y + 1) - A(x, y - 1))) / 2; // frontier = a == 0.5 contour
    if (gr > 0.002 && ((x + y) % 18) < 11) {
      const cov = Math.max(0, Math.min(1, 1.3 - Math.abs(a - 0.5) / gr));
      if (cov > 0) { r = r * (1 - cov) + ORANGE[0] * cov; gg = gg * (1 - cov) + ORANGE[1] * cov; b = b * (1 - cov) + ORANGE[2] * cov; al = Math.max(al, cov); }
    }
    o[i] = r; o[i + 1] = gg; o[i + 2] = b; o[i + 3] = al * 255;
  }
  g.putImageData(out, 0, 0);
  return c;
}
