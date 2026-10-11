import type { ReactNode } from "react";
import { BrandLogo, Canvas, GridBackground } from "../components/primitives";
import { c, mono, TAGLINE_CAPS } from "../tokens";

export const W = 1920, H = 1080, TOTAL = 11;

/** Common 16:9 chrome: logo + section counter on top, slogan + note on the bottom. Content is positioned absolutely by each slide. */
export const Slide = ({ n, label, note, children, grid = true }: { n: number; label: string; note?: string; children: ReactNode; grid?: boolean }) => (
  <Canvas w={W} h={H}>
    {grid && <GridBackground w={W} h={H} step={40} />}
    {children}
    <div style={{ position: "absolute", left: 80, top: 44, display: "flex", alignItems: "center", gap: 16 }}>
      <BrandLogo size={40} />
      <span style={{ fontWeight: 700, fontSize: 20, letterSpacing: 4, color: c.white }}>ARCHIPELAGO</span>
    </div>
    <div style={{ position: "absolute", right: 80, top: 54, fontFamily: mono, fontSize: 16, letterSpacing: 3, color: c.grey }}>{String(n).padStart(2, "0")} / {TOTAL} · {label}</div>
    <div style={{ position: "absolute", left: 80, right: 80, bottom: 40, display: "flex", justifyContent: "space-between", fontFamily: mono, fontSize: 15, letterSpacing: 2.5 }}>
      <span style={{ color: c.grey }}>{note ?? ""}</span><span style={{ color: c.orange }}>{TAGLINE_CAPS}</span>
    </div>
  </Canvas>
);

export const P = ({ children, size = 28, color = c.stone, w, style }: { children: ReactNode; size?: number; color?: string; w?: number; style?: React.CSSProperties }) => (
  <div style={{ fontSize: size, lineHeight: 1.35, color, maxWidth: w, ...style }}>{children}</div>
);
