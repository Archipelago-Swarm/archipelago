import { useEffect, useRef, useState } from "react";
import { exFor, pitchFor } from "./FlightMap";
import { fitZoom, wheelZoom } from "./camera";
import { Terrain3D, fogMask, ground3, makeCam3, project3, type Cam3 } from "./terrain3d";
import { sampleElev, type MapStyle } from "./terrainTexture";
import { linkStyle, poiLabel, type Meta, type MissionEvent, type View } from "./missionReplay";

const OBJ_COLOR: Record<string, string> = { DISCOVER_POI: "#4aa3ff", VERIFY_POI: "#f5b942", STAY_OPERATIONAL: "#f47b3c", MAINTAIN_CONNECTIVITY: "#a78bfa", SHARE_INFORMATION: "#3ddc84" };
const COMP = ["#3ddc84", "#4aa3ff", "#f5b942", "#ef6a4c", "#a78bfa", "#2dd4bf", "#f472b6"];
const COMM_STATE: Record<string, string> = { CONNECTED: "#3ddc84", DEGRADED: "#f5b942", ISOLATED: "#ef4444", OFFLINE: "#777" };
const MONO = "Consolas, 'Courier New', monospace";

export interface Props {
  meta: Meta; view: View; events: MissionEvent[]; selUav: string | null; selLink: string | null; showWeak: boolean; showRings: boolean;
  onUav(id: string): void; onLink(id: string): void;
}

/** The mission world on the shared Terrain3D renderer (the GPU heightfield FlightMap uses); UAVs, RF links, POIs and zones are drawn on top at their altitude. */
export function MissionMap(props: Props) {
  const box = useRef<HTMLDivElement>(null), glCv = useRef<HTMLCanvasElement>(null), cv = useRef<HTMLCanvasElement>(null);
  const pr = useRef(props); pr.current = props;
  const [style, setStyle] = useState<MapStyle>("topo"), [tilted, setTilted] = useState(true), [glOk, setGlOk] = useState(true);
  const st = useRef({ style, tilted }); st.current = { style, tilted };
  const cam = useRef({ x: 0, y: 0, zoom: 0 }), fit = useRef(0), refit = useRef(true);
  const hit = useRef<{ uavs: [string, number, number][]; links: [string, number, number, number, number][] }>({ uavs: [], links: [] });

  useEffect(() => { refit.current = true; }, [tilted, props.meta]);

  useEffect(() => {
    const el = box.current!, c = cv.current!, g = c.getContext("2d");
    if (!g) return;
    let raf = 0, W = 0, H = 0, T: Terrain3D | null = null, terrKey = "", drag: { x: number; y: number; moved: number } | null = null;
    try { T = new Terrain3D(glCv.current!); } catch { setGlOk(false); } // no WebGL: overlays still draw, flat, on a plain background

    const cam3 = (): Cam3 => {
      const { meta } = pr.current, w = meta.world, flat = !st.current.tilted;
      const ground = (x: number, y: number) => sampleElev(w.terrain, x / w.cellMeters, y / w.cellMeters);
      return makeCam3(cam.current, W, H, flat ? Math.PI / 2 : (pitchFor(cam.current.zoom / fit.current) * Math.PI) / 180, flat ? 0 : exFor(w.width, w.terrain), flat ? 0 : ground(cam.current.x, cam.current.y), ground);
    };
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      W = el.clientWidth; H = el.clientHeight;
      c.width = Math.round(W * dpr); c.height = Math.round(H * dpr); g.setTransform(dpr, 0, 0, dpr, 0, 0);
      const gc = glCv.current!; gc.width = c.width; gc.height = c.height;
      refit.current = true;
    };
    const ro = new ResizeObserver(resize); ro.observe(el); resize();

    const onWheel = (e: WheelEvent) => { e.preventDefault(); cam.current = { ...cam.current, zoom: wheelZoom(cam.current.zoom, e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY, fit.current * 0.6, fit.current * 40) }; };
    const onDown = (e: PointerEvent) => { c.setPointerCapture(e.pointerId); drag = { x: e.clientX, y: e.clientY, moved: 0 }; };
    const onMove = (e: PointerEvent) => {
      if (!drag) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y, r = c.getBoundingClientRect(), x0 = drag.x - r.left, y0 = drag.y - r.top;
      drag.x = e.clientX; drag.y = e.clientY; drag.moved += Math.abs(dx) + Math.abs(dy);
      if (drag.moved < 4) return;
      const k = cam3(), [ax, ay] = ground3(k, x0, y0, 0), [bx, by] = ground3(k, x0 + dx, y0 + dy, 0); // grab the ground
      cam.current = { ...cam.current, x: cam.current.x + ax - bx, y: cam.current.y + ay - by };
    };
    const onUp = (e: PointerEvent) => {
      const d = drag; drag = null;
      if (!d || d.moved >= 4) return;
      const r = c.getBoundingClientRect(), sx = e.clientX - r.left, sy = e.clientY - r.top;
      const u = hit.current.uavs.map(([id, x, y]) => [id, Math.hypot(x - sx, y - sy)] as const).filter((a) => a[1] < 18).sort((a, b) => a[1] - b[1])[0];
      if (u) return pr.current.onUav(u[0]);
      const l = hit.current.links.map(([id, ax, ay, bx, by]) => {
        const vx = bx - ax, vy = by - ay, t = Math.max(0, Math.min(1, ((sx - ax) * vx + (sy - ay) * vy) / (vx * vx + vy * vy || 1)));
        return [id, Math.hypot(ax + t * vx - sx, ay + t * vy - sy)] as const;
      }).filter((a) => a[1] < 7).sort((a, b) => a[1] - b[1])[0];
      if (l) pr.current.onLink(l[0]);
    };
    c.addEventListener("wheel", onWheel, { passive: false });
    c.addEventListener("pointerdown", onDown); c.addEventListener("pointermove", onMove); c.addEventListener("pointerup", onUp); c.addEventListener("pointercancel", () => { drag = null; });

    const frame = () => {
      raf = requestAnimationFrame(frame);
      const { meta, view, events, selUav, selLink, showWeak, showRings } = pr.current, w = meta.world, terr = w.terrain;
      if (!W || !H) return;
      if (refit.current) { fit.current = fitZoom({ w: W, h: H }, w.width, w.height, st.current.tilted ? 0.8 : 0.92); cam.current = { x: w.width / 2, y: w.height / 2, zoom: fit.current }; refit.current = false; }
      const k = cam3(), flat = !st.current.tilted, gz = (x: number, y: number) => (flat ? 0 : sampleElev(terr, x / w.cellMeters, y / w.cellMeters));
      const S = (x: number, y: number, z = 0) => project3(k, x, y, z), P = (x: number, y: number, agl: number) => S(x, y, gz(x, y) + agl);
      if (T) {
        const key = `${meta.seed}:${terr.size}x${terr.height}`;
        if (key !== terrKey) { T.setTerrain(terr, w.cellMeters); T.setFog(fogMask(terr)); T.setViewshed(new Uint8Array(terr.size * terr.height * 2)); terrKey = key; }
        T.draw(k, st.current.style);
      }
      g.clearRect(0, 0, W, H);
      if (!T) { g.fillStyle = "#101214"; g.fillRect(0, 0, W, H); }
      const line = (pts: [number, number][]) => { g.beginPath(); pts.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); };
      const ring = (x: number, y: number, r: number) => { // a circle lying on the ground
        g.beginPath();
        for (let i = 0; i <= 48; i++) { const a = (i / 48) * 2 * Math.PI, wx = x + Math.cos(a) * r, wy = y + Math.sin(a) * r, [px, py] = S(wx, wy, gz(wx, wy)); if (i) g.lineTo(px, py); else g.moveTo(px, py); }
      };
      const gline = (x0: number, y0: number, x1: number, y1: number) => line(Array.from({ length: 41 }, (_, i) => P(x0 + ((x1 - x0) * i) / 40, y0 + ((y1 - y0) * i) / 40, 0)));

      g.strokeStyle = "rgba(237,231,223,0.28)"; g.lineWidth = 1; // 100 km tiles
      for (let i = 0; i <= w.tilesX; i++) { gline(i * w.tileMeters, 0, i * w.tileMeters, w.height); g.stroke(); }
      for (let j = 0; j <= w.tilesY; j++) { gline(0, j * w.tileMeters, w.width, j * w.tileMeters); g.stroke(); }

      for (const d of view.floor.disruptions) {
        if (!d.active || !d.position || !d.radius) continue;
        const comm = d.type === "COMMUNICATION_DEGRADATION", col = comm ? "245,185,66" : "74,163,255";
        ring(d.position.x, d.position.y, d.radius); g.fillStyle = `rgba(${col},0.16)`; g.fill(); g.strokeStyle = `rgb(${col})`; g.lineWidth = 1.5; g.setLineDash([6, 4]); g.stroke(); g.setLineDash([]);
      }

      const air: Record<string, [number, number]> = {}, hits = hit.current; hits.uavs = []; hits.links = [];
      for (const u of view.uavs) air[u.id] = P(u.position.x, u.position.y, u.altitudeMeters);
      for (const l of view.floor.links) {
        const s = linkStyle(l, showWeak), a = air[l.sourceNodeId], b = air[l.targetNodeId];
        if (!s || !a || !b || !Number.isFinite(a[0] + b[0])) continue;
        hits.links.push([l.id, a[0], a[1], b[0], b[1]]);
        line([a, b]); g.globalAlpha = s.opacity; g.strokeStyle = s.color; g.lineWidth = l.id === selLink ? s.width + 2 : s.width; g.setLineDash(s.dash ? s.dash.split(/[ ,]+/).map(Number) : []); g.stroke(); g.setLineDash([]); g.globalAlpha = 1;
      }
      for (const e of events) { // recent skill transfers: dashed orange with a packet marching sender -> recipient
        if (e.type !== "SKILL_TRANSFERRED" || e.timestamp > view.t || view.t - e.timestamp > 60) continue;
        const a = air[e.sourceNodeId], b = air[e.targetNodeId]; if (!a || !b) continue;
        line([a, b]); g.strokeStyle = "#f47b3c"; g.lineWidth = 2.5; g.setLineDash([5, 3]); g.stroke(); g.setLineDash([]);
        const m = (performance.now() / 1200) % 1; g.fillStyle = "#f47b3c"; g.fillRect(a[0] + (b[0] - a[0]) * m - 4, a[1] + (b[1] - a[1]) * m - 4, 8, 8);
      }

      for (const p of view.floor.pois) {
        const label = poiLabel(p);
        if (!label) continue; // UNKNOWN: ground truth stays hidden
        const [x, y] = P(p.position.x, p.position.y, 0), ok = p.state === "VERIFIED", col = ok ? "#3ddc84" : "#f5b942";
        g.beginPath(); g.arc(x, y, 7, 0, 2 * Math.PI); g.fillStyle = "#101214"; g.fill(); g.strokeStyle = col; g.lineWidth = 2; g.stroke();
        g.fillStyle = col; g.font = `10px ${MONO}`; g.textAlign = "center"; g.fillText(ok ? "✓" : "?", x, y + 3.5); g.textAlign = "left";
        g.fillStyle = "#EDE7DF"; g.font = `9px ${MONO}`; g.fillText(`${p.id} ${label}`, x + 10, y + 3);
      }

      for (const u of view.uavs) {
        const [x, y] = air[u.id]; if (!Number.isFinite(x)) continue;
        hits.uavs.push([u.id, x, y]);
        const dead = u.status === "FAILED", col = dead ? "#666" : OBJ_COLOR[u.currentObjective] ?? "#ccc", [gx, gy] = P(u.position.x, u.position.y, 0);
        if (!flat) { g.beginPath(); g.moveTo(x, y); g.lineTo(gx, gy); g.strokeStyle = col + "bb"; g.lineWidth = 1; g.setLineDash([3, 3]); g.stroke(); g.setLineDash([]); } // drop line: altitude above the terrain
        if (showRings && !dead) { ring(u.position.x, u.position.y, u.sensorRadius); g.fillStyle = col + "14"; g.fill(); g.strokeStyle = col + "66"; g.lineWidth = 1; g.stroke(); }
        if (!dead && u.networkComponent >= 0) { g.beginPath(); g.arc(x, y, 12, 0, 2 * Math.PI); g.strokeStyle = COMP[u.networkComponent % COMP.length]; g.lineWidth = 2; g.stroke(); }
        if (u.activeSkill && !dead) { g.beginPath(); g.arc(x, y, 16, 0, 2 * Math.PI); g.strokeStyle = "#f47b3c"; g.lineWidth = 1.5; g.setLineDash([2, 3]); g.stroke(); g.setLineDash([]); }
        const [hx, hy] = P(u.position.x + Math.cos(u.heading) * 4000, u.position.y + Math.sin(u.heading) * 4000, u.altitudeMeters), ang = Math.atan2(hy - y, hx - x); // heading as it appears on screen
        g.save(); g.translate(x, y); g.rotate(Number.isFinite(ang) ? ang : u.heading);
        g.beginPath(); g.moveTo(9, 0); g.lineTo(-7, 6); g.lineTo(-4, 0); g.lineTo(-7, -6); g.closePath(); g.fillStyle = col; g.fill(); g.strokeStyle = u.id === pr.current.selUav ? "#fff" : "#0A0A0A"; g.lineWidth = u.id === pr.current.selUav ? 2 : 1; g.stroke(); g.restore();
        g.font = `11px ${MONO}`; g.fillStyle = dead ? "#777" : "#EDE7DF"; g.fillText(u.id.replace("UAV-", "U"), x + 14, y - 10);
        if (!dead) { const climbing = u.altitudeMeters > meta.uavSpec.cruiseAltitudeAglMeters + 1; g.font = `9px ${MONO}`; g.fillStyle = COMM_STATE[u.communicationState]; g.fillText(`${Math.round(u.altitudeMeters)} m${climbing ? " ↑" : ""}${u.sensorState === "DEGRADED" ? " ⚠" : ""}`, x + 14, y + 2); }
        if (u.id === selUav) { g.beginPath(); g.arc(x, y, 20, 0, 2 * Math.PI); g.strokeStyle = "#fff"; g.lineWidth = 1; g.stroke(); }
      }

      const len = 100_000, bx = 16, by = H - 16, wpx = len * cam.current.zoom; // scale bar (zoom = px per metre at the focus point)
      g.strokeStyle = "#EDE7DF"; g.lineWidth = 2; g.beginPath(); g.moveTo(bx, by); g.lineTo(bx + wpx, by); g.stroke();
      g.fillStyle = "#EDE7DF"; g.font = `10px ${MONO}`; g.fillText("100 km", bx, by - 6);
    };
    raf = requestAnimationFrame(frame);
    return () => { cancelAnimationFrame(raf); ro.disconnect(); c.removeEventListener("wheel", onWheel); c.removeEventListener("pointerdown", onDown); c.removeEventListener("pointermove", onMove); c.removeEventListener("pointerup", onUp); };
  }, []);

  const btn = { background: "#141414", color: "#EDE7DF", border: "1px solid #333", borderRadius: 3, padding: "3px 8px", cursor: "pointer", font: `10px ${MONO}`, textTransform: "uppercase" } as const;
  return (
    <div ref={box} className="m-map" role="img" aria-label="Mission map">
      <canvas ref={glCv} aria-hidden="true" style={{ position: "absolute", inset: 0, width: "100%", height: "100%", display: glOk ? "block" : "none" }} />
      <canvas ref={cv} style={{ position: "relative", display: "block", width: "100%", height: "100%", touchAction: "none", cursor: "grab" }} />
      <div style={{ position: "absolute", top: 8, left: 8, display: "flex", gap: 6 }}>
        <button style={btn} onClick={() => { refit.current = true; }}>Fit world</button>
        <button style={btn} aria-pressed={style === "topo"} onClick={() => setStyle(style === "topo" ? "natural" : "topo")}>{style === "topo" ? "Topo map" : "Imagery"}</button>
        <button style={btn} aria-pressed={tilted} onClick={() => setTilted(!tilted)}>{tilted ? "2.5D" : "2D"}</button>
        {!glOk && <span style={{ ...btn, border: "none" }}>WebGL unavailable: terrain not drawn</span>}
      </div>
    </div>
  );
}
