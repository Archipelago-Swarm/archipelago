import { c } from "../tokens";

// Plan view of the loyal-wingman UAV modelled for the demo video (remotion/src/components/Uav3D.tsx):
// long pointed nose, swept tapered wings, canted twin tails. Model units, x forward, y right; length 62.
const NOSE: [number, number] = [31, 0], R1: [number, number] = [14, 3.4], R2: [number, number] = [-8, 4.6], RT: [number, number] = [-31, 3.2];
// Proportions per belly-view photos of the YFQ-44A class: slim fuselage, short clipped swept wing (span ~0.5 of length), small rear stabilisers.
const WING = [[4, 4.2], [-9, 16], [-14.5, 15.6], [-11, 5]] as [number, number][];
const FIN = [[-23, 3.4], [-30, 10], [-32.5, 9.6], [-31, 3.2]] as [number, number][];
const K = 100 / 62; // model -> glyph units (nose-to-tail = 100, nose up)
const pt = ([x, y]: [number, number], side: 1 | -1) => `${(side * y * K).toFixed(2)},${(-x * K).toFixed(2)}`;
const poly = (p: [number, number][], side: 1 | -1) => p.map((q) => pt(q, side)).join(" ");
const BODY = [NOSE, R1, R2, RT];

/** Top-down UAV silhouette matching the Remotion demo model, nose up at heading 0. `size` is a nominal px size (glyph is drawn 1.4x so it matches the old glyph weight). */
export const FixedWing = ({ x, y, size = 60, heading = 0, color = c.stone, accent = false }: { x: number; y: number; size?: number; heading?: number; color?: string; accent?: boolean }) => (
  <g transform={`translate(${x},${y}) rotate(${heading}) scale(${(size * 1.4) / 100})`} strokeLinejoin="round" stroke={c.bg} strokeWidth={4} strokeOpacity={1} paintOrder="stroke">
    {[1, -1].map((s) => <polygon key={"w" + s} points={poly(WING, s as 1 | -1)} fill={color} fillOpacity={0.82} />)}
    {[1, -1].map((s) => <polygon key={"f" + s} points={poly(FIN, s as 1 | -1)} fill={color} fillOpacity={0.7} />)}
    <line x1={0} y1={-NOSE[0] * K} x2={0} y2={-(NOSE[0] + 6) * K} stroke={color} strokeWidth={1.6} strokeOpacity={0.9} />
    <polygon points={`${poly(BODY, 1)} ${poly([RT, R2, R1], -1)}`} fill={color} />
    <circle cx={0} cy={-20} r={3} fill={accent ? c.orange : c.bg} stroke="none" />
  </g>
);
