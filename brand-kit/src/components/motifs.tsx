import type { CSSProperties, ReactNode } from "react";
import { c, font, mono } from "../tokens";

export const Tag = ({ children, tone = "grey", size = 14 }: { children: ReactNode; tone?: "grey" | "orange" | "stone"; size?: number }) => {
  const col = tone === "orange" ? c.orange : tone === "stone" ? c.stone : c.grey;
  return <span style={{ display: "inline-block", fontFamily: mono, fontSize: size, letterSpacing: size * 0.1, color: col, border: `1px solid ${tone === "orange" ? c.orange : "#444"}`, borderRadius: 3, padding: `${size * 0.3}px ${size * 0.7}px`, textTransform: "uppercase" }}>{children}</span>;
};

export const Card = ({ label, children, accent, style }: { label?: string; children: ReactNode; accent?: boolean; style?: CSSProperties }) => (
  <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderTop: accent ? `3px solid ${c.orange}` : `1px solid ${c.border}`, borderRadius: 6, padding: 28, ...style }}>
    {label && <div style={{ fontFamily: mono, fontSize: 14, letterSpacing: 2.4, color: c.grey, marginBottom: 18 }}>{label}</div>}
    {children}
  </div>
);

export const Telemetry = ({ k, v, size = 16 }: { k: string; v: string; size?: number }) => (
  <div style={{ display: "flex", justifyContent: "space-between", gap: 24, fontFamily: mono, fontSize: size, padding: `${size * 0.5}px 0`, borderBottom: `1px solid ${c.border}` }}>
    <span style={{ color: c.grey }}>{k}</span><span style={{ color: c.stone }}>{v}</span>
  </div>
);

export const Divider = ({ w, kind = "solid" }: { w: number; kind?: "solid" | "dashed" | "ticks" }) => (
  <svg width={w} height={10}>
    {kind === "ticks"
      ? Array.from({ length: Math.floor(w / 12) }, (_, i) => <line key={i} x1={i * 12 + 1} x2={i * 12 + 1} y1={i % 5 ? 4 : 0} y2={10} stroke={c.grey} />)
      : <line x1={0} x2={w} y1={5} y2={5} stroke={kind === "dashed" ? c.orange : c.border} strokeWidth={kind === "dashed" ? 1.5 : 1} strokeDasharray={kind === "dashed" ? "6 6" : undefined} />}
  </svg>
);

/** Corner-bracket frame, used to call out a region. */
export const Callout = ({ x, y, w, h, label }: { x: number; y: number; w: number; h: number; label?: string }) => {
  const L = 16;
  return (
    <g>
      <path d={`M${x} ${y + L} V${y} H${x + L} M${x + w - L} ${y} H${x + w} V${y + L} M${x + w} ${y + h - L} V${y + h} H${x + w - L} M${x + L} ${y + h} H${x} V${y + h - L}`} stroke={c.orange} strokeWidth={2} fill="none" />
      {label && <text x={x} y={y - 10} fill={c.orange} fontFamily={mono} fontSize={13} letterSpacing={2}>{label}</text>}
    </g>
  );
};

/** Section header: mono kicker + big title. */
export const SectionTitle = ({ kicker, title, size = 64 }: { kicker: string; title: string; size?: number }) => (
  <div>
    <div style={{ fontFamily: mono, fontSize: 18, letterSpacing: 4, color: c.orange, marginBottom: 18 }}>{kicker}</div>
    <div style={{ fontFamily: font, fontSize: size, fontWeight: 700, color: c.white, letterSpacing: -size * 0.03, lineHeight: 1.04 }}>{title}</div>
  </div>
);

const ic = { fill: "none", stroke: c.stone, strokeWidth: 2.5, strokeLinecap: "round", strokeLinejoin: "round" } as const;
export const Icon = ({ kind, size = 56 }: { kind: "learn" | "transfer" | "validate" | "partition"; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 48 48">
    {kind === "learn" && <><path d="M8 38 V10" {...ic} /><path d="M8 38 H40" {...ic} /><path d="M12 32 C18 30 20 20 26 20 S34 12 40 10" {...ic} stroke={c.orange} /></>}
    {kind === "transfer" && <><rect x="4" y="16" width="14" height="16" rx="2" {...ic} /><rect x="30" y="16" width="14" height="16" rx="2" {...ic} /><path d="M20 24 H28 M25 20 L29 24 L25 28" {...ic} stroke={c.orange} /></>}
    {kind === "validate" && <><path d="M24 5 L40 11 V24 C40 33 33 40 24 43 C15 40 8 33 8 24 V11Z" {...ic} /><path d="M16 24 L22 30 L33 18" {...ic} stroke={c.orange} /></>}
    {kind === "partition" && <><rect x="4" y="18" width="12" height="12" rx="2" {...ic} /><rect x="32" y="18" width="12" height="12" rx="2" {...ic} /><path d="M18 24 H22 M26 24 H30" {...ic} /><path d="M24 10 V38" {...ic} stroke={c.orange} strokeDasharray="3 5" /></>}
  </svg>
);
