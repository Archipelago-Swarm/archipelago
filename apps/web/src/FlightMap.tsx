import { useEffect, useRef, useState } from "react";
import type { WorldSnapshot } from "@archipelago/contracts";
import {
  PoseBuffer, bearingDeg, boundsOf, fitZoom, intersects, screenToWorld, stepCamera, visibleBounds, wheelZoom, worldToScreen,
  type Anchor, type Bounds, type Camera, type Pose2,
} from "./camera";
import type { Panels } from "./live";
import type { Spotlight } from "./demoScriptController";
import { AGL_M, buildViewshed, viewshedCanvas } from "./viewshed";
import { buildFogOverlay, buildTerrainBaseAsync, sampleElev, CONTOUR_M, INDEX_EVERY, type MapStyle } from "./terrainTexture";
import { Terrain3D, fogMask, ground3, makeCam3, project3, viewshedRG, type Cam3 } from "./terrain3d";
import { contourLabels, drawTopoLabels, type ContourLabel } from "./topoLabels";

// Brand kit palette (brand-kit/src/tokens.ts): black 60 / stone 30 / orange <=10 accent, grey for labels, Consolas for telemetry.
const BR = { bg: "#0A0A0A", surface: "#141414", border: "#333333", stone: "#EDE7DF", orange: "#F47B3C", grey: "#8A8A8A" };
const MONO = "Consolas, 'Courier New', monospace";
const TRAIL_MAX = 600, TRAIL_STEP_M = 30, PULSE_MS = 3000;
const LOD_ICON = 2.5, LOD_CLOSE = 10; // zoom relative to the fit-world zoom
// 2.5D vertical exaggeration: relief is small next to a tens-of-km map, so heights are stretched until the tallest peak is ~18% of the map width
const exFor = (widthM: number, t?: { elev_m: number[] } | null) => (t ? Math.round(Math.min(4, Math.max(1, (0.18 * widthM) / (t.elev_m.reduce((a, b) => Math.max(a, b), 1)))) * 10) / 10 : 1);

// Camera pitch (degrees above the horizon) follows zoom: zoomed out is near top-down, zoomed in is a low oblique view.
const PITCH_FAR = 84, PITCH_NEAR = 22, ZR_NEAR = 12;
const pitchFor = (zr: number) => {
  const t = Math.min(1, Math.max(0, Math.log(Math.max(zr, 1)) / Math.log(ZR_NEAR))), k = t * t * (3 - 2 * t);
  return PITCH_FAR + (PITCH_NEAR - PITCH_FAR) * k;
};

let placeholder: HTMLCanvasElement | null = null; // 1x1 dark stand-in while the terrain texture is still being built
const PLACEHOLDER = () => placeholder ??= (() => { const c = document.createElement("canvas"); c.width = c.height = 1; const x = c.getContext("2d")!; x.fillStyle = BR.surface; x.fillRect(0, 0, 1, 1); return c; })();
type Swatch = (g: CanvasRenderingContext2D, x: number, y: number) => void; // 12x12 box at (x, y)
const hatchSwatch = (line: string, fill: string, dir: 1 | -1): Swatch => (g, x, y) => {
  g.save(); g.beginPath(); g.rect(x, y, 12, 12); g.clip(); g.fillStyle = fill; g.fillRect(x, y, 12, 12);
  g.strokeStyle = line; g.lineWidth = 1.2; g.beginPath();
  for (let k = -12; k <= 12; k += 4) { g.moveTo(x + k, dir > 0 ? y + 12 : y); g.lineTo(x + k + 12, dir > 0 ? y : y + 12); }
  g.stroke(); g.restore();
};
const LEGEND: [Swatch, string][] = [
  [(g, x, y) => { g.fillStyle = "rgba(237,231,223,0.35)"; g.fillRect(x, y, 12, 12); }, "IN VIEW NOW"],
  [hatchSwatch("rgba(138,138,138,0.9)", "#0A0A0A", 1), "UNEXPLORED"],
  [(g, x, y) => { g.fillStyle = "#1c1c1c"; g.fillRect(x, y, 12, 12); g.strokeStyle = BR.orange; g.lineWidth = 1.5; g.setLineDash([3, 2]); g.beginPath(); g.moveTo(x, y + 6); g.lineTo(x + 12, y + 6); g.stroke(); g.setLineDash([]); }, "EXPLORED EDGE"],
  [hatchSwatch("rgba(244,123,60,0.9)", "rgba(244,123,60,0.18)", -1), "HIDDEN BY TERRAIN"],
];
function legend(g: CanvasRenderingContext2D, notes: string[]) {
  g.save(); g.font = `10px ${MONO}`; g.textBaseline = "middle";
  const hgt = (LEGEND.length + notes.length) * 18 + 14;
  g.fillStyle = "rgba(20,20,20,0.92)"; g.fillRect(10, 40, 212, hgt); g.strokeStyle = BR.border; g.lineWidth = 1; g.strokeRect(10.5, 40.5, 211, hgt - 1);
  g.fillStyle = BR.orange; g.fillRect(10, 40, 212, 2); // card accent
  LEGEND.forEach(([sw, label], i) => {
    const y = 40 + 17 + i * 18;
    sw(g, 18, y - 6); g.strokeStyle = "rgba(237,231,223,0.35)"; g.lineWidth = 1; g.strokeRect(18.5, y - 5.5, 11, 11);
    g.fillStyle = BR.stone; g.fillText(label, 38, y);
  });
  g.fillStyle = BR.grey; notes.forEach((n, i) => g.fillText(n.toUpperCase(), 18, 40 + 17 + (LEGEND.length + i) * 18));
  g.restore();
}
function jet(g: CanvasRenderingContext2D, x: number, y: number, heading: number, size: number, color: string, ring: boolean) {
  g.save();
  g.translate(x, y);
  g.rotate(heading); // sprite points along +x, so heading 0 = east
  g.beginPath(); // generic delta-wing silhouette
  g.moveTo(size, 0); g.lineTo(-size * 0.75, size * 0.8); g.lineTo(-size * 0.35, 0); g.lineTo(-size * 0.75, -size * 0.8); g.closePath();
  g.fillStyle = color; g.fill();
  g.strokeStyle = BR.bg; g.lineWidth = 1; g.stroke();
  if (ring) { g.beginPath(); g.arc(0, 0, size * 1.5, 0, 2 * Math.PI); g.strokeStyle = BR.orange; g.lineWidth = 1.5; g.stroke(); }
  g.restore();
}

const niceLen = (m: number) => [50, 100, 200, 500, 1000, 2000, 5000, 10000].find((n) => n >= m) ?? 20000;
const km = (m: number) => `${(m / 1000).toFixed(2)} km`;

export function FlightMap({ snap, panels, height, instant = false, getPoses, focus, spotlight }: { snap: WorldSnapshot; panels?: Panels; height: string; instant?: boolean; getPoses?: () => Record<string, Pose2> | null; focus?: { ids: string[]; n: number }; spotlight?: Spotlight }) {
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const snapRef = useRef(snap), panelsRef = useRef(panels), instantRef = useRef(instant), spotRef = useRef(spotlight);
  const buf = useRef(new PoseBuffer());
  const fog = useRef<HTMLCanvasElement | null>(null), fogKey = useRef(""), vsTex = useRef<HTMLCanvasElement | null>(null), vsKey = useRef("");
  const texCache = useRef<Record<string, HTMLCanvasElement>>({}), texPending = useRef<Record<string, boolean>>({}), texKey = useRef(""), glCv = useRef<HTMLCanvasElement>(null), gl3 = useRef<Terrain3D | null>(null), glFail = useRef(false);
  const glS = useRef({ terr: "", fog: "", vs: "" }), labels = useRef<{ list: ContourLabel[] }>({ list: [] }); // what the GPU currently holds
  const proj = useRef<Record<string, [number, number]>>({}), glScaleRef = useRef(Math.min(window.devicePixelRatio || 1, 1.5));
  const [mapStyle, setMapStyle] = useState<MapStyle>("topo"), [view, setView] = useState<"2d" | "3d">("3d"), tzRef = useRef(0); // eased elevation under the screen centre: the 2.5D camera orbits this point
  const styleRef = useRef(mapStyle), viewRef = useRef(view);
  styleRef.current = mapStyle; viewRef.current = view;
  const trails = useRef<Record<string, [number, number, number][]>>({}); // x, y, ground elevation (cached at push time)
  const trailKey = useRef<string | null>(null);
  const cam = useRef<Camera>({ x: 0, y: 0, zoom: 0.04 }), tgt = useRef<Camera>({ x: 0, y: 0, zoom: 0.04 });
  const anchor = useRef<Anchor | null>(null);
  const fit = useRef({ zoom: 0.04, done: false });
  const sel = useRef<string | null>(null), follow = useRef(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [following, setFollowing] = useState(false);
  const [, bump] = useState(0);
  const posesRef = useRef(getPoses);
  snapRef.current = snap; panelsRef.current = panels; instantRef.current = instant; spotRef.current = spotlight; posesRef.current = getPoses;

  const world = snap.world;
  const sampled = useRef<Record<string, Pose2>>({});

  useEffect(() => { // new snapshot -> interpolation buffer
    const poses: Record<string, Pose2> = {};
    for (const [id, p] of Object.entries(snap.poses)) poses[id] = { x: p.x, y: p.y, heading: p.heading_rad ?? 0, speed: p.speed_mps ?? 0 };
    buf.current.push(snap.run_id, snap.sim_tick, poses, performance.now(), instantRef.current);
  }, [snap]);

  useEffect(() => { // timeline event click: centre the camera on the involved nodes
    if (!focus?.n) return;
    const ps = focus.ids.map((id) => sampled.current[id]).filter(Boolean);
    if (!ps.length) return;
    follow.current = false; setFollowing(false); anchor.current = null;
    tgt.current = { x: ps.reduce((a, p) => a + p.x, 0) / ps.length, y: ps.reduce((a, p) => a + p.y, 0) / ps.length, zoom: Math.max(tgt.current.zoom, fit.current.zoom * LOD_ICON) };
  }, [focus?.n]);

  const doFit = () => {
    const el = box.current; if (!el || !world) return;
    const z = fitZoom({ w: el.clientWidth, h: el.clientHeight }, world.width_m, world.height_m, viewRef.current === "3d" && world.terrain ? 0.8 : 0.92); // perspective + relief need room
    fit.current = { zoom: z, done: true };
    tgt.current = { x: world.width_m / 2, y: world.height_m / 2, zoom: z };
    anchor.current = null; follow.current = false; setFollowing(false);
  };

  useEffect(() => {
    const el = box.current, cv = canvas.current;
    if (!el || !cv) return;
    const g = cv.getContext("2d");
    if (!g) return;
    let raf = 0, last = performance.now(), W = 0, H = 0, dragging: { x: number; y: number; moved: number } | null = null;
    const shapeBox = new Map<string, Bounds>(), shapeZ = new Map<string, number[]>();

    // The ground shader costs per pixel, so the GL resolution adapts: it backs off when frames run long and recovers when cheap.
    const glScale = glScaleRef;
    let ema = 16, nFrames = 0;
    const governor = (rawDt: number) => {
      if (rawDt > 250) return; // tab was hidden / paused
      ema += (rawDt - ema) * 0.1;
      if (++nFrames % 45) return;
      const max = Math.min(window.devicePixelRatio || 1, 1.5);
      const next = ema > 26 ? glScale.current * 0.8 : ema < 15 ? glScale.current * 1.15 : glScale.current;
      const clamped = Math.max(0.5, Math.min(max, next));
      if (Math.abs(clamped - glScale.current) > 0.01) { glScale.current = clamped; sizeGL(); }
    };
    const sizeGL = () => {
      const gc = glCv.current; if (!gc) return;
      const dpr = glScale.current;
      gc.width = Math.max(1, Math.round(W * dpr)); gc.height = Math.max(1, Math.round(H * dpr)); gc.style.width = `${W}px`; gc.style.height = `${H}px`;
    };
    const ensureGL = () => {
      if (!gl3.current && !glFail.current) {
        try { gl3.current = new Terrain3D(glCv.current!); sizeGL(); } catch { glFail.current = true; viewRef.current = "2d"; setView("2d"); }
      }
      return gl3.current;
    };
    const useGL = () => !!gl3.current && !!snapRef.current.world?.terrain;
    const cam3 = (c: Camera): Cam3 | null => {
      const w = snapRef.current.world, terr = w?.terrain; if (!w || !terr || !W) return null;
      const flat = viewRef.current !== "3d"; // 2D map = the same renderer looking straight down at flat ground
      return makeCam3(c, W, H, flat ? Math.PI / 2 : (pitchFor(c.zoom / fit.current.zoom) * Math.PI) / 180, flat ? 0 : exFor(w.width_m, terr), flat ? 0 : tzRef.current, (x, y) => sampleElev(terr, x / w.cell_m, y / w.cell_m));
    };
    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      W = el.clientWidth; H = el.clientHeight;
      cv.width = Math.max(1, Math.round(W * dpr)); cv.height = Math.max(1, Math.round(H * dpr));
      cv.style.width = `${W}px`; cv.style.height = `${H}px`;
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      sizeGL();
      if (!fit.current.done || (!dragging && tgt.current.zoom <= fit.current.zoom * 1.001)) { doFit(); cam.current = { ...tgt.current }; }
    };
    const ro = new ResizeObserver(resize); ro.observe(el); resize();

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = cv.getBoundingClientRect(), sx = e.clientX - r.left, sy = e.clientY - r.top, v = { w: W, h: H };
      const dy = e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY;
      tgt.current = { ...tgt.current, zoom: wheelZoom(tgt.current.zoom, dy, fit.current.zoom * 0.5, 4) };
      if (!follow.current) { const k = useGL() ? cam3(cam.current) : null, [wx, wy] = k ? ground3(k, sx, sy, tzRef.current) : screenToWorld(cam.current, v, sx, sy); anchor.current = { wx, wy, sx, sy }; }
    };
    const onDown = (e: PointerEvent) => { cv.setPointerCapture(e.pointerId); dragging = { x: e.clientX, y: e.clientY, moved: 0 }; };
    const onMove = (e: PointerEvent) => {
      if (!dragging) return;
      const dx = e.clientX - dragging.x, dy = e.clientY - dragging.y, r = cv.getBoundingClientRect(), x0 = dragging.x - r.left, y0 = dragging.y - r.top;
      dragging.x = e.clientX; dragging.y = e.clientY; dragging.moved += Math.abs(dx) + Math.abs(dy);
      if (dragging.moved < 4) return;
      anchor.current = null; follow.current = false; setFollowing(false); // dragging breaks follow
      const z = cam.current.zoom, k = useGL() ? cam3(cam.current) : null;
      if (k) { // grab the ground: the point under the pointer stays under it, with perspective
        const [ax, ay] = ground3(k, x0, y0, tzRef.current), [bx, by] = ground3(k, x0 + dx, y0 + dy, tzRef.current);
        cam.current = { ...cam.current, x: cam.current.x + ax - bx, y: cam.current.y + ay - by };
      } else cam.current = { ...cam.current, x: cam.current.x - dx / z, y: cam.current.y - dy / z };
      tgt.current = { ...tgt.current, x: cam.current.x, y: cam.current.y, zoom: tgt.current.zoom };
    };
    const onUp = (e: PointerEvent) => {
      const d = dragging; dragging = null;
      if (!d || d.moved >= 4) return;
      const r = cv.getBoundingClientRect(), sx = e.clientX - r.left, sy = e.clientY - r.top;
      let best: string | null = null, bd = 28;
      for (const [id, [px, py]] of Object.entries(proj.current)) {
        const dd = Math.hypot(px - sx, py - sy);
        if (dd < bd) { bd = dd; best = id; }
      }
      sel.current = best; setSelected(best);
      if (!best) { follow.current = false; setFollowing(false); }
    };
    cv.addEventListener("wheel", onWheel, { passive: false });
    cv.addEventListener("pointerdown", onDown); cv.addEventListener("pointermove", onMove);
    const onCancel = () => { dragging = null; };
    cv.addEventListener("pointerup", onUp); cv.addEventListener("pointercancel", onCancel);

    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      const rawDt = now - last, dt = Math.min(100, rawDt); last = now; governor(rawDt);
      const s = snapRef.current, w = s.world, v = { w: W, h: H };
      if (!w || !W) return;
      const poses = posesRef.current?.() ?? buf.current.sample(now);
      sampled.current = poses;
      if (follow.current && sel.current && poses[sel.current]) { tgt.current = { ...tgt.current, x: poses[sel.current].x, y: poses[sel.current].y }; }
      const terr = w.terrain, gl = !!terr && !!ensureGL(), m3 = gl && viewRef.current === "3d"; // gl: GPU renderer (2D or 2.5D); m3: tilted view
      cam.current = stepCamera(cam.current, tgt.current, v, gl ? null : anchor.current, dt);
      if (gl) {
        tzRef.current += ((m3 ? sampleElev(terr!, cam.current.x / w.cell_m, cam.current.y / w.cell_m) : 0) - tzRef.current) * Math.min(1, dt / 120);
        const A = anchor.current;
        if (A) for (let i = 0; i < 3; i++) { // perspective + changing pitch: re-pin the world point under the cursor
          const [gx, gy] = ground3(cam3(cam.current)!, A.sx, A.sy, tzRef.current);
          cam.current = { ...cam.current, x: cam.current.x + A.wx - gx, y: cam.current.y + A.wy - gy };
        }
      }
      if (anchor.current) tgt.current = { ...tgt.current, x: cam.current.x, y: cam.current.y };
      if (Math.abs(tgt.current.zoom - cam.current.zoom) < 1e-9) anchor.current = null;
      const c = cam.current, zr = c.zoom / fit.current.zoom, ex = exFor(w.width_m, terr), k3d = gl ? cam3(c)! : null;
      const vb = gl ? { x0: -1e9, y0: -1e9, x1: 1e9, y1: 1e9 } : visibleBounds(c, v, 40 / c.zoom);
      const gz = (x: number, y: number) => (m3 ? sampleElev(terr!, x / w.cell_m, y / w.cell_m) : 0);
      const S = (x: number, y: number, z = 0) => (k3d ? project3(k3d, x, y, z) : worldToScreen(c, v, x, y));
      const Sg = (x: number, y: number) => S(x, y, gz(x, y)), Sa = (x: number, y: number) => S(x, y, gz(x, y) + AGL_M); // ground point / aircraft point
      const ring = (x: number, y: number, r: number) => { // a circle lying on the ground: an arc in 2D, a projected polygon in perspective
        g.beginPath();
        if (!k3d) { const [px, py] = worldToScreen(c, v, x, y); g.arc(px, py, r * c.zoom, 0, 2 * Math.PI); return; }
        const z = gz(x, y);
        for (let i = 0; i <= 36; i++) { const a = (i / 36) * 2 * Math.PI, [px, py] = project3(k3d, x + Math.cos(a) * r, y + Math.sin(a) * r, z); if (i) g.lineTo(px, py); else g.moveTo(px, py); }
      };

      if (trailKey.current !== s.run_id) { trails.current = {}; trailKey.current = s.run_id; }
      for (const [id, p] of Object.entries(poses)) {
        const t = (trails.current[id] ??= []), l = t[t.length - 1];
        if (!l || Math.hypot(l[0] - p.x, l[1] - p.y) > TRAIL_STEP_M) { t.push([p.x, p.y, terr ? sampleElev(terr, p.x / w.cell_m, p.y / w.cell_m) : 0]); if (t.length > TRAIL_MAX) t.shift(); }
      }

      const cells = terr ? Object.values(poses).map((p) => [Math.floor(p.x / w.cell_m), Math.floor(p.y / w.cell_m)] as [number, number]) : [];
      const tk = terr ? terr.biome + w.cell_m : "", vk = cells.join(";") + w.sensor_radius_m; // keys for what is cached on the GPU / in bitmaps
      if (terr && gl) { // all ground detail is drawn per pixel on the GPU (resolution independent); only small masks are uploaded
        const T = gl3.current!, gs = glS.current;
        if (gs.terr !== tk) { T.setTerrain(terr, w.cell_m); gs.terr = tk; gs.fog = gs.vs = ""; labels.current = { list: contourLabels(terr, w.cell_m) }; }
        if (gs.fog !== terr.observed) { T.setFog(fogMask(terr)); gs.fog = terr.observed; }
        if (gs.vs !== vk) { T.setViewshed(viewshedRG(buildViewshed(terr, cells, Math.round(w.sensor_radius_m / w.cell_m)))); gs.vs = vk; } // terrain-driven line of sight
        T.draw(k3d!, styleRef.current);
        g.clearRect(0, 0, W, H);
        if (styleRef.current === "topo") drawTopoLabels(g, k3d!, labels.current.list, { w: w.width_m, h: w.height_m }, gz, (x, y) => terr.observed[Math.floor(y / w.cell_m) * terr.size + Math.floor(x / w.cell_m)] === "1"); // vector text, sharp at any zoom
      } else { // no WebGL: baked bitmap fallback
        let base: HTMLCanvasElement | null = null, vsc: HTMLCanvasElement | null = null;
        if (terr) {
          if (texKey.current !== tk) { texKey.current = tk; texCache.current = {}; texPending.current = {}; fogKey.current = ""; }
          const st = styleRef.current, cache = texCache.current;
          if (!cache[st] && !texPending.current[st]) { texPending.current[st] = true; buildTerrainBaseAsync(terr, w.cell_m, st).then((cv) => { cache[st] = cv; }); }
          base = cache[st] ?? cache[st === "topo" ? "natural" : "topo"] ?? PLACEHOLDER(); // keep showing the other style while this one builds
          if (fogKey.current !== terr.observed) { fogKey.current = terr.observed; fog.current = buildFogOverlay(terr); }
          if (vsKey.current !== vk) { vsKey.current = vk; vsTex.current = viewshedCanvas(terr, buildViewshed(terr, cells, Math.round(w.sensor_radius_m / w.cell_m))); }
          vsc = vsTex.current;
        }
        g.fillStyle = BR.bg; g.fillRect(0, 0, W, H);
        const [ox, oy] = S(0, 0), [ex2, ey2] = S(w.width_m, w.height_m);
        g.fillStyle = BR.surface; g.fillRect(ox, oy, ex2 - ox, ey2 - oy);
        if (base) {
          g.imageSmoothingEnabled = true; g.imageSmoothingQuality = "high";
          g.drawImage(base, ox, oy, ex2 - ox, ey2 - oy); g.drawImage(fog.current!, ox, oy, ex2 - ox, ey2 - oy); g.drawImage(vsc!, ox, oy, ex2 - ox, ey2 - oy);
        }
        g.strokeStyle = BR.border; g.lineWidth = 1; g.strokeRect(ox, oy, ex2 - ox, ey2 - oy);
      }

      for (const sh of w.shapes ?? []) { // revealed terrain polygons, culled to the viewport
        const key = sh.id + ":" + sh.points.length;
        let b = shapeBox.get(key); if (!b) { b = boundsOf(sh.points as [number, number][]); shapeBox.set(key, b); }
        if (!intersects(b, vb)) continue;
        g.beginPath();
        let zs = shapeZ.get(key); if (!zs) { zs = (sh.points as [number, number][]).map(([x, y]) => (terr ? sampleElev(terr, x / w.cell_m, y / w.cell_m) : 0)); shapeZ.set(key, zs); }
        (sh.points as [number, number][]).forEach(([x, y], i) => { const [px, py] = S(x, y, zs![i]); if (i) g.lineTo(px, py); else g.moveTo(px, py); });
        g.closePath(); g.fillStyle = "rgba(237,231,223,0.14)"; g.fill(); g.strokeStyle = "rgba(237,231,223,0.55)"; g.lineWidth = 1; g.stroke();
      }
      for (const t of w.targets_found ?? []) {
        ring(t.x, t.y, Math.max(t.radius, 4 / c.zoom));
        g.strokeStyle = BR.orange; g.lineWidth = 2; g.stroke();
      }

      const sp = spotRef.current;
      if (sp?.dim) { g.fillStyle = "rgba(10,10,10,0.62)"; g.fillRect(0, 0, W, H); }
      if (terr) legend(g, [...(styleRef.current === "topo" ? [`Contours ${CONTOUR_M} m, bold every ${CONTOUR_M * INDEX_EVERY} m`, "Blue grid: 1 km squares"] : []), ...(m3 ? [`Vertical scale x${ex}, pitch ${Math.round(pitchFor(zr))} deg (zoom-linked)`] : [])]); // after the demo dim (which dims the map, keeps links and aircraft bright) so the key stays readable
      const ids = Object.keys(poses).sort();
      if (zr >= LOD_ICON) { // trails: medium and close only
        for (const id of ids) {
          const t = trails.current[id]; if (!t || t.length < 2) continue;
          g.beginPath(); t.forEach(([x, y, z], i) => { const [px, py] = S(x, y, z + AGL_M); if (i) g.lineTo(px, py); else g.moveTo(px, py); });
          g.strokeStyle = BR.stone + "55"; g.lineWidth = 1.5; g.stroke();
        }
      }
      g.lineWidth = 1; g.strokeStyle = "rgba(237,231,223,0.28)"; // topology links follow the moving aircraft
      for (const [a, b] of s.topology.links as [string, string][]) {
        const p = poses[a], q = poses[b]; if (!p || !q) continue;
        const [x1, y1] = Sa(p.x, p.y), [x2, y2] = Sa(q.x, q.y);
        g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.stroke();
      }
      const wall = Date.now();
      for (const o of panelsRef.current?.offers ?? []) { // real offer decisions only; never synthesised
        const age = wall - o.at;
        if (!o.at || age > PULSE_MS || !o.sender) continue;
        const p = poses[o.sender], q = poses[o.node]; if (!p || !q) continue;
        const [x1, y1] = Sa(p.x, p.y), [x2, y2] = Sa(q.x, q.y), k = age / PULSE_MS, col = o.transfer === "accepted" ? "237,231,223" : "244,123,60"; // accepted = solid stone, rejected = dashed orange (never colour alone)
        g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.strokeStyle = `rgba(${col},${1 - k})`; g.lineWidth = 2.5; g.setLineDash(o.transfer === "accepted" ? [] : [6, 4]); g.stroke(); g.setLineDash([]);
        const m = Math.min(1, age / 1200); g.beginPath(); g.arc(x1 + (x2 - x1) * m, y1 + (y2 - y1) * m, 4, 0, 2 * Math.PI); g.fillStyle = `rgba(${col},${1 - k})`; g.fill();
      }

      for (const [a, b] of sp?.links ?? []) { // guided demo: active P2P transmission, with a packet marching sender -> recipient
        const p = poses[a], q = poses[b]; if (!p || !q) continue;
        const [x1, y1] = Sa(p.x, p.y), [x2, y2] = Sa(q.x, q.y), m = (now / 1200) % 1;
        g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.strokeStyle = BR.orange; g.lineWidth = 2.5; g.shadowColor = BR.orange; g.shadowBlur = 10; g.stroke(); g.shadowBlur = 0;
        g.fillStyle = BR.orange; g.fillRect(x1 + (x2 - x1) * m - 4, y1 + (y2 - y1) * m - 4, 8, 8); // capability candidate in transit: the brand's orange square
      }
      for (const id of ids) {
        const p = poses[id], [px, py] = Sa(p.x, p.y), [gx, gy] = Sg(p.x, p.y);
        proj.current[id] = [px, py];
        if (px < -40 || py < -40 || px > W + 40 || py > H + 40) continue;
        const isSel = id === sel.current, col = BR.stone;
        if (isSel || zr >= LOD_CLOSE) { // sensor footprint: the real perception radius
          ring(p.x, p.y, w.sensor_radius_m);
          g.fillStyle = col + "14"; g.fill(); g.strokeStyle = col + "88"; g.lineWidth = 1; g.setLineDash([6, 4]); g.stroke(); g.setLineDash([]);
        }
        if (m3) { // drop line + ground shadow make the altitude above the terrain obvious
          g.beginPath(); g.moveTo(px, py); g.lineTo(gx, gy); g.strokeStyle = col + "bb"; g.lineWidth = 1; g.setLineDash([3, 3]); g.stroke(); g.setLineDash([]);
          ring(p.x, p.y, 6 / c.zoom); g.fillStyle = "rgba(0,0,0,0.55)"; g.fill(); g.strokeStyle = col; g.stroke();
        }
        const [hx, hy] = m3 ? Sa(p.x + Math.cos(p.heading) * 40, p.y + Math.sin(p.heading) * 40) : [0, 0]; // heading as it appears on screen
        const ang = m3 && Number.isFinite(hx) ? Math.atan2(hy - py, hx - px) : p.heading;
        if (zr < LOD_ICON) { jet(g, px, py, ang, isSel ? 10 : 8, col, isSel); } // far: small arrow
        else { jet(g, px, py, ang, zr >= LOD_CLOSE ? 16 : 11, col, isSel); }
        {
          g.fillStyle = isSel ? BR.orange : BR.stone; g.font = `11px ${MONO}`;
          g.fillText(zr >= LOD_CLOSE ? `${id} · ${bearingDeg(p.heading)}° · ${Math.round(p.speed)} m/s` : id, px + 14, py - 12);
        }
      }

      for (const [id, text] of Object.entries(sp?.pills ?? {})) { // validation / status pills above nodes
        const p = poses[id]; if (!p) continue;
        const [px, py] = Sa(p.x, p.y);
        g.font = `bold 12px ${MONO}`;
        const tw = g.measureText(text).width + 16;
        g.fillStyle = BR.surface; g.strokeStyle = BR.orange; g.lineWidth = 1.5;
        g.beginPath(); g.roundRect(px - tw / 2, py - 46, tw, 22, 11); g.fill(); g.stroke();
        g.fillStyle = BR.stone; g.textAlign = "center"; g.fillText(text, px, py - 31); g.textAlign = "left";
      }

      const len = niceLen(110 / c.zoom), bx = 16, by = H - 16; // scale bar
      g.strokeStyle = BR.grey; g.lineWidth = 2; g.beginPath(); g.moveTo(bx, by); g.lineTo(bx + len * c.zoom, by); g.stroke();
      g.fillStyle = BR.grey; g.font = `10px ${MONO}`; g.fillText(len >= 1000 ? `${len / 1000} km` : `${len} m`, bx, by - 6);
    };
    raf = requestAnimationFrame(frame);
    const iv = setInterval(() => bump((n) => n + 1), 250); // refreshes the telemetry panel
    return () => { cancelAnimationFrame(raf); ro.disconnect(); clearInterval(iv);
      cv.removeEventListener("wheel", onWheel); cv.removeEventListener("pointerdown", onDown); cv.removeEventListener("pointermove", onMove);
      cv.removeEventListener("pointerup", onUp); cv.removeEventListener("pointercancel", onCancel);
    };
  }, [!!world]);
  useEffect(() => { if (world) doFit(); }, [view]); // the 2.5D footprint on screen differs, so refit when switching

  const p = selected ? sampled.current[selected] : undefined;
  const card = selected ? panels?.nodes[selected] : undefined;
  const offers = (panels?.offers ?? []).filter((o) => o.node === selected);
  const feed = [...(panels?.offers ?? [])].slice(-4).reverse();
  const btn = { background: BR.surface, color: BR.stone, border: `1px solid ${BR.border}`, borderRadius: 3, padding: "3px 8px", cursor: "pointer", font: `10px ${MONO}`, letterSpacing: "0.08em", textTransform: "uppercase" } as const;
  const on = (a: boolean) => (a ? { ...btn, border: `1px solid ${BR.orange}`, color: BR.orange } : btn);
  return (
    <div ref={box} style={{ position: "relative", height, background: BR.bg, borderRadius: getPoses ? "6px 6px 0 0" : 6, overflow: "hidden", userSelect: "none", color: BR.stone, font: `11px ${MONO}` }}>
      <canvas ref={glCv} aria-hidden="true" style={{ position: "absolute", left: 0, top: 0, display: glFail.current ? "none" : "block" }} />
      <canvas ref={canvas} aria-label="Large-area map: aircraft, terrain, links" style={{ position: "relative", display: "block", touchAction: "none", cursor: "grab" }} />
      <div style={{ position: "absolute", top: 8, left: 8, display: "flex", gap: 6 }}>
        <button style={btn} onClick={doFit}>Fit world</button>
        <button style={on(mapStyle === "topo")} aria-pressed={mapStyle === "topo"} onClick={() => setMapStyle(mapStyle === "topo" ? "natural" : "topo")}>{mapStyle === "topo" ? "Topo map" : "Imagery"}</button>
        <button style={on(view === "3d")} aria-pressed={view === "3d"} onClick={() => setView(view === "3d" ? "2d" : "3d")}>{view === "3d" ? "2.5D" : "2D"}</button>
        <button style={btn} disabled={!selected} onClick={() => { follow.current = !follow.current; anchor.current = null; setFollowing(follow.current); }}>{following ? "Unfollow" : selected ? `Follow ${selected}` : "Select an aircraft to follow"}</button>
      </div>
      {selected && p && (
        <dl aria-label="Node telemetry" style={{ position: "absolute", top: 8, right: 8, margin: 0, padding: 8, background: "#141414f2", border: `1px solid ${BR.border}`, borderTop: `2px solid ${BR.orange}`, borderRadius: 3, display: "grid", gridTemplateColumns: "auto auto", gap: "2px 10px", minWidth: 190 }}>
          <dt>Node</dt><dd style={{ margin: 0 }}>{selected}</dd>
          <dt>Position</dt><dd style={{ margin: 0 }}>X {km(p.x)} · Y {km(p.y)}</dd>
          <dt>Altitude</dt><dd style={{ margin: 0 }}>{world?.terrain ? `${Math.round(sampleElev(world.terrain, p.x / world.cell_m, p.y / world.cell_m) + AGL_M)} m MSL (${AGL_M} m AGL)` : "not reported"}</dd>
          <dt>Heading</dt><dd style={{ margin: 0 }}>{bearingDeg(p.heading)}°</dd>
          <dt>Speed</dt><dd style={{ margin: 0 }}>{Math.round(p.speed)} m/s</dd>
          <dt>Sensor radius</dt><dd style={{ margin: 0 }}>{world ? km(world.sensor_radius_m) : "not reported"}</dd>
          <dt>Policy version</dt><dd style={{ margin: 0 }}>{card?.policyVersion ?? "not reported"}</dd>
          <dt>Policy updates</dt><dd style={{ margin: 0 }}>{card?.updateCount ?? "not reported"}</dd>
          <dt>Candidates received</dt><dd style={{ margin: 0 }}>{offers.filter((o) => o.transfer === "accepted").length} accepted · {offers.filter((o) => o.transfer === "rejected").length} rejected</dd>
        </dl>
      )}
      <ul aria-label="Policy candidate offers" style={{ position: "absolute", left: 8, bottom: 34, margin: 0, padding: 0, listStyle: "none", maxWidth: "60%" }}>
        {feed.map((o) => (
          <li key={o.sequence} style={{ background: "#141414ee", margin: "2px 0", padding: "2px 8px", borderLeft: `3px solid ${o.transfer === "accepted" ? BR.stone : BR.orange}` }}>
            {o.sender ?? "a peer"} → {o.node}: policy candidate v{o.version} {o.transfer}{o.reason ? ` (${o.reason})` : ""}
          </li>
        ))}
      </ul>
    </div>
  );
}
