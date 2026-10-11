export const FPS = 30;
export const DURATION_S = 72;
/** design size is 1920x1080; the composition is rendered at SCALE x that (2 = 3840x2160, 4K) */
export const SCALE = 2;
export const W = 1920;
export const H = 1080;
/** screen y of the camera focus: the action sits in the upper part of the frame, the bottom band is reserved for callouts */
export const CY = 0.42 * 1080;

export type P = { x: number; y: number };

export const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
export const smooth = (x: number) => {
  const c = clamp01(x);
  return c * c * (3 - 2 * c);
};
/** 0 -> 1 between a and b (eased) */
export const win = (t: number, a: number, b: number) => smooth((t - a) / (b - a));
/** fade in a..b, hold, fade out c..d */
export const pulse = (t: number, a: number, b: number, c: number, d: number) =>
  win(t, a, b) * (1 - win(t, c, d));
export const lerp = (a: number, b: number, f: number) => a + (b - a) * f;

/** Periodic Catmull-Rom through keys; key i sits at t = i * DURATION / n, so the path loops exactly. */
export function loopPos(keys: readonly P[], t: number): P {
  const n = keys.length;
  const u = ((((t / DURATION_S) % 1) + 1) % 1) * n;
  const i = Math.floor(u);
  const f = u - i;
  const p0 = keys[(i - 1 + n) % n];
  const p1 = keys[i % n];
  const p2 = keys[(i + 1) % n];
  const p3 = keys[(i + 2) % n];
  const cr = (a: number, b: number, c: number, d: number) =>
    0.5 *
    (2 * b + (-a + c) * f + (2 * a - 5 * b + 4 * c - d) * f * f + (-a + 3 * b - 3 * c + d) * f * f * f);
  return { x: cr(p0.x, p1.x, p2.x, p3.x), y: cr(p0.y, p1.y, p2.y, p3.y) };
}

/** Sideways "search weave" that eases in/out over window w = [inA, inB, outA, outB]. */
export function weave(keys: readonly P[], t: number, w: [number, number, number, number], amp = 80): P {
  const b = win(t, w[0], w[1]) * (1 - win(t, w[2], w[3]));
  if (b <= 0) return { x: 0, y: 0 };
  const a = loopPos(keys, t - 0.03);
  const c = loopPos(keys, t + 0.03);
  const dx = c.x - a.x;
  const dy = c.y - a.y;
  const L = Math.hypot(dx, dy) || 1;
  const s = amp * b * Math.sin((t - w[0]) * 5.2);
  return { x: (-dy / L) * s, y: (dx / L) * s };
}
