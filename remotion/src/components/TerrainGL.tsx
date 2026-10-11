import { useLayoutEffect, useRef } from "react";
import * as THREE from "three";
import { Cam } from "../world/camera3d";
import { coastAt, elevM, GRID, Viewshed, ZS } from "../world/geo";
import { CY, H, SCALE, W } from "../world/paths";

export type Layer = { vs: Viewshed; los: number; cover: number };
export type Layers = Layer[];

const UP = 3; // mesh vertices per DEM cell
const PAD = 56; // extra cells of (mirrored, faded) world around the data
const VS_N = 108;

// Whole region as one smooth mesh (built once): nothing is ever culled, so nothing pops while the camera moves.
let GEO: THREE.BufferGeometry | null = null;
function geometry() {
  if (GEO) return GEO;
  const nx = (GRID.w - 1 + 2 * PAD) * UP + 1, ny = (GRID.h - 1 + 2 * PAD) * UP + 1;
  const pos = new Float32Array(nx * ny * 3), aE = new Float32Array(nx * ny), aC = new Float32Array(nx * ny);
  for (let j = 0; j < ny; j++)
    for (let i = 0; i < nx; i++) {
      const x = i / UP - PAD, y = j / UP - PAD, k = j * nx + i;
      const e = elevM(x, y, 1);
      pos[k * 3] = x; pos[k * 3 + 1] = -y; pos[k * 3 + 2] = e * ZS;
      aE[k] = e; aC[k] = coastAt(x, y);
    }
  const idx = new Uint32Array((nx - 1) * (ny - 1) * 6);
  let q = 0;
  for (let j = 0; j < ny - 1; j++)
    for (let i = 0; i < nx - 1; i++) {
      const a = j * nx + i, b = a + 1, c = a + nx, d = c + 1;
      idx[q++] = a; idx[q++] = c; idx[q++] = b; idx[q++] = b; idx[q++] = c; idx[q++] = d;
    }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setAttribute("aE", new THREE.BufferAttribute(aE, 1));
  g.setAttribute("aC", new THREE.BufferAttribute(aC, 1));
  g.setIndex(new THREE.BufferAttribute(idx, 1));
  g.computeVertexNormals();
  GEO = g;
  return g;
}

const VERT = /* glsl */ `
attribute float aE; attribute float aC;
varying float vE; varying float vC; varying vec3 vN; varying vec3 vW;
void main() { vE = aE; vC = aC; vN = normal; vW = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;

const FRAG = /* glsl */ `
precision highp float;
varying float vE; varying float vC; varying vec3 vN; varying vec3 vW;
uniform vec3 uCam; uniform float uFog0; uniform float uFog1; uniform vec2 uSize; uniform float uPad;
uniform vec4 uVs0; uniform vec4 uVs1; uniform vec2 uA0; uniform vec2 uA1;
uniform sampler2D uT0; uniform sampler2D uT1;
const vec3 SEA = vec3(10.,11.,13.)/255.;
const vec3 LOW = vec3(30.,29.,27.)/255.; const vec3 MID = vec3(72.,70.,65.)/255.; const vec3 HIGH = vec3(156.,151.,143.)/255.;
const vec3 ORANGE = vec3(244.,123.,60.)/255.; const vec3 STONE = vec3(237.,231.,223.)/255.;
const vec3 L = normalize(vec3(-0.55, 0.55, 0.62));

vec3 overlay(vec3 col, vec4 vs, vec2 a, sampler2D tex, vec2 w) {
  if (a.x < 0.01 && a.y < 0.01) return col;
  vec2 uv = ((w - vs.xy) / vs.z + 0.5) / vs.w;
  if (uv.x < 0. || uv.y < 0. || uv.x > 1. || uv.y > 1.) return col;
  float v = texture2D(tex, uv).r;
  float half_ = vs.w * vs.z * 0.5;
  if (v > 0.004) return mix(col, ORANGE, min(0.62, v * 1.1 + 0.18) * a.x);
  if (length(w - (vs.xy + half_)) < half_) return mix(col, STONE, 0.07 * a.y);
  return col;
}

void main() {
  vec2 w = vec2(vW.x, -vW.y);
  vec2 out_ = max(max(-w, w - uSize), 0.);
  float edge = smoothstep(uPad * 0.3, uPad * 0.9, length(out_));
  float land = smoothstep(0.46, 0.54, vC);
  float lit = max(dot(normalize(vN), L), 0.);
  float t = sqrt(clamp(vE / 1500., 0., 1.));
  vec3 col = t < 0.45 ? mix(LOW, MID, t / 0.45) : mix(MID, HIGH, (t - 0.45) / 0.55);
  float f = vE / 150.;
  float fw = max(fwidth(f), 1e-4);
  float line = 1. - smoothstep(0., fw * 1.4, abs(fract(f - 0.5) - 0.5));
  col *= (0.30 + 0.95 * lit) * (1.0 + 0.05 * mod(floor(f), 2.));
  col += line * 0.045 * clamp(1. - fw * 3., 0., 1.);
  col = overlay(col, uVs0, uA0, uT0, w);
  col = overlay(col, uVs1, uA1, uT1, w);
  // sea: flat, with a 50 km graticule and a faint shelf glow along the coast
  vec2 gq = w / 10.; vec2 gf = fwidth(gq);
  vec2 gl = 1. - smoothstep(vec2(0.), gf * 1.2, abs(fract(gq - 0.5) - 0.5));
  vec3 sea = SEA + vec3(0.03) * max(gl.x, gl.y) * clamp(1. - max(gf.x, gf.y) * 6., 0., 1.) + vec3(0.025) * smoothstep(0.05, 0.46, vC);
  col = mix(sea, col, land);
  float d = length(vec3(vW.x, vW.y, vW.z) - uCam);
  col = mix(col, SEA, smoothstep(uFog0, uFog1, d) * 0.9);
  col = mix(col, SEA, edge);
  gl_FragColor = vec4(col, 1.);
}`;

const mkTex = () => {
  const t = new THREE.DataTexture(new Uint8Array(VS_N * VS_N), VS_N, VS_N, THREE.RedFormat, THREE.UnsignedByteType);
  t.minFilter = t.magFilter = THREE.LinearFilter;
  return t;
};

type R = { r: THREE.WebGLRenderer; scene: THREE.Scene; cam: THREE.PerspectiveCamera; mat: THREE.ShaderMaterial; tex: THREE.DataTexture[] };

/** 3D relief on the GPU: smooth normals, contour lines, per-pixel line-of-sight / cover overlays, whole-region view distance. */
export const TerrainGL: React.FC<{ cam: Cam; layers: Layers }> = ({ cam, layers }) => {
  const ref = useRef<HTMLCanvasElement>(null);
  const st = useRef<R | null>(null);
  useLayoutEffect(() => {
    if (!st.current) {
      const r = new THREE.WebGLRenderer({ canvas: ref.current!, antialias: true, preserveDrawingBuffer: true });
      r.setPixelRatio(SCALE); // backing store at output resolution, CSS size stays 1920x1080
      r.setSize(W, H, false);
      r.outputColorSpace = THREE.LinearSRGBColorSpace;
      const tex = [mkTex(), mkTex()];
      const mat = new THREE.ShaderMaterial({
        vertexShader: VERT, fragmentShader: FRAG, extensions: { derivatives: true } as never,
        uniforms: {
          uCam: { value: new THREE.Vector3() }, uSize: { value: new THREE.Vector2(GRID.w - 1, GRID.h - 1) }, uPad: { value: PAD }, uFog0: { value: 100 }, uFog1: { value: 300 },
          uVs0: { value: new THREE.Vector4() }, uVs1: { value: new THREE.Vector4() },
          uA0: { value: new THREE.Vector2() }, uA1: { value: new THREE.Vector2() },
          uT0: { value: tex[0] }, uT1: { value: tex[1] },
        },
      });
      const scene = new THREE.Scene();
      scene.background = new THREE.Color(10 / 255, 11 / 255, 13 / 255);
      const mesh = new THREE.Mesh(geometry(), mat);
      mesh.frustumCulled = false;
      scene.add(mesh);
      const camera = new THREE.PerspectiveCamera(50, W / H, 0.5, 1500);
      camera.up.set(0, 0, 1);
      st.current = { r, scene, cam: camera, mat, tex };
    }
    const { r, scene, cam: pc, mat, tex } = st.current;
    pc.fov = cam.fovDeg;
    pc.setViewOffset(W, H, 0, H / 2 - CY, W, H); // matches the shifted principal point in cam.project
    pc.updateProjectionMatrix();
    pc.position.set(cam.eye.x, -cam.eye.y, cam.eye.z);
    pc.lookAt(cam.target.x, -cam.target.y, cam.target.z);
    pc.updateMatrixWorld();
    (mat.uniforms.uCam.value as THREE.Vector3).set(cam.eye.x, -cam.eye.y, cam.eye.z);
    mat.uniforms.uFog0.value = cam.dist * 2.2;
    mat.uniforms.uFog1.value = cam.dist * 5.5;
    for (let k = 0; k < 2; k++) {
      const ly = layers[k];
      const vs = mat.uniforms[`uVs${k}`].value as THREE.Vector4;
      const a = mat.uniforms[`uA${k}`].value as THREE.Vector2;
      const data = tex[k].image.data as Uint8Array;
      if (ly) {
        vs.set(ly.vs.x0, ly.vs.y0, ly.vs.res, ly.vs.n);
        a.set(ly.los, ly.cover);
        for (let i = 0; i < data.length; i++) data[i] = Math.min(255, ly.vs.vis[i] * 255);
        tex[k].needsUpdate = true;
      } else {
        a.set(0, 0);
      }
    }
    r.render(scene, pc);
  });
  return <canvas ref={ref} width={W * SCALE} height={H * SCALE} style={{ position: "absolute", left: 0, top: 0, width: W, height: H }} />;
};
