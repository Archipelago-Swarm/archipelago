import type { TerrainGrid } from "@archipelago/contracts";
import { sampleElev, type MapStyle } from "./terrainTexture";

// Perspective camera over the heightfield. World metres: x east, y south, z up (z is exaggerated by `ex`; 0 = flat 2D map).
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
out vec2 vW; out float vSkirt; out float vZ; out float vD;
void main() {
  gl_Position = uVP * vec4(aPos.x, aPos.y, aPos.z * uE, 1.0);
  vW = aPos.xy; vSkirt = aSkirt; vZ = aPos.z; vD = gl_Position.w;
}`;

// Everything on the ground is computed per pixel from the sim grid, so detail is resolution-independent:
// bicubic elevation + fractal noise whose octaves fade in as you zoom (and out as they drop below a pixel),
// contours/grid as antialiased lines, fog and line-of-sight as smooth masks with AA'd edges.
const FRAG = `#version 300 es
precision highp float; precision highp int; precision highp sampler2D;
in vec2 vW; in float vSkirt; in float vZ; in float vD;
uniform sampler2D uH; uniform sampler2D uB; uniform sampler2D uFog; uniform sampler2D uVs;
uniform vec2 uGrid; uniform float uCell; uniform float uDist; uniform float uZmin; uniform float uZmax; uniform int uStyle; uniform float uPx;
out vec4 o;
const vec3 BLACK = vec3(10.) / 255., STONE = vec3(237., 231., 223.) / 255., ORANGE = vec3(244., 123., 60.) / 255., GREY = vec3(138.) / 255.;
const float DETAIL = 45.;

float hash(ivec2 p, int s) {
  uint h = uint(p.x) * 374761393u + uint(p.y) * 668265263u + uint(s) * 2246822519u;
  h = (h ^ (h >> 13)) * 1274126177u;
  return float(h ^ (h >> 16)) / 4294967295.0;
}
float vnoise(vec2 p, int s) {
  vec2 i = floor(p), f = p - i; f = f * f * (3. - 2. * f);
  ivec2 q = ivec2(i);
  float a = hash(q, s), b = hash(q + ivec2(1, 0), s), c = hash(q + ivec2(0, 1), s), d = hash(q + ivec2(1, 1), s);
  return a + (b - a) * f.x + (c - a) * f.y + (a - b - c + d) * f.x * f.y;
}
float fade(float freq, float fw) { return 1. - smoothstep(0.25, 0.5, freq * fw); }
// fbm over 'oct' octaves; octaves finer than a pixel collapse to their mean so nothing shimmers when zoomed out
float fbm(vec2 p, int s, int oct, float fw) {
  float t = 0., n = 0., a = 1., f = 1.;
  for (int o = 0; o < 8; o++) { if (o >= oct) break; float fd = fade(f, fw); t += a * (fd > 0. ? mix(.5, vnoise(p * f, s + o), fd) : .5); n += a; a *= .5; f *= 2.; } // sub-pixel octaves cost nothing
  return t / n;
}
float gH(ivec2 c) { return texelFetch(uH, clamp(c, ivec2(0), ivec2(uGrid) - 1), 0).r; }
float cub(float p0, float p1, float p2, float p3, float t) { return p1 + .5 * t * (p2 - p0 + t * (2. * p0 - 5. * p1 + 4. * p2 - p3 + t * (3. * (p1 - p2) + p3 - p0))); }
float baseH(vec2 uv) {
  vec2 g = uv - .5; ivec2 i = ivec2(floor(g)); vec2 f = g - vec2(i);
  float r0 = cub(gH(i + ivec2(-1, -1)), gH(i + ivec2(0, -1)), gH(i + ivec2(1, -1)), gH(i + ivec2(2, -1)), f.x);
  float r1 = cub(gH(i + ivec2(-1, 0)), gH(i + ivec2(0, 0)), gH(i + ivec2(1, 0)), gH(i + ivec2(2, 0)), f.x);
  float r2 = cub(gH(i + ivec2(-1, 1)), gH(i + ivec2(0, 1)), gH(i + ivec2(1, 1)), gH(i + ivec2(2, 1)), f.x);
  float r3 = cub(gH(i + ivec2(-1, 2)), gH(i + ivec2(0, 2)), gH(i + ivec2(1, 2)), gH(i + ivec2(2, 2)), f.x);
  return cub(r0, r1, r2, r3, f.y);
}
float detail(vec2 uv, float fw) { // mirrors detailElev() in terrainTexture.ts, plus finer octaves while zoomed in
  float a = fbm(uv * 3., 7, 5, fw * 3.);
  float r = 1. - abs(2. * fbm(uv * 1.6, 91, 5, fw * 1.6) - 1.);
  float d = (a - .5) + .6 * (r - .5);
  float amp = .03125 / 1.9375, f = 96.; vec2 p = uv * 96.;
  for (int o = 5; o < 12; o++) { float fd = fade(f, fw); if (fd <= 0.) break; d += amp * fd * (vnoise(p, 7 + o) - .5); amp *= .5; p *= 2.; f *= 2.; }
  return DETAIL * d;
}
float H(vec2 uv, float fw) { return baseH(uv) + detail(uv, fw); }
vec3 ramp(float f) { // brand monochrome relief ramp
  vec3 c0 = vec3(40., 39., 37.), c1 = vec3(72., 70., 65.), c2 = vec3(112., 108., 100.), c3 = vec3(156., 151., 141.), c4 = vec3(206., 200., 190.), c5 = vec3(237., 231., 223.);
  vec3 c = f < .25 ? mix(c0, c1, f / .25) : f < .5 ? mix(c1, c2, (f - .25) / .25) : f < .75 ? mix(c2, c3, (f - .5) / .25) : f < .93 ? mix(c3, c4, (f - .75) / .18) : mix(c4, c5, (f - .93) / .07);
  return c / 255.;
}
float hatch(float coord, float period, float width) { // antialiased line family in CSS px
  float p = fract(coord / (period * uPx)); return clamp(width + .5 - min(p, 1. - p) * period, 0., 1.);
}

void main() {
  vec2 uv = vW / uCell, fwv = fwidth(uv); float fw = max(fwv.x, fwv.y);
  // masks first: derivatives must be taken outside any divergent branch
  vec2 wuv = (uv + .35 * (vec2(fbm(uv * 3., 21, 2, fw * 3.), fbm(uv * 3., 22, 2, fw * 3.)) - .5)) / uGrid;
  float m = texture(uFog, wuv).r, ua = .92 * clamp(m * 1.6, 0., 1.), mw = fwidth(m) + 1e-4;
  vec2 vv = texture(uVs, wuv).rg, vw2 = fwidth(vv) + 1e-4;
  vec3 col;
  if (vSkirt > .5) {
    col = vec3(.55, .53, .5) * (.22 + .5 * clamp(vZ / 1500. + .3, 0., 1.));
  } else {
    if (m > .995) {
      col = vec3(.12); // deep in the fog: nothing of the terrain shows, so skip evaluating it
    } else {
      float z = H(uv, fw), e = max(fw * .75, 1e-4);
      vec2 gr = vec2(H(uv + vec2(e, 0.), fw) - z, H(uv + vec2(0., e), fw) - z) / (e * uCell); // slope (m per m)
      float shade = clamp(2.2 * (-gr.x - gr.y) * .7071, -.7, .7);
      vec2 wp = vec2(fbm(uv * 2., 3, 3, fw * 2.), fbm(uv * 2., 4, 3, fw * 2.)) - .5; // domain-warped biome borders
      vec2 bv = texelFetch(uB, clamp(ivec2(floor(uv + .8 * wp)), ivec2(0), ivec2(uGrid) - 1), 0).rg * 255.;
      float bio = floor(bv.x + .5), veg = bv.y / 100.;
      float fz = z / 50., fzw = length(gr) * fw * uCell / 50. + 1e-6, fz5 = fz / 5., fz5w = fzw / 5.; // contour-level change per pixel, from the slope
      float dm = abs(fract(fz - .5) - .5) / fzw, di = abs(fract(fz5 - .5) - .5) / fz5w; // distance to a minor / index contour, px
      float covM = clamp(1.1 - dm, 0., 1.) * smoothstep(3., 8., 1. / fzw), covI = clamp(1.6 - di, 0., 1.) * smoothstep(3., 8., 1. / fz5w);
      if (uStyle == 1) { // topographic map
        float sp = bio > .5 ? (vnoise(uv * 30., 61) - .5) * (.25 + .5 * veg) * (bio > 1.5 ? 1.3 : 1.) * fade(30., fw) + (vnoise(uv * 240., 62) - .5) * .18 * veg * fade(240., fw) : 0.;
        float tex = 1. + .08 * (fbm(uv * 14., 40, 2, fw * 14.) - .5) + sp;
        col = ramp(clamp((z - uZmin) / (uZmax - uZmin + 1e-6), 0., 1.)) * (.82 + .95 * shade) * tex;
        vec3 lc = dot(col, vec3(.299, .587, .114)) > .47 ? BLACK : STONE; // dark lines on bright ground, stone lines on dark
        col = mix(col, lc, max(covM * .34, covI * .8));
        vec2 gq = vW / 1000., gf = fwv * uCell / 1000. + 1e-7, gd = abs(fract(gq - .5) - .5) / gf; // 1 km graticule
        col = mix(col, GREY, .28 * clamp(1.2 - min(gd.x, gd.y), 0., 1.) * smoothstep(6., 14., 1. / max(gf.x, gf.y)));
      } else { // imagery
        vec3 base = bio < .5 ? vec3(150., 178., 100.) : bio < 1.5 ? vec3(64., 120., 60.) : vec3(26., 82., 44.);
        float k = .95 + .4 * clamp(z / 550., 0., 1.) + shade;
        float speck = (vnoise(uv * 38., 55) - .5) * fade(38., fw) + (vnoise(uv * 300., 56) - .5) * .5 * fade(300., fw);
        k *= 1. + .35 * (fbm(uv * 14., 40, 3, fw * 14.) - .5) + (.3 + .5 * veg) * .45 * speck * (bio > .5 ? 1. : .5);
        col = mix(base, vec3(120., 108., 96.), clamp((length(gr) - .25) * 2., 0., 1.)) / 255. * k;
        col *= 1. - .1 * covM - .12 * covI;
      }
    }
    // fog of war: dense black, a faint hatch, and a dashed orange frontier that stays crisp at any zoom
    col = mix(col, BLACK, ua);
    col = mix(col, GREY, hatch(gl_FragCoord.x + gl_FragCoord.y, 12., .5) * .14 * smoothstep(.4, .7, m) * ua);
    float edge = clamp(1.4 - abs(m - .5) / mw / uPx, 0., 1.);
    col = mix(col, ORANGE, edge * step(fract((gl_FragCoord.x + gl_FragCoord.y) / (18. * uPx)), .62));
    // line of sight from the aircraft: stone wash where visible now, orange hatch where terrain hides the ground
    float sh = clamp((vv.r - .5) / vw2.x + .5, 0., 1.), vw = clamp((vv.g - .5) / vw2.y + .5, 0., 1.);
    col = mix(col, STONE, .16 * vw);
    col = mix(col, ORANGE, sh * (.16 + .5 * hatch(gl_FragCoord.x - gl_FragCoord.y, 10., .6)));
  }
  col = mix(col, vec3(.039), clamp((vD - uDist * 1.4) / (uDist * 3.), 0., .75)); // distance haze: depth cue
  o = vec4(col, 1.);
}`;

export class Terrain3D {
  private gl: WebGL2RenderingContext;
  private prog: WebGLProgram;
  private vao: WebGLVertexArrayObject;
  private count = 0;
  private tex: Record<"uH" | "uB" | "uFog" | "uVs", WebGLTexture>;
  private loc: Record<string, WebGLUniformLocation | null> = {};
  private grid = { w: 1, h: 1, cell: 625, zMin: 0, zMax: 1 };

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
    for (const n of ["uVP", "uE", "uDist", "uH", "uB", "uFog", "uVs", "uGrid", "uCell", "uZmin", "uZmax", "uStyle", "uPx"]) this.loc[n] = gl.getUniformLocation(p, n);
    const mk = () => gl.createTexture()!;
    this.tex = { uH: mk(), uB: mk(), uFog: mk(), uVs: mk() };
  }

  private upload(name: keyof Terrain3D["tex"], internal: number, format: number, type: number, w: number, h: number, data: ArrayBufferView, linear: boolean) {
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, this.tex[name]); gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texImage2D(gl.TEXTURE_2D, 0, internal, w, h, 0, format, type, data);
    const f = linear ? gl.LINEAR : gl.NEAREST;
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, f); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, f);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  }

  /** Uploads the sim grid (elevation, biome, vegetation) and builds the displacement mesh. Call once per terrain. */
  setTerrain(t: TerrainGrid, cellM: number) {
    const gl = this.gl, w = t.size, h = t.height, nx = w * SUB + 1, ny = h * SUB + 1, W = w * cellM, H = h * cellM;
    const elev = Float32Array.from(t.elev_m), bv = new Uint8Array(w * h * 2);
    for (let i = 0; i < w * h; i++) { bv[i * 2] = +t.biome[i] || 0; bv[i * 2 + 1] = t.veg_pct?.[i] ?? 50; }
    this.upload("uH", gl.R32F, gl.RED, gl.FLOAT, w, h, elev, false);
    this.upload("uB", gl.RG8, gl.RG, gl.UNSIGNED_BYTE, w, h, bv, false);
    this.grid = { w, h, cell: cellM, zMin: elev.reduce((a, b) => Math.min(a, b), Infinity) - 20, zMax: elev.reduce((a, b) => Math.max(a, b), -Infinity) + 20 };

    const vtx: number[] = [], idx: number[] = [], z = new Float32Array(nx * ny);
    for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
      const zz = sampleElev(t, i / SUB, j / SUB); z[j * nx + i] = zz;
      vtx.push((i / SUB) * cellM, (j / SUB) * cellM, zz, (i / SUB) * cellM / W, (j / SUB) * cellM / H, 0);
    }
    for (let j = 0; j < ny - 1; j++) for (let i = 0; i < nx - 1; i++) {
      const a = j * nx + i, b = a + 1, c = a + nx, d = c + 1; idx.push(a, c, b, b, c, d);
    }
    const vert = (i: number, j: number, zz: number) => { // wall vertex (flag 1): surface copy or a point under it
      const k = vtx.length / 6; vtx.push((i / SUB) * cellM, (j / SUB) * cellM, zz, 0, 0, 1); return k;
    };
    const wall = (pts: [number, number][]) => {
      for (let k = 0; k < pts.length - 1; k++) {
        const [i0, j0] = pts[k], [i1, j1] = pts[k + 1];
        const a = vert(i0, j0, z[j0 * nx + i0]), b = vert(i1, j1, z[j1 * nx + i1]), c = vert(i0, j0, -SKIRT_M), d = vert(i1, j1, -SKIRT_M);
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
      const l = gl.getAttribLocation(this.prog, name); if (l < 0) continue; gl.enableVertexAttribArray(l); gl.vertexAttribPointer(l, size, gl.FLOAT, false, 24, off * 4);
    }
    this.count = idx.length;
  }

  /** One byte per cell: how unexplored it is (255 = fully), already softened. Smoothly sampled by the shader. */
  setFog(mask: Uint8Array) { this.upload("uFog", this.gl.R8, this.gl.RED, this.gl.UNSIGNED_BYTE, this.grid.w, this.grid.h, mask, true); }
  /** Two bytes per cell: R = hidden behind terrain, G = in view now. */
  setViewshed(rg: Uint8Array) { this.upload("uVs", this.gl.RG8, this.gl.RG, this.gl.UNSIGNED_BYTE, this.grid.w, this.grid.h, rg, true); }

  draw(cam: Cam3, style: MapStyle) {
    const gl = this.gl, g = this.grid;
    gl.viewport(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight);
    gl.clearColor(10 / 255, 10 / 255, 10 / 255, 1); gl.clearDepth(1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    if (!this.count) return;
    gl.enable(gl.DEPTH_TEST); gl.depthFunc(gl.LESS); gl.disable(gl.CULL_FACE);
    gl.useProgram(this.prog); gl.bindVertexArray(this.vao);
    gl.uniformMatrix4fv(this.loc.uVP, false, cam.vp); gl.uniform1f(this.loc.uE, cam.ex); gl.uniform1f(this.loc.uDist, cam.dist);
    gl.uniform2f(this.loc.uGrid, g.w, g.h); gl.uniform1f(this.loc.uCell, g.cell); gl.uniform1f(this.loc.uZmin, g.zMin); gl.uniform1f(this.loc.uZmax, g.zMax);
    gl.uniform1i(this.loc.uStyle, style === "topo" ? 1 : 0); gl.uniform1f(this.loc.uPx, gl.drawingBufferWidth / cam.W);
    (["uH", "uB", "uFog", "uVs"] as const).forEach((n, i) => { gl.activeTexture(gl.TEXTURE0 + i); gl.bindTexture(gl.TEXTURE_2D, this.tex[n]); gl.uniform1i(this.loc[n], i); });
    gl.drawElements(gl.TRIANGLES, this.count, gl.UNSIGNED_INT, 0);
  }
}

/** Unexplored mask for setFog: 3x3-softened, 255 = unexplored. */
export function fogMask(t: TerrainGrid): Uint8Array {
  const w = t.size, h = t.height, out = new Uint8Array(w * h);
  const obs = (x: number, y: number) => (t.observed[Math.min(h - 1, Math.max(0, y)) * w + Math.min(w - 1, Math.max(0, x))] === "1" ? 1 : 0);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    let a = 0; for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) a += obs(x + dx, y + dy);
    out[y * w + x] = Math.round(255 * (1 - a / 9));
  }
  return out;
}

/** Visibility classes from buildViewshed (0 none, 1 hidden, 2 in view) as the R/G bytes setViewshed expects. */
export function viewshedRG(vs: Uint8Array): Uint8Array {
  const out = new Uint8Array(vs.length * 2);
  for (let i = 0; i < vs.length; i++) { out[i * 2] = vs[i] === 1 ? 255 : 0; out[i * 2 + 1] = vs[i] === 2 ? 255 : 0; }
  return out;
}
