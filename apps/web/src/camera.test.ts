import { expect, it } from "vitest";
import { interpPose, lerpAngle, screenToWorld, stepCamera, worldToScreen } from "./camera";

const v = { w: 800, h: 600 };

it("world/screen transforms are inverse", () => {
  const c = { x: 1200, y: -300, zoom: 0.07 };
  const [sx, sy] = worldToScreen(c, v, 500, 900);
  const [x, y] = screenToWorld(c, v, sx, sy);
  expect(x).toBeCloseTo(500); expect(y).toBeCloseTo(900);
});

it("zoom keeps the anchored world point under the cursor at every frame", () => {
  let cur = { x: 0, y: 0, zoom: 0.05 };
  const tgt = { x: 0, y: 0, zoom: 1 };
  const [wx, wy] = screenToWorld(cur, v, 123, 456);
  const anchor = { wx, wy, sx: 123, sy: 456 };
  for (let i = 0; i < 30; i++) {
    cur = stepCamera(cur, tgt, v, anchor, 16);
    const [sx, sy] = worldToScreen(cur, v, wx, wy);
    expect(sx).toBeCloseTo(123); expect(sy).toBeCloseTo(456);
  }
});

it("headings interpolate through 0 deg, not the long way round", () => {
  const a = (359 * Math.PI) / 180, b = (1 * Math.PI) / 180;
  expect(Math.abs(lerpAngle(a, b, 0.5))).toBeLessThan(0.01);
  const p = interpPose({ x: 0, y: 0, heading: a, speed: 80 }, { x: 10, y: 0, heading: b, speed: 80 }, 0.5);
  expect(Math.abs(p.heading)).toBeLessThan(0.01);
});
