import { useEffect, useRef, useState } from "react";
import type { WorldSnapshot } from "@archipelago/contracts";
import {
  PoseBuffer, bearingDeg, boundsOf, fitZoom, intersects, screenToWorld, stepCamera, visibleBounds, wheelZoom, worldToScreen,
  type Anchor, type Bounds, type Camera, type Pose2,
} from "./camera";
import type { Panels } from "./live";
import type { Spotlight } from "./demoScriptController";
import { buildTerrainTexture } from "./terrainTexture";

const COLORS = ["#4fc3f7", "#ffb74d", "#81c784", "#ba68c8", "#f06292", "#e0e0e0"];
const TRAIL_MAX = 600, TRAIL_STEP_M = 30, PULSE_MS = 3000;
const LOD_ICON = 2.5, LOD_CLOSE = 10; // zoom relative to the fit-world zoom

function jet(g: CanvasRenderingContext2D, x: number, y: number, heading: number, size: number, color: string, ring: boolean) {
  g.save();
  g.translate(x, y);
  g.rotate(heading); // sprite points along +x, so heading 0 = east
  g.beginPath(); // generic delta-wing silhouette
  g.moveTo(size, 0); g.lineTo(-size * 0.75, size * 0.8); g.lineTo(-size * 0.35, 0); g.lineTo(-size * 0.75, -size * 0.8); g.closePath();
  g.fillStyle = color; g.fill();
  g.strokeStyle = "#0b1020"; g.lineWidth = 1; g.stroke();
  if (ring) { g.beginPath(); g.arc(0, 0, size * 1.5, 0, 2 * Math.PI); g.strokeStyle = "#fff"; g.lineWidth = 1.5; g.stroke(); }
  g.restore();
}

const niceLen = (m: number) => [50, 100, 200, 500, 1000, 2000, 5000, 10000].find((n) => n >= m) ?? 20000;
const km = (m: number) => `${(m / 1000).toFixed(2)} km`;

export function FlightMap({ snap, panels, height, instant = false, getPoses, focus, spotlight }: { snap: WorldSnapshot; panels?: Panels; height: string; instant?: boolean; getPoses?: () => Record<string, Pose2> | null; focus?: { ids: string[]; n: number }; spotlight?: Spotlight }) {
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const snapRef = useRef(snap), panelsRef = useRef(panels), instantRef = useRef(instant), spotRef = useRef(spotlight);
  const buf = useRef(new PoseBuffer());
  const tex = useRef<HTMLCanvasElement | null>(null), texKey = useRef("");
  const trails = useRef<Record<string, [number, number][]>>({});
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
    const z = fitZoom({ w: el.clientWidth, h: el.clientHeight }, world.width_m, world.height_m);
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
    const shapeBox = new Map<string, Bounds>();

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      W = el.clientWidth; H = el.clientHeight;
      cv.width = Math.max(1, Math.round(W * dpr)); cv.height = Math.max(1, Math.round(H * dpr));
      cv.style.width = `${W}px`; cv.style.height = `${H}px`;
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (!fit.current.done || (!dragging && tgt.current.zoom <= fit.current.zoom * 1.001)) { doFit(); cam.current = { ...tgt.current }; }
    };
    const ro = new ResizeObserver(resize); ro.observe(el); resize();

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = cv.getBoundingClientRect(), sx = e.clientX - r.left, sy = e.clientY - r.top, v = { w: W, h: H };
      const dy = e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY;
      tgt.current = { ...tgt.current, zoom: wheelZoom(tgt.current.zoom, dy, fit.current.zoom * 0.5, 4) };
      if (!follow.current) { const [wx, wy] = screenToWorld(cam.current, v, sx, sy); anchor.current = { wx, wy, sx, sy }; }
    };
    const onDown = (e: PointerEvent) => { cv.setPointerCapture(e.pointerId); dragging = { x: e.clientX, y: e.clientY, moved: 0 }; };
    const onMove = (e: PointerEvent) => {
      if (!dragging) return;
      const dx = e.clientX - dragging.x, dy = e.clientY - dragging.y;
      dragging.x = e.clientX; dragging.y = e.clientY; dragging.moved += Math.abs(dx) + Math.abs(dy);
      if (dragging.moved < 4) return;
      anchor.current = null; follow.current = false; setFollowing(false); // dragging breaks follow
      const z = cam.current.zoom;
      cam.current = { ...cam.current, x: cam.current.x - dx / z, y: cam.current.y - dy / z };
      tgt.current = { ...tgt.current, x: cam.current.x, y: cam.current.y, zoom: tgt.current.zoom };
    };
    const onUp = (e: PointerEvent) => {
      const d = dragging; dragging = null;
      if (!d || d.moved >= 4) return;
      const r = cv.getBoundingClientRect(), sx = e.clientX - r.left, sy = e.clientY - r.top;
      let best: string | null = null, bd = 28;
      for (const [id, p] of Object.entries(sampled.current)) {
        const [px, py] = worldToScreen(cam.current, { w: W, h: H }, p.x, p.y);
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
      const dt = Math.min(100, now - last); last = now;
      const s = snapRef.current, w = s.world, v = { w: W, h: H };
      if (!w || !W) return;
      const poses = posesRef.current?.() ?? buf.current.sample(now);
      sampled.current = poses;
      if (follow.current && sel.current && poses[sel.current]) { tgt.current = { ...tgt.current, x: poses[sel.current].x, y: poses[sel.current].y }; }
      cam.current = stepCamera(cam.current, tgt.current, v, anchor.current, dt);
      if (anchor.current) tgt.current = { ...tgt.current, x: cam.current.x, y: cam.current.y };
      if (Math.abs(tgt.current.zoom - cam.current.zoom) < 1e-9) anchor.current = null;
      const c = cam.current, zr = c.zoom / fit.current.zoom;
      const vb = visibleBounds(c, v, 40 / c.zoom);
      const S = (x: number, y: number) => worldToScreen(c, v, x, y);

      if (trailKey.current !== s.run_id) { trails.current = {}; trailKey.current = s.run_id; }
      for (const [id, p] of Object.entries(poses)) {
        const t = (trails.current[id] ??= []), l = t[t.length - 1];
        if (!l || Math.hypot(l[0] - p.x, l[1] - p.y) > TRAIL_STEP_M) { t.push([p.x, p.y]); if (t.length > TRAIL_MAX) t.shift(); }
      }

      g.fillStyle = "#070b14"; g.fillRect(0, 0, W, H);
      const [ox, oy] = S(0, 0), [ex, ey] = S(w.width_m, w.height_m);
      g.fillStyle = "#0d1424"; g.fillRect(ox, oy, ex - ox, ey - oy);
      if (w.terrain) { // smooth terrain with unobserved areas dimmed; rebuilt only when the observed set changes
        const key = w.terrain.observed + w.terrain.biome.length;
        if (texKey.current !== key) { texKey.current = key; tex.current = buildTerrainTexture(w.terrain); }
        g.imageSmoothingEnabled = true; g.drawImage(tex.current!, ox, oy, ex - ox, ey - oy);
      }
      g.strokeStyle = "#2a3a5c"; g.lineWidth = 1; g.strokeRect(ox, oy, ex - ox, ey - oy);

      for (const sh of w.shapes ?? []) { // revealed terrain polygons, culled to the viewport
        const key = sh.id + ":" + sh.points.length;
        let b = shapeBox.get(key); if (!b) { b = boundsOf(sh.points as [number, number][]); shapeBox.set(key, b); }
        if (!intersects(b, vb)) continue;
        g.beginPath();
        (sh.points as [number, number][]).forEach(([x, y], i) => { const [px, py] = S(x, y); if (i) g.lineTo(px, py); else g.moveTo(px, py); });
        g.closePath(); g.fillStyle = "rgba(120,135,165,0.28)"; g.fill(); g.strokeStyle = "rgba(160,175,205,0.55)"; g.lineWidth = 1; g.stroke();
      }
      for (const t of w.targets_found ?? []) {
        const [px, py] = S(t.x, t.y); g.beginPath(); g.arc(px, py, Math.max(4, t.radius * c.zoom), 0, 2 * Math.PI);
        g.strokeStyle = "#ffd54f"; g.lineWidth = 1.5; g.stroke();
      }

      const sp = spotRef.current;
      if (sp?.dim) { g.fillStyle = "rgba(5,8,16,0.62)"; g.fillRect(0, 0, W, H); } // guided demo: dim the map, keep links and aircraft bright
      const ids = Object.keys(poses).sort();
      const color = (id: string) => COLORS[ids.indexOf(id) % COLORS.length];
      if (zr >= LOD_ICON) { // trails: medium and close only
        for (const id of ids) {
          const t = trails.current[id]; if (!t || t.length < 2) continue;
          g.beginPath(); t.forEach(([x, y], i) => { const [px, py] = S(x, y); if (i) g.lineTo(px, py); else g.moveTo(px, py); });
          g.strokeStyle = color(id) + "55"; g.lineWidth = 1.5; g.stroke();
        }
      }
      g.lineWidth = 1; g.strokeStyle = "rgba(90,160,255,0.22)"; // topology links follow the moving aircraft
      for (const [a, b] of s.topology.links as [string, string][]) {
        const p = poses[a], q = poses[b]; if (!p || !q) continue;
        const [x1, y1] = S(p.x, p.y), [x2, y2] = S(q.x, q.y);
        g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.stroke();
      }
      const wall = Date.now();
      for (const o of panelsRef.current?.offers ?? []) { // real offer decisions only; never synthesised
        const age = wall - o.at;
        if (!o.at || age > PULSE_MS || !o.sender) continue;
        const p = poses[o.sender], q = poses[o.node]; if (!p || !q) continue;
        const [x1, y1] = S(p.x, p.y), [x2, y2] = S(q.x, q.y), k = age / PULSE_MS, col = o.transfer === "accepted" ? "76,175,80" : "255,152,0";
        g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.strokeStyle = `rgba(${col},${1 - k})`; g.lineWidth = 2.5; g.stroke();
        const m = Math.min(1, age / 1200); g.beginPath(); g.arc(x1 + (x2 - x1) * m, y1 + (y2 - y1) * m, 4, 0, 2 * Math.PI); g.fillStyle = `rgba(${col},${1 - k})`; g.fill();
      }

      for (const [a, b] of sp?.links ?? []) { // guided demo: active P2P transmission, with a packet marching sender -> recipient
        const p = poses[a], q = poses[b]; if (!p || !q) continue;
        const [x1, y1] = S(p.x, p.y), [x2, y2] = S(q.x, q.y), m = (now / 1200) % 1;
        g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.strokeStyle = "#00e5ff"; g.lineWidth = 3; g.shadowColor = "#00e5ff"; g.shadowBlur = 12; g.stroke(); g.shadowBlur = 0;
        g.beginPath(); g.arc(x1 + (x2 - x1) * m, y1 + (y2 - y1) * m, 5, 0, 2 * Math.PI); g.fillStyle = "#fff"; g.fill();
      }
      for (const id of ids) {
        const p = poses[id], [px, py] = S(p.x, p.y);
        if (px < -40 || py < -40 || px > W + 40 || py > H + 40) continue;
        const isSel = id === sel.current, col = color(id);
        if (isSel || zr >= LOD_CLOSE) { // sensor footprint: the real perception radius
          g.beginPath(); g.arc(px, py, w.sensor_radius_m * c.zoom, 0, 2 * Math.PI);
          g.fillStyle = col + "14"; g.fill(); g.strokeStyle = col + "88"; g.lineWidth = 1; g.setLineDash([6, 4]); g.stroke(); g.setLineDash([]);
        }
        if (zr < LOD_ICON) { jet(g, px, py, p.heading, isSel ? 10 : 8, col, isSel); } // far: small arrow
        else { jet(g, px, py, p.heading, zr >= LOD_CLOSE ? 16 : 11, col, isSel); }
        if (zr >= LOD_ICON || isSel) {
          g.fillStyle = "#cfd8dc"; g.font = "11px system-ui, sans-serif";
          g.fillText(zr >= LOD_CLOSE ? `${id} · ${bearingDeg(p.heading)}° · ${Math.round(p.speed)} m/s` : id, px + 14, py - 12);
        }
      }

      for (const [id, text] of Object.entries(sp?.pills ?? {})) { // validation / status pills above nodes
        const p = poses[id]; if (!p) continue;
        const [px, py] = S(p.x, p.y);
        g.font = "bold 12px system-ui, sans-serif";
        const tw = g.measureText(text).width + 16;
        g.fillStyle = "#0d1424"; g.strokeStyle = "#00e5ff"; g.lineWidth = 1.5;
        g.beginPath(); g.roundRect(px - tw / 2, py - 46, tw, 22, 11); g.fill(); g.stroke();
        g.fillStyle = "#e3eaf5"; g.textAlign = "center"; g.fillText(text, px, py - 31); g.textAlign = "left";
      }

      const len = niceLen(110 / c.zoom), bx = 16, by = H - 16; // scale bar
      g.strokeStyle = "#90a4ae"; g.lineWidth = 2; g.beginPath(); g.moveTo(bx, by); g.lineTo(bx + len * c.zoom, by); g.stroke();
      g.fillStyle = "#90a4ae"; g.font = "11px system-ui, sans-serif"; g.fillText(len >= 1000 ? `${len / 1000} km` : `${len} m`, bx, by - 6);
    };
    raf = requestAnimationFrame(frame);
    const iv = setInterval(() => bump((n) => n + 1), 250); // refreshes the telemetry panel
    return () => { cancelAnimationFrame(raf); ro.disconnect(); clearInterval(iv);
      cv.removeEventListener("wheel", onWheel); cv.removeEventListener("pointerdown", onDown); cv.removeEventListener("pointermove", onMove);
      cv.removeEventListener("pointerup", onUp); cv.removeEventListener("pointercancel", onCancel);
    };
  }, [!!world]);

  const p = selected ? sampled.current[selected] : undefined;
  const card = selected ? panels?.nodes[selected] : undefined;
  const offers = (panels?.offers ?? []).filter((o) => o.node === selected);
  const feed = [...(panels?.offers ?? [])].slice(-4).reverse();
  const btn = { background: "#16213a", color: "#e3eaf5", border: "1px solid #33476e", borderRadius: 4, padding: "3px 8px", cursor: "pointer" } as const;
  return (
    <div ref={box} style={{ position: "relative", height, background: "#070b14", borderRadius: getPoses ? "6px 6px 0 0" : 6, overflow: "hidden", userSelect: "none", color: "#e3eaf5", font: "12px system-ui, sans-serif" }}>
      <canvas ref={canvas} aria-label="Large-area map: aircraft, terrain, links" style={{ display: "block", touchAction: "none", cursor: "grab" }} />
      <div style={{ position: "absolute", top: 8, left: 8, display: "flex", gap: 6 }}>
        <button style={btn} onClick={doFit}>Fit world</button>
        <button style={btn} disabled={!selected} onClick={() => { follow.current = !follow.current; anchor.current = null; setFollowing(follow.current); }}>{following ? "Unfollow" : selected ? `Follow ${selected}` : "Select an aircraft to follow"}</button>
      </div>
      {selected && p && (
        <dl aria-label="Node telemetry" style={{ position: "absolute", top: 8, right: 8, margin: 0, padding: 8, background: "#0d1424ee", border: "1px solid #33476e", borderRadius: 6, display: "grid", gridTemplateColumns: "auto auto", gap: "2px 10px", minWidth: 190 }}>
          <dt>Node</dt><dd style={{ margin: 0 }}>{selected}</dd>
          <dt>Position</dt><dd style={{ margin: 0 }}>X {km(p.x)} · Y {km(p.y)}</dd>
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
          <li key={o.sequence} style={{ background: "#0d1424dd", margin: "2px 0", padding: "2px 8px", borderLeft: `3px solid ${o.transfer === "accepted" ? "#4caf50" : "#ff9800"}` }}>
            {o.sender ?? "a peer"} → {o.node}: policy candidate v{o.version} {o.transfer}{o.reason ? ` (${o.reason})` : ""}
          </li>
        ))}
      </ul>
    </div>
  );
}
