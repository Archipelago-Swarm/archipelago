import type { TerrainGrid } from "@archipelago/contracts";
import { sampleElev } from "./terrainTexture";

// 2.5D view: a perspective camera over the heightfield. World metres: x east, y south, z up (z is exaggerated by `ex`).
// `zoom` keeps its 2D meaning (screen px per metre at the focus point), so the camera distance follows from it.
// `tilt` is the camera elevation above the horizon (PI/2 = straight down, north up).
const FOV = (40 * Math.PI) / 180, TAN_H = Math.tan(FOV / 2);
export interface Cam3 { vp: Float32Array; eye: [number, number, number]; f: number[]; r: number[]; u: number[]; W: number; H: number; ex: number; dist: number }
const dot = (a: number[], b: number[]) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const norm = (a: number[]) => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };

/** `tz` is the focus point's elevation in metres (before exaggeration); `groundZ` keeps the eye above the terrain it flies over. */
export function makeCam3(c: { x: number; y: number; zoom: number }, W: number, H: number, tilt: number, ex: number, tz: number, groundZ: (x: number, y: number) => number): Cam3 {
  const dist = H / (2 * c.zoom * TAN_H), T = [c.x, c.y, tz * ex];
  const eye: [number, number, number] = [T[0], T[1] + dist * Math.cos(tilt), T[2] + dist * Math.sin(tilt)];
  eye[2] = Math.max(eye[2], groundZ(eye[0], eye[1]) * ex + 80); // never inside a mountain on the near side
  const f = norm([T[0] - eye[0], T[1] - eye[1], T[2] - eye[2]]);
  const r = Math.hypot(f[0], f[1]) < 1e-4 ? [1, 0, 0] : norm([-f[1], f[0], 0]); // east-ish; degenerate looking straight down
  const u = [f[1] * r[2] - f[2] * r[1], f[2] * r[0] - f[0] * r[2], f[0] * r[1] - f[1] * r[0]]; // f x r
  const near = dist * 0.05, far = dist * 14, k = 1 / TAN_H, A = (far + near) / (near - far), B = (2 * far * near) / (near - far), asp = W / H;
  const m = new Float32Array(16); // column-major clip = P * V
  const row = (i: number, v: number[], s: number, t: number) => { m[i] = v[0] * s; m[4 + i] = v[1] * s; m[8 + i] = v[2] * s; m[12 + i] = t; };
  row(0, r, k / asp, (-dot(r, eye) * k) / asp); row(1, u, k, -dot(u, eye) * k);
  row(2, f, -A, A * dot(f, eye) + B); row(3, f, 1, -dot(f, eye));
  return { vp: m, eye, f, r, u, W, H, ex, dist };
}

/** Screen position of a world point; NaN when it is behind the camera. */
export function project3(cam: Cam3, x: number, y: number, z: number): [number, number] {
  const m = cam.vp, zz = z * cam.ex, w = m[3] * x + m[7] * y + m[11] * zz + m[15];
  if (w <= 1e-6) return [NaN, NaN];
  return [((m[0] * x + m[4] * y + m[8] * zz + m[12]) / w + 1) * 0.5 * cam.W, (1 - (m[1] * x + m[5] * y + m[9] * zz + m[13]) / w) * 0.5 * cam.H];
}

/** World (x, y) under a screen point, on the horizontal plane at elevation `z` (metres, before exaggeration). */
export function ground3(cam: Cam3, sx: number, sy: number, z: number): [number, number] {
  const nx = (sx / cam.W) * 2 - 1, ny = 1 - (sy / cam.H) * 2, a = nx * TAN_H * (cam.W / cam.H), b = ny * TAN_H;
  const d = [cam.f[0] + a * cam.r[0] + b * cam.u[0], cam.f[1] + a * cam.r[1] + b * cam.u[1], cam.f[2] + a * cam.r[2] + b * cam.u[2]];
  const t = (z * cam.ex - cam.eye[2]) / Math.min(d[2], -1e-3); // rays at/above the horizon are clamped to a far hit
  return [cam.eye[0] + t * d[0], cam.eye[1] + t * d[1]];
}

const SUB = 3, SKIRT_M = 400;
const VERT = `#version 300 es
in vec3 aPos; in vec2 aUv; in float aSkirt;
uniform mat4 uVP; uniform float uE;
out vec2 vUv; out float vSkirt; out float vZ; out float vD;
void main() {
  gl_Position = uVP * vec4(aPos.x, aPos.y, aPos.z * uE, 1.0);
  vUv = aUv; vSkirt = aSkirt; vZ = aPos.z; vD = gl_Position.w;
}`;
const FRAG = `#version 300 es
precision highp float;
in vec2 vUv; in float vSkirt; in float vZ; in float vD;
uniform sampler2D uBase; uniform sampler2D uFog; uniform sampler2D uVs; uniform float uDist;
out vec4 o;
void main() {
  vec3 col = texture(uBase, vUv).rgb;
  if (vSkirt > 0.5) col = vec3(0.42, 0.32, 0.24) * (0.4 + 0.6 * clamp(vZ / 1500.0 + 0.3, 0.0, 1.0));
  else { vec4 f = texture(uFog, vUv); col = mix(col, f.rgb, f.a); vec4 v = texture(uVs, vUv); col = mix(col, v.rgb, v.a); }
  col = mix(col, vec3(0.027, 0.043, 0.078), clamp((vD - uDist * 1.4) / (uDist * 3.0), 0.0, 0.75)); // distance haze: depth cue
  o = vec4(col, 1.0);
}`;

export class Terrain3D {
  private gl: WebGL2RenderingContext;
  private prog: WebGLProgram;
  private vao: WebGLVertexArrayObject;
  private count = 0;
  private tex: Record<"uBase" | "uFog" | "uVs", WebGLTexture>;
  private loc: Record<string, WebGLUniformLocation | null> = {};

  constructor(canvas: HTMLCanvasElement) {
    const gl = canvas.getContext("webgl2", { antialias: true, alpha: false });
    if (!gl) throw new Error("WebGL2 unavailable");
    this.gl = gl;
    const sh = (type: number, src: string) => {
      const s = gl.createShader(type)!; gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) ?? "shader");
      return s;
    };
    const p = gl.createProgram()!;
    gl.attachShader(p, sh(gl.VERTEX_SHADER, VERT)); gl.attachShader(p, sh(gl.FRAGMENT_SHADER, FRAG)); gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p) ?? "link");
    this.prog = p; this.vao = gl.createVertexArray()!;
    for (const n of ["uVP", "uE", "uDist", "uBase", "uFog", "uVs"]) this.loc[n] = gl.getUniformLocation(p, n);
    const mk = () => gl.createTexture()!;
    this.tex = { uBase: mk(), uFog: mk(), uVs: mk() };
  }

  setMesh(t: TerrainGrid, cellM: number) {
    const gl = this.gl, nx = t.size * SUB + 1, ny = t.height * SUB + 1, W = t.size * cellM, H = t.height * cellM;
    const vtx: number[] = [], idx: number[] = [], z = new Float32Array(nx * ny);
    for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
      const zz = sampleElev(t, i / SUB, j / SUB); z[j * nx + i] = zz;
      vtx.push((i / SUB) * cellM, (j / SUB) * cellM, zz, (i / SUB) * cellM / W, (j / SUB) * cellM / H, 0);
    }
    for (let j = 0; j < ny - 1; j++) for (let i = 0; i < nx - 1; i++) {
      const a = j * nx + i, b = a + 1, c = a + nx, d = c + 1; idx.push(a, c, b, b, c, d);
    }
    const skirt = (i: number, j: number) => { // a bottom vertex under the surface vertex (i, j)
      const k = vtx.length / 6; vtx.push((i / SUB) * cellM, (j / SUB) * cellM, -SKIRT_M, (i / SUB) * cellM / W, (j / SUB) * cellM / H, 1); return k;
    };
    const top = (i: number, j: number) => { // surface vertex copy flagged as wall, so the cliff face is not textured from the map
      const k = vtx.length / 6; vtx.push((i / SUB) * cellM, (j / SUB) * cellM, z[j * nx + i], (i / SUB) * cellM / W, (j / SUB) * cellM / H, 1); return k;
    };
    const wall = (pts: [number, number][]) => { // surface edge + matching skirt row -> quad strip
      for (let k = 0; k < pts.length - 1; k++) {
        const [i0, j0] = pts[k], [i1, j1] = pts[k + 1], a = top(i0, j0), b = top(i1, j1), c = skirt(i0, j0), d = skirt(i1, j1);
        idx.push(a, c, b, b, c, d, a, b, c, b, d, c); // both windings: culling is off
      }
    };
    const row = (j: number) => Array.from({ length: nx }, (_, i) => [i, j] as [number, number]);
    const col = (i: number) => Array.from({ length: ny }, (_, j) => [i, j] as [number, number]);
    wall(row(0)); wall(row(ny - 1)); wall(col(0)); wall(col(nx - 1));
    gl.bindVertexArray(this.vao);
    const vb = gl.createBuffer()!; gl.bindBuffer(gl.ARRAY_BUFFER, vb); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(vtx), gl.STATIC_DRAW);
    const ib = gl.createBuffer()!; gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint32Array(idx), gl.STATIC_DRAW);
    for (const [name, size, off] of [["aPos", 3, 0], ["aUv", 2, 3], ["aSkirt", 1, 5]] as const) {
      const l = gl.getAttribLocation(this.prog, name); gl.enableVertexAttribArray(l); gl.vertexAttribPointer(l, size, gl.FLOAT, false, 24, off * 4);
    }
    this.count = idx.length;
  }

  setTexture(name: "uBase" | "uFog" | "uVs", src: HTMLCanvasElement) {
    const gl = this.gl, big = name === "uBase";
    gl.bindTexture(gl.TEXTURE_2D, this.tex[name]);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, src);
    if (big) gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, big ? gl.LINEAR_MIPMAP_LINEAR : gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    const aniso = big && gl.getExtension("EXT_texture_filter_anisotropic");
    if (aniso) gl.texParameterf(gl.TEXTURE_2D, aniso.TEXTURE_MAX_ANISOTROPY_EXT, 8);
  }

  draw(cam: Cam3) {
    const gl = this.gl;
    gl.viewport(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight);
    gl.clearColor(7 / 255, 11 / 255, 20 / 255, 1); gl.clearDepth(1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    if (!this.count) return;
    gl.enable(gl.DEPTH_TEST); gl.depthFunc(gl.LESS); gl.disable(gl.CULL_FACE);
    gl.useProgram(this.prog); gl.bindVertexArray(this.vao);
    gl.uniformMatrix4fv(this.loc.uVP, false, cam.vp); gl.uniform1f(this.loc.uE, cam.ex); gl.uniform1f(this.loc.uDist, cam.dist);
    (["uBase", "uFog", "uVs"] as const).forEach((n, i) => { gl.activeTexture(gl.TEXTURE0 + i); gl.bindTexture(gl.TEXTURE_2D, this.tex[n]); gl.uniform1i(this.loc[n], i); });
    gl.drawElements(gl.TRIANGLES, this.count, gl.UNSIGNED_INT, 0);
  }
}
