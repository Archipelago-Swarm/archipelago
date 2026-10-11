// One-time: turns the Taiwan Strait land-fraction mask used by the demo (remotion/src/world/dem.ts, derived from the
// supplied topographic reference) into SVG paths at assets/strait-coast.json. Not part of the normal render.
import fs from "node:fs";
const s = fs.readFileSync(new URL("../../remotion/src/world/dem.ts", import.meta.url), "utf8");
const W = +s.match(/DEM_W\s*=\s*(\d+)/)[1], H = +s.match(/DEM_H\s*=\s*(\d+)/)[1];
const a = Buffer.from(s.match(/COAST_B64\s*=\s*"([^"]+)"/)[1], "base64");
const v = (x, y) => (x < 0 || y < 0 || x >= W || y >= H ? -0.5 : a[y * W + x] / 255 - 0.5); // sea outside the grid
const interp = (p, q, fp, fq) => { const t = fp / (fp - fq); return [p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t]; };
const segs = [];
for (let y = -1; y < H; y++) for (let x = -1; x < W; x++) {
  const c = [[x, y], [x + 1, y], [x + 1, y + 1], [x, y + 1]], f = c.map(([i, j]) => v(i, j));
  const pts = [];
  for (let k = 0; k < 4; k++) { const k2 = (k + 1) % 4; if ((f[k] > 0) !== (f[k2] > 0)) pts.push(interp(c[k], c[k2], f[k], f[k2])); }
  if (pts.length === 2) segs.push(pts); else if (pts.length === 4) segs.push([pts[0], pts[1]], [pts[2], pts[3]]);
}
const key = (p) => p[0].toFixed(3) + "," + p[1].toFixed(3);
const chain = (ss) => {
  const m = new Map(); ss.forEach((sg, i) => sg.forEach((p) => { const k = key(p); (m.get(k) ?? m.set(k, []).get(k)).push(i); }));
  const used = new Set(), out = [];
  for (let i = 0; i < ss.length; i++) {
    if (used.has(i)) continue; used.add(i);
    let line = [...ss[i]];
    for (const dir of [1, 0]) for (;;) {
      const end = dir ? line[line.length - 1] : line[0];
      const nx = (m.get(key(end)) ?? []).find((j) => !used.has(j)); if (nx === undefined) break;
      used.add(nx); const [p, q] = ss[nx]; const nxt = key(p) === key(end) ? q : p;
      dir ? line.push(nxt) : line.unshift(nxt);
    }
    out.push(line);
  }
  return out;
};
const chaikin = (l, closed) => { const o = []; for (let i = 0; i < l.length - (closed ? 0 : 1); i++) { const p = l[i], q = l[(i + 1) % l.length]; o.push([0.75 * p[0] + 0.25 * q[0], 0.75 * p[1] + 0.25 * q[1]], [0.25 * p[0] + 0.75 * q[0], 0.25 * p[1] + 0.75 * q[1]]); } return o; };
const d = (l, closed) => { let q = chaikin(chaikin(l, closed), closed); return "M" + q.map((p) => p[0].toFixed(2) + " " + p[1].toFixed(2)).join("L") + (closed ? "Z" : ""); };
const closed = (l) => key(l[0]) === key(l[l.length - 1]);
const fill = chain(segs).filter((l) => l.length > 4).map((l) => d(closed(l) ? l.slice(0, -1) : l, true));
const inside = (p) => p[0] >= 0 && p[0] <= W - 1 && p[1] >= 0 && p[1] <= H - 1;
const coast = chain(segs.filter((sg) => sg.every(inside))).filter((l) => l.length > 4).map((l) => d(closed(l) ? l.slice(0, -1) : l, closed(l)));
fs.writeFileSync(new URL("../assets/strait-coast.json", import.meta.url), JSON.stringify({ W, H, fill, coast }));
console.log(W, H, fill.length, coast.length);
