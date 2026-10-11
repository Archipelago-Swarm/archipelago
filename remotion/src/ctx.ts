import { Cam } from "./world/camera3d";
import { H, V3 } from "./world/geo";
import { Sample } from "./world/scenario";

export type Ctx = {
  t: number;
  cam: Cam;
  /** world point -> screen */
  proj: (p: V3) => [number, number];
  /** point on the terrain surface -> screen */
  gnd: (x: number, y: number) => [number, number];
  /** UAV samples this frame (NODE-01..04) */
  nodes: Sample[];
  alpha: number[];
  /** screen position of each UAV */
  scr: [number, number][];
};

export const mkProj = (cam: Cam) => (p: V3): [number, number] => {
  const q = cam.project(p);
  return [q.x, q.y];
};
export const mkGnd = (cam: Cam) => (x: number, y: number): [number, number] => {
  const q = cam.project({ x, y, z: H(x, y) });
  return [q.x, q.y];
};
