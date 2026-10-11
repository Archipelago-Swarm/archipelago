import type { CSSProperties, ReactNode } from "react";
import { c, font, LOGO_ASPECT, LOGO_SRC, mono, TAGLINE_CAPS } from "../tokens";

export const Canvas = ({ w, h, children }: { w: number; h: number; children: ReactNode }) => (
  <div style={{ position: "relative", width: w, height: h, background: c.bg, overflow: "hidden", fontFamily: font, color: c.stone }}>{children}</div>
);

/** Dot grid like the media kit's network panel, fading toward the edges. */
export const GridBackground = ({ w, h, step = 32 }: { w: number; h: number; step?: number }) => (
  <svg width={w} height={h} style={{ position: "absolute", inset: 0 }}>
    <defs>
      <pattern id="gd" width={step} height={step} patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1.1" fill="#fff" fillOpacity={0.16} /></pattern>
      <radialGradient id="gf" cx="65%" cy="50%" r="70%"><stop offset="0" stopColor="#fff" /><stop offset="1" stopColor="#000" /></radialGradient>
      <mask id="gm"><rect width={w} height={h} fill="url(#gf)" /></mask>
    </defs>
    <rect width={w} height={h} fill="url(#gd)" mask="url(#gm)" />
  </svg>
);

export const BrandLogo = ({ size, style }: { size: number; style?: CSSProperties }) => (
  <img src={LOGO_SRC} width={size * LOGO_ASPECT} height={size} style={{ display: "block", ...style }} />
);

export const Wordmark = ({ size, color = c.white }: { size: number; color?: string }) => (
  <div style={{ fontSize: size, fontWeight: 700, letterSpacing: -size * 0.04, color, lineHeight: 1 }}>ARCHIPELAGO</div>
);

export const SectionLabel = ({ children, size = 14, color = c.orange }: { children: ReactNode; size?: number; color?: string }) => (
  <div style={{ fontSize: size, fontWeight: 700, letterSpacing: size * 0.16, color, textTransform: "uppercase" }}>{children}</div>
);

export const Micro = ({ children, size = 14, color = c.grey }: { children: ReactNode; size?: number; color?: string }) => (
  <div style={{ fontFamily: mono, fontSize: size, letterSpacing: size * 0.05, color }}>{children}</div>
);

export const TechBadge = ({ name, note, planned }: { name: string; note?: string; planned?: boolean }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 5, padding: "11px 16px", border: `1px ${planned ? "dashed" : "solid"} ${planned ? c.orange : "#444"}`, background: c.elevated, borderRadius: 3 }}>
    <span style={{ fontSize: 22, fontWeight: 700, color: c.white, letterSpacing: -0.4 }}>{name}</span>
    {note && <span style={{ fontFamily: mono, fontSize: 12, color: planned ? c.orange : c.grey }}>{note}</span>}
  </div>
);

/** Rectangular architecture node. */
export const ArchNode = ({ x, y, w, h, title, lines = [], accent, dashed }: { x: number; y: number; w: number; h: number; title: string; lines?: string[]; accent?: boolean; dashed?: boolean }) => (
  <g>
    <rect x={x} y={y} width={w} height={h} rx={3} fill={c.elevated} stroke={accent ? c.orange : "#555"} strokeWidth={1.2} strokeDasharray={dashed ? "6 5" : undefined} />
    <text x={x + 16} y={y + 29} fill={c.white} fontSize={16} fontFamily={mono} fontWeight={700}>{title}</text>
    {lines.map((l, i) => <text key={i} x={x + 16} y={y + 55 + i * 20} fill="#aaa" fontSize={14}>{l}</text>)}
  </g>
);

/** Connection with optional arrowheads and a label. Needs <ArrowDefs/> in the same svg. */
export const ConnectionPath = ({ d, label, lx, ly, both, dashed, accent, anchor = "middle" }: { d: string; label?: string; lx?: number; ly?: number; both?: boolean; dashed?: boolean; accent?: boolean; anchor?: "start" | "middle" | "end" }) => (
  <g>
    <path d={d} fill="none" stroke={accent ? c.orange : "#aaa"} strokeWidth={1.6} strokeDasharray={dashed ? "7 6" : undefined} markerEnd="url(#ah)" markerStart={both ? "url(#ah)" : undefined} />
    {label && <text x={lx} y={ly} textAnchor={anchor} fill={c.stone} fontSize={13} fontFamily={mono} style={{ paintOrder: "stroke", stroke: c.bg, strokeWidth: 6 }}>{label}</text>}
  </g>
);
export const ArrowDefs = () => (
  <defs><marker id="ah" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 1 L9 5 L0 9 z" fill="#aaa" /></marker></defs>
);

export const MetricCard = ({ label, value, unit, waiting }: { label: string; value?: string | number; unit?: string; waiting?: boolean }) => (
  <div style={{ padding: "16px 20px", border: `1px solid ${c.border}`, background: c.surface, borderRadius: 6, minWidth: 180 }}>
    <SectionLabel size={11} color={c.grey}>{label}</SectionLabel>
    <div style={{ fontSize: waiting ? 20 : 44, fontWeight: 700, color: waiting ? c.grey : c.white, marginTop: 10, fontFamily: waiting ? mono : font }}>{waiting ? "AWAITING DATA" : value}<span style={{ fontSize: 16, color: c.grey }}> {unit}</span></div>
  </div>
);

export const Footer = ({ w, text }: { w: number; text: string }) => (
  <div style={{ position: "absolute", left: 64, bottom: 34, width: w - 128, display: "flex", justifyContent: "space-between" }}>
    <Micro>{text}</Micro><Micro color={c.orange}>{TAGLINE_CAPS}</Micro>
  </div>
);

export const Header = ({ w, label, title }: { w: number; label: string; title: string }) => (
  <div style={{ position: "absolute", left: 64, top: 52, width: w - 128, display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <SectionLabel>{label}</SectionLabel>
      <div style={{ fontSize: 48, fontWeight: 700, color: c.white, letterSpacing: -2 }}>{title}</div>
    </div>
    <BrandLogo size={64} />
  </div>
);
