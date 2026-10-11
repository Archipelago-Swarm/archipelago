import { Ctx } from "../ctx";
import { theme } from "../styles/theme";
import { H, los, V3 } from "../world/geo";
import { P } from "../world/paths";

export const poly = (pts: [number, number][]) => pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");

/** ring lying on the terrain */
export const groundRing = (ctx: Ctx, c: P, r: number, n = 56): [number, number][] =>
  Array.from({ length: n + 1 }, (_, k) => {
    const a = (k / n) * Math.PI * 2;
    return ctx.gnd(c.x + r * Math.cos(a), c.y + r * Math.sin(a));
  });

export const Marker: React.FC<{ ctx: Ctx; p: P; label: string; sub?: string; o: number; unc: number; lost?: number }> = ({ ctx, p, label, sub, o, unc, lost = 0 }) => {
  if (o < 0.01) return null;
  const [x, y] = ctx.gnd(p.x, p.y);
  return (
    <g opacity={o}>
      <polyline points={poly(groundRing(ctx, p, unc, 36))} fill={theme.accent} fillOpacity={0.1 + 0.1 * lost} stroke={theme.accent} strokeOpacity={0.7} strokeDasharray={lost > 0.4 ? "3 4" : undefined} strokeWidth={1.2} />
      <path d={`M${x} ${y - 15} L${x + 12} ${y} L${x} ${y + 15} L${x - 12} ${y} Z`} fill="none" stroke={theme.accent} strokeWidth={3} />
      <circle cx={x} cy={y} r={3.2} fill={theme.accent} />
      <text x={x + 22} y={y + 34} fill={theme.accent} fontFamily={theme.fontFamily} fontSize={17} fontWeight={700} letterSpacing={3} style={{ paintOrder: "stroke", stroke: "#0A0A0A", strokeWidth: 4 }}>{label}</text>
      {sub && <text x={x + 22} y={y + 56} fill={theme.primary} fillOpacity={0.85} fontFamily={theme.fontFamily} fontSize={15} letterSpacing={1} style={{ paintOrder: "stroke", stroke: "#0A0A0A", strokeWidth: 4 }}>{sub}</text>}
    </g>
  );
};

/** sensor line from a UAV to a ground track: stone when clear, broken at the ridge that blocks it */
export const LosRay: React.FC<{ ctx: Ctx; from: V3; to: P; o: number }> = ({ ctx, from, to, o }) => {
  if (o < 0.01) return null;
  const g: V3 = { x: to.x, y: to.y, z: H(to.x, to.y) + 0.03 };
  const r = los(from, g);
  const a = ctx.proj(from);
  const end = r.clear ? ctx.proj(g) : ctx.proj({ x: from.x + (g.x - from.x) * r.t, y: from.y + (g.y - from.y) * r.t, z: from.z + (g.z - from.z) * r.t });
  const b = ctx.proj(g);
  return (
    <g opacity={o}>
      <line x1={a[0]} y1={a[1]} x2={end[0]} y2={end[1]} stroke={r.clear ? theme.primary : theme.muted} strokeOpacity={r.clear ? 0.75 : 0.6} strokeWidth={1.4} strokeDasharray={r.clear ? undefined : "4 4"} />
      {!r.clear && (
        <>
          <line x1={end[0]} y1={end[1]} x2={b[0]} y2={b[1]} stroke={theme.muted} strokeOpacity={0.3} strokeDasharray="2 6" />
          <path d={`M${end[0] - 6} ${end[1] - 6} L${end[0] + 6} ${end[1] + 6} M${end[0] + 6} ${end[1] - 6} L${end[0] - 6} ${end[1] + 6}`} stroke={theme.accent} strokeWidth={2} />
        </>
      )}
    </g>
  );
};

export const headingDeg = (ctx: Ctx, i: number) => {
  const n = ctx.nodes[i];
  const q = ctx.proj({ x: n.x + n.hx * 0.6, y: n.y + n.hy * 0.6, z: n.z });
  return (Math.atan2(q[1] - ctx.scr[i][1], q[0] - ctx.scr[i][0]) * 180) / Math.PI;
};
