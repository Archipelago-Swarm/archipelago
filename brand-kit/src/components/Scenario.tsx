import { c, mono } from "../tokens";
import { FixedWing } from "./FixedWing";
import { StraitMap } from "./StraitMap";

type V = [number, number];
const bez = (p: V[], t: number): V => {
  const u = 1 - t;
  return [u ** 3 * p[0][0] + 3 * u * u * t * p[1][0] + 3 * u * t * t * p[2][0] + t ** 3 * p[3][0], u ** 3 * p[0][1] + 3 * u * u * t * p[1][1] + 3 * u * t * t * p[2][1] + t ** 3 * p[3][1]];
};
// Illustrative squadron routes in demo-map cells (Taiwan west coast -> across the strait).
export const ROUTE_A: V[] = [[106, 98], [95, 90], [86, 76], [80, 44]];
export const ROUTE_B: V[] = [[110, 126], [98, 118], [86, 106], [72, 92]];
const heading = (r: V[], t: number) => {
  const a = bez(r, t), b = bez(r, Math.min(1, t + 0.02));
  return (Math.atan2(b[0] - a[0], -(b[1] - a[1])) * 180) / Math.PI;
};
const route = (r: V[], P: (x: number, y: number) => V) => `M${P(...r[0])} C${P(...r[1])} ${P(...r[2])} ${P(...r[3])}`;

/** Squadron over the strait: routes, sensor footprints, comms-denied zone, severed links, capability handoff. All illustrative. */
export const StraitScenario = ({ w, h, view, wing = 56, detail = true }: { w: number; h: number; view: [number, number, number, number]; wing?: number; detail?: boolean }) => (
  <StraitMap w={w} h={h} view={view}>
    {(P, k) => {
      const A = [0.2, 0.5, 0.8].map((t) => ({ p: bez(ROUTE_A, t), hd: heading(ROUTE_A, t) }));
      const B = [0.3, 0.7].map((t) => ({ p: bez(ROUTE_B, t), hd: heading(ROUTE_B, t) }));
      const [a1, a2, a3, b1, b2] = [...A, ...B].map((a) => ({ px: P(...a.p), hd: a.hd }));
      const all = [a1, a2, a3, b1, b2];
      const zone = P(82, 62), zr = 15 * k;
      const cmd = P(106, 98);
      const sw = Math.min(2, Math.max(1.2, k * 0.12));
      const cone = (o: V, hd: number, len: number, half: number) => {
        const l = ((hd - half) * Math.PI) / 180, r = ((hd + half) * Math.PI) / 180;
        return `M${o[0]} ${o[1]} L${o[0] + Math.sin(l) * len} ${o[1] - Math.cos(l) * len} A${len} ${len} 0 0 1 ${o[0] + Math.sin(r) * len} ${o[1] - Math.cos(r) * len}Z`;
      };
      const links: [typeof a1, typeof a1, boolean][] = [[a1, a2, false], [a1, b1, false], [b1, b2, false], [a2, a3, true], [a2, b2, true]];
      const m: V = [(a1.px[0] + b1.px[0]) / 2, (a1.px[1] + b1.px[1]) / 2];
      const z = Math.max(10, k * 1.7);
      return (
        <>
          <defs><pattern id="hatch" width="10" height="10" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="10" stroke={c.orange} strokeOpacity={0.25} strokeWidth={2} /></pattern></defs>
          <circle cx={zone[0]} cy={zone[1]} r={zr} fill="url(#hatch)" stroke={c.orange} strokeOpacity={0.7} strokeDasharray="6 6" strokeWidth={sw * 0.7} />
          {detail && <text x={zone[0]} y={zone[1] - zr * 0.45} textAnchor="middle" fill={c.orange} fontFamily={mono} fontSize={Math.min(24, Math.max(11, k * 1.4))} letterSpacing={4} style={{ paintOrder: "stroke", stroke: c.bg, strokeWidth: 6 }}>COMMS DENIED</text>}
          <path d={route(ROUTE_A, P)} fill="none" stroke={c.stone} strokeOpacity={0.3} strokeWidth={sw} strokeDasharray="1 9" strokeLinecap="round" />
          <path d={route(ROUTE_B, P)} fill="none" stroke={c.stone} strokeOpacity={0.3} strokeWidth={sw} strokeDasharray="1 9" strokeLinecap="round" />
          <path d={cone(a3.px, a3.hd, 11 * k, 24)} fill={c.stone} fillOpacity={0.08} stroke={c.stone} strokeOpacity={0.35} strokeWidth={sw * 0.7} />
          <path d={cone(b2.px, b2.hd, 9 * k, 24)} fill={c.stone} fillOpacity={0.08} stroke={c.stone} strokeOpacity={0.35} strokeWidth={sw * 0.7} />
          {links.map(([p, q, cut], i) => (
            <line key={i} x1={p.px[0]} y1={p.px[1]} x2={q.px[0]} y2={q.px[1]} stroke="#8a8a88" strokeOpacity={cut ? 0.6 : 0.85} strokeWidth={sw} strokeDasharray={cut ? "5 7" : undefined} />
          ))}
          <rect x={m[0] - z / 2} y={m[1] - z / 2} width={z} height={z} fill={c.orange} stroke={c.bg} strokeWidth={3} />
          <circle cx={cmd[0]} cy={cmd[1]} r={11} fill={c.bg} stroke={c.orange} strokeWidth={3} /><circle cx={cmd[0]} cy={cmd[1]} r={3.5} fill={c.orange} />
          {all.map((a, i) => <FixedWing key={i} x={a.px[0]} y={a.px[1]} size={wing * 1.35} heading={a.hd} accent={i === 0 || i === 3} />)}
        </>
      );
    }}
  </StraitMap>
);
