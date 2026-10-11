import { theme } from "../styles/theme";

// Callouts live in fixed lanes (a, b left; c, d right, in the bottom band) so they never move or collide; a leader line follows the thing they describe.
const LANES = { a: { x: 560, y: 762 }, b: { x: 560, y: 856 }, c: { x: 1110, y: 762 }, d: { x: 1110, y: 856 } };

type Props = {
  title: string;
  sub?: string;
  opacity: number;
  slot: keyof typeof LANES;
  /** screen position of the node / track this callout is about */
  at?: [number, number];
  tone?: "accent" | "muted";
};

const box: React.CSSProperties = {
  display: "inline-flex",
  flexDirection: "column",
  gap: 6,
  padding: "13px 20px 13px 18px",
  background: "rgba(10,10,10,0.9)",
  border: "1px solid rgba(237,231,223,0.16)",
  fontFamily: theme.fontFamily,
  whiteSpace: "nowrap",
};

export const EventBadge: React.FC<Props> = ({ title, sub, opacity, slot, at, tone = "accent" }) => {
  if (opacity < 0.02) return null;
  const w = Math.max(title.length * 15.2, (sub?.length ?? 0) * 8.6) + 46;
  const h = sub ? 84 : 54;
  const { x, y } = LANES[slot];
  const rail = tone === "accent" ? theme.accent : theme.muted;
  let leader: JSX.Element | null = null;
  if (at) {
    const px = Math.min(Math.max(at[0], x), x + w), py = Math.min(Math.max(at[1], y), y + h);
    if (Math.hypot(at[0] - px, at[1] - py) > 24)
      leader = (
        <g opacity={opacity * 0.7}>
          <line x1={px} y1={py} x2={at[0]} y2={at[1]} stroke={rail} strokeWidth={1.6} strokeDasharray="3 5" />
          <circle cx={at[0]} cy={at[1]} r={5} fill="none" stroke={rail} strokeWidth={2} />
        </g>
      );
  }
  return (
    <>
      {leader}
      <foreignObject x={x} y={y} width={w + 40} height={h + 20} style={{ overflow: "visible" }} opacity={opacity}>
        <div style={{ transform: `translateY(${(1 - opacity) * 8}px)` }}>
          <div style={{ ...box, borderLeft: `4px solid ${rail}`, borderRadius: theme.borderRadius }}>
            <span style={{ fontSize: 20, fontWeight: 700, letterSpacing: 3.5, color: theme.textPrimary }}>{title}</span>
            {sub && <span style={{ fontSize: 16, color: theme.primary, opacity: 0.8, letterSpacing: 0.5 }}>{sub}</span>}
          </div>
        </div>
      </foreignObject>
    </>
  );
};
