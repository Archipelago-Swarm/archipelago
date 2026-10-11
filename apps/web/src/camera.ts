// Camera + pose interpolation for the continuous-flight map. All world<->screen conversion lives here.
// World units are meters (x east, y south). camera.x/y is the world point at the viewport centre; zoom is px per meter.

export interface Camera { x: number; y: number; zoom: number }
export interface Viewport { w: number; h: number }
export interface Bounds { x0: number; y0: number; x1: number; y1: number }
export interface Anchor { wx: number; wy: number; sx: number; sy: number }
export interface Pose2 { x: number; y: number; heading: number; speed: number }

export const worldToScreen = (c: Camera, v: Viewport, x: number, y: number): [number, number] =>
  [(x - c.x) * c.zoom + v.w / 2, (y - c.y) * c.zoom + v.h / 2];
export const screenToWorld = (c: Camera, v: Viewport, sx: number, sy: number): [number, number] =>
  [(sx - v.w / 2) / c.zoom + c.x, (sy - v.h / 2) / c.zoom + c.y];

export function visibleBounds(c: Camera, v: Viewport, pad = 0): Bounds {
  const [x0, y0] = screenToWorld(c, v, -pad, -pad);
  const [x1, y1] = screenToWorld(c, v, v.w + pad, v.h + pad);
  return { x0, y0, x1, y1 };
}
export const intersects = (a: Bounds, b: Bounds) => a.x0 <= b.x1 && a.x1 >= b.x0 && a.y0 <= b.y1 && a.y1 >= b.y0;
export const boundsOf = (pts: ReadonlyArray<readonly [number, number]>): Bounds => ({
  x0: Math.min(...pts.map((p) => p[0])), y0: Math.min(...pts.map((p) => p[1])),
  x1: Math.max(...pts.map((p) => p[0])), y1: Math.max(...pts.map((p) => p[1])),
});

// Zoom that fits the whole world with a margin.
export const fitZoom = (v: Viewport, worldW: number, worldH: number, margin = 0.92) => Math.min(v.w / worldW, v.h / worldH) * margin;

// Wheel -> new target zoom, clamped. Continuous (no discrete levels).
export const wheelZoom = (zoom: number, deltaY: number, min: number, max: number, sensitivity = 0.0015) =>
  Math.min(max, Math.max(min, zoom * Math.exp(-deltaY * sensitivity)));

// One animation frame: ease zoom (and position) toward the target. While an anchor is set the world point under the
// cursor is pinned to that screen point, which is what makes zoom cursor-centred at every intermediate frame.
export function stepCamera(cur: Camera, tgt: Camera, v: Viewport, anchor: Anchor | null, dtMs: number, rate = 14): Camera {
  const k = 1 - Math.exp(-(dtMs / 1000) * rate);
  const zoom = Math.abs(tgt.zoom - cur.zoom) < cur.zoom * 1e-4 ? tgt.zoom : cur.zoom + (tgt.zoom - cur.zoom) * k;
  if (anchor) return { zoom, x: anchor.wx - (anchor.sx - v.w / 2) / zoom, y: anchor.wy - (anchor.sy - v.h / 2) / zoom };
  return { zoom, x: cur.x + (tgt.x - cur.x) * k, y: cur.y + (tgt.y - cur.y) * k };
}

// Shortest-arc angle interpolation (359deg -> 1deg passes through 0deg).
export const wrapAngle = (a: number) => a - 2 * Math.PI * Math.floor((a + Math.PI) / (2 * Math.PI));
export const lerpAngle = (a: number, b: number, t: number) => wrapAngle(a + wrapAngle(b - a) * t);

// Cubic Hermite between two poses with tangents along each heading: smooth arcs instead of straight chords.
export function interpPose(p0: Pose2, p1: Pose2, t: number): Pose2 {
  const d = Math.hypot(p1.x - p0.x, p1.y - p0.y);
  const heading = lerpAngle(p0.heading, p1.heading, t);
  if (d < 1e-6 || t >= 1) return { x: t >= 1 ? p1.x : p0.x, y: t >= 1 ? p1.y : p0.y, heading, speed: p0.speed + (p1.speed - p0.speed) * t };
  const t2 = t * t, t3 = t2 * t;
  const h00 = 2 * t3 - 3 * t2 + 1, h10 = t3 - 2 * t2 + t, h01 = -2 * t3 + 3 * t2, h11 = t3 - t2;
  const m0 = [Math.cos(p0.heading) * d, Math.sin(p0.heading) * d], m1 = [Math.cos(p1.heading) * d, Math.sin(p1.heading) * d];
  return {
    x: h00 * p0.x + h10 * m0[0] + h01 * p1.x + h11 * m1[0],
    y: h00 * p0.y + h10 * m0[1] + h01 * p1.y + h11 * m1[1],
    heading, speed: p0.speed + (p1.speed - p0.speed) * t,
  };
}

// Keeps the previous and current snapshot poses and the observed arrival interval; sample() is called every frame.
export class PoseBuffer {
  prev: Record<string, Pose2> = {};
  cur: Record<string, Pose2> = {};
  tCur = 0;
  interval = 250; // ms, smoothed gap between snapshots
  key: string | null = null;
  tick = -1;
  push(runKey: string, tick: number, poses: Record<string, Pose2>, nowMs: number, instant = false) {
    if (runKey !== this.key || tick <= this.tick || instant) { this.prev = poses; this.cur = poses; this.interval = 250; }
    else { this.prev = this.cur; this.cur = poses; this.interval = Math.min(2000, Math.max(40, this.interval * 0.7 + (nowMs - this.tCur) * 0.3)); }
    this.key = runKey; this.tick = tick; this.tCur = nowMs;
  }
  sample(nowMs: number): Record<string, Pose2> {
    const t = Math.min(1, Math.max(0, (nowMs - this.tCur) / this.interval));
    const out: Record<string, Pose2> = {};
    for (const [id, p1] of Object.entries(this.cur)) out[id] = interpPose(this.prev[id] ?? p1, p1, t);
    return out;
  }
}

export const bearingDeg = (heading: number) => ((Math.round((heading * 180) / Math.PI) + 90) % 360 + 360) % 360; // 0 = north, clockwise
