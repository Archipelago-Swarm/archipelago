import { describe, expect, it } from "vitest";
import { ground3, makeCam3, project3 } from "./terrain3d";

const flat = () => 0;

describe("2.5D perspective camera", () => {
  for (const pitchDeg of [84, 50, 22]) {
    it(`projects and unprojects consistently at pitch ${pitchDeg}`, () => {
      const cam = makeCam3({ x: 5000, y: 3000, zoom: 0.05 }, 1000, 600, (pitchDeg * Math.PI) / 180, 2, 300, flat);
      const [cx, cy] = project3(cam, 5000, 3000, 300);
      expect(cx).toBeCloseTo(500, 3); // the focus point sits at screen centre
      expect(cy).toBeCloseTo(300, 3);
      const [sx, sy] = project3(cam, 5600, 3300, 300);
      const [wx, wy] = ground3(cam, sx, sy, 300);
      expect(wx).toBeCloseTo(5600, 2);
      expect(wy).toBeCloseTo(3300, 2);
    });
  }

  it("has perspective: a point nearer the camera is drawn larger and higher ground moves up the screen", () => {
    const cam = makeCam3({ x: 0, y: 0, zoom: 0.05 }, 1000, 600, (40 * Math.PI) / 180, 2, 0, flat);
    const near = project3(cam, 1000, 2000, 0), far = project3(cam, 1000, -2000, 0);
    expect(Math.abs(near[0] - 500)).toBeGreaterThan(Math.abs(far[0] - 500)); // same x offset, wider when nearer
    expect(project3(cam, 0, 0, 500)[1]).toBeLessThan(project3(cam, 0, 0, 0)[1]);
  });

  it("keeps the eye above terrain on the near side", () => {
    const cam = makeCam3({ x: 0, y: 0, zoom: 0.5 }, 1000, 600, (22 * Math.PI) / 180, 2, 0, () => 900);
    expect(cam.eye[2]).toBeGreaterThanOrEqual(900 * 2 + 80);
  });
});
