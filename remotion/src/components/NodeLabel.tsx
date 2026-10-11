import { theme } from "../styles/theme";

export const NodeLabel: React.FC<{ x: number; y: number; id: string; opacity: number; active?: boolean }> = ({ x, y, id, opacity, active }) => (
  <g opacity={opacity}>
    <text x={x + 34} y={y - 30} fill={active ? theme.accent : theme.primary} fontFamily={theme.fontFamily} fontSize={19} fontWeight={700} letterSpacing={3} style={{ paintOrder: "stroke", stroke: "#0A0A0A", strokeWidth: 5 }}>
      {id}
    </text>
    <path d={`M${x + 16} ${y - 16} L${x + 30} ${y - 26}`} stroke={theme.muted} strokeWidth={1} />
  </g>
);

export const HaloRing: React.FC<{ x: number; y: number; r: number; opacity: number; t: number; spin?: boolean }> = ({ x, y, r, opacity, t, spin }) =>
  opacity < 0.01 ? null : (
    <g opacity={opacity}>
      <circle cx={x} cy={y} r={r} fill="none" stroke={theme.accent} strokeWidth={2.5} strokeDasharray={spin ? "14 10" : undefined} transform={spin ? `rotate(${t * 220} ${x} ${y})` : undefined} />
      <circle cx={x} cy={y} r={r + ((t * 40) % 24)} fill="none" stroke={theme.accent} strokeWidth={1} opacity={1 - ((t * 40) % 24) / 24} />
    </g>
  );
