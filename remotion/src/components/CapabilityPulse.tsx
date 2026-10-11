import { theme } from "../styles/theme";

/** gently bowed link between two screen points */
export const linkPath = (a: [number, number], b: [number, number], bow = 0.07) => {
  const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
  const nx = -(b[1] - a[1]) * bow, ny = (b[0] - a[0]) * bow;
  return { d: `M${a[0]} ${a[1]} Q${mx + nx} ${my + ny} ${b[0]} ${b[1]}`, mid: [mx + nx / 2, my + ny / 2] as [number, number] };
};

type Pt = [number, number];

/** Directional capability transfer along the same bowed edge as the link. p: 0..1 progress of the artifact. */
export const CapabilityPulse: React.FC<{ a: Pt; b: Pt; p: number; opacity: number }> = ({ a, b, p, opacity }) => {
  if (opacity < 0.01) return null;
  const { d } = linkPath(a, b);
  // point on the quadratic for the artifact head
  const q = (s: number): Pt => {
    const c = linkPath(a, b);
    const cx = 2 * c.mid[0] - (a[0] + b[0]) / 2;
    const cy = 2 * c.mid[1] - (a[1] + b[1]) / 2;
    return [(1 - s) * (1 - s) * a[0] + 2 * (1 - s) * s * cx + s * s * b[0], (1 - s) * (1 - s) * a[1] + 2 * (1 - s) * s * cy + s * s * b[1]];
  };
  const head = q(p);
  const len = 1000; // dash trick: pathLength normalised
  return (
    <g opacity={opacity}>
      <path d={d} fill="none" stroke={theme.accent} strokeWidth={1.6} strokeOpacity={0.35} />
      <path d={d} fill="none" stroke={theme.accent} strokeWidth={2.4} pathLength={len} strokeDasharray={`${p * len} ${len}`} strokeLinecap="round" />
      {[0.04, 0.08, 0.12].map((o, i) => {
        const s = q(Math.max(0, p - o));
        return <circle key={i} cx={s[0]} cy={s[1]} r={3 - i * 0.7} fill={theme.accent} opacity={0.6 - i * 0.18} />;
      })}
      <circle cx={head[0]} cy={head[1]} r={16} fill={theme.accent} opacity={0.16} />
      {/* artifact: a small package, not a coordinate */}
      <rect x={head[0] - 7} y={head[1] - 7} width={14} height={14} fill={theme.background} stroke={theme.accent} strokeWidth={2} transform={`rotate(45 ${head[0]} ${head[1]})`} />
      <rect x={head[0] - 2.5} y={head[1] - 2.5} width={5} height={5} fill={theme.accent} transform={`rotate(45 ${head[0]} ${head[1]})`} />
    </g>
  );
};
