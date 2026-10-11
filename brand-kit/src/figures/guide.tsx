import type { ReactNode } from "react";
import { FixedWing } from "../components/FixedWing";
import { Callout, Card, Divider, Icon, SectionTitle, Tag, Telemetry } from "../components/motifs";
import { ArrowDefs, Canvas } from "../components/primitives";
import { c, font, mono } from "../tokens";
import { logoUri } from "./logos";

export const GW = 1920, GH = 3480;

const Sec = ({ n, title, top, children }: { n: string; title: string; top: number; children: ReactNode }) => (
  <div style={{ position: "absolute", left: 80, right: 80, top }}>
    <div style={{ display: "flex", alignItems: "baseline", gap: 24, borderBottom: `1px solid ${c.border}`, paddingBottom: 16, marginBottom: 36 }}>
      <span style={{ fontFamily: mono, fontSize: 18, letterSpacing: 4, color: c.orange }}>{n}</span>
      <span style={{ fontSize: 36, fontWeight: 700, color: c.white, letterSpacing: -1 }}>{title}</span>
    </div>
    {children}
  </div>
);
const Note = ({ children }: { children: ReactNode }) => <div style={{ fontFamily: mono, fontSize: 14, letterSpacing: 1.5, color: c.grey, marginTop: 14, lineHeight: 1.6 }}>{children}</div>;

export const BrandGuide = () => (
  <Canvas w={GW} h={GH}>
    <div style={{ position: "absolute", left: 80, top: 70 }}><SectionTitle kicker="BRAND GUIDE · v2" title="ARCHIPELAGO identity system" size={84} /></div>
    <div style={{ position: "absolute", left: 80, top: 300, width: 1100, fontSize: 26, lineHeight: 1.4, color: c.stone }}>Decentralized learning for collaborative autonomous platforms. Defense and autonomy first; broad enough for search and rescue, robotics, disaster response and edge systems. Dark-mode first. Black dominant, orange as an accent.</div>

    <Sec n="01" title="Logo" top={440}>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.1fr) minmax(0,1.4fr) minmax(0,0.7fr)", gap: 24 }}>
        <Card label="PRIMARY LOCKUP · DARK" style={{ height: 470, display: "flex", alignItems: "center", justifyContent: "center" }}><img src={logoUri("primary", "dark")} height={300} /></Card>
        <Card label="HORIZONTAL · DARK" style={{ height: 470, display: "flex", alignItems: "center", justifyContent: "center" }}><img src={logoUri("horizontal", "dark")} width={620} /></Card>
        <Card label="ICON" style={{ height: 470, display: "flex", alignItems: "center", justifyContent: "center" }}><img src={logoUri("icon", "dark")} height={230} /></Card>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.1fr) minmax(0,1.4fr) minmax(0,0.7fr)", gap: 24, marginTop: 24 }}>
        <div style={{ background: "#EDE7DF", borderRadius: 6, height: 360, display: "flex", alignItems: "center", justifyContent: "center" }}><img src={logoUri("stacked", "light")} height={260} /></div>
        <div style={{ background: "#EDE7DF", borderRadius: 6, height: 360, display: "flex", alignItems: "center", justifyContent: "center" }}><img src={logoUri("horizontal", "light")} width={700} /></div>
        <div style={{ background: "#EDE7DF", borderRadius: 6, height: 360, display: "flex", alignItems: "center", justifyContent: "center" }}><img src={logoUri("icon", "light")} height={200} /></div>
      </div>
      <Note>CLEARSPACE = HEIGHT OF ONE ORANGE NODE ON ALL SIDES · MIN ICON 24 PX · MIN LOCKUP WIDTH 160 PX · DO NOT RECOLOR, ROTATE, OUTLINE OR PLACE ON BUSY IMAGERY · LIGHT FILES ARE FOR LIGHT BACKGROUNDS ONLY</Note>
    </Sec>

    <Sec n="02" title="Color" top={1580}>
      <div style={{ display: "grid", gridTemplateColumns: "6fr 3fr 1fr 1fr 1fr", gap: 0, height: 200, borderRadius: 6, overflow: "hidden", border: `1px solid ${c.border}` }}>
        {[["BLACK", "#0A0A0A", c.white, "60%"], ["STONE / WHITE", "#EDE7DF", "#0A0A0A", "30%"], ["ORANGE", "#F47B3C", "#0A0A0A", "≤10%"], ["GREY", "#8A8A8A", "#0A0A0A", "LABELS"], ["SURFACE", "#141414", c.white, "PANELS"]].map(([n, hex, fg, p]) => (
          <div key={n} style={{ background: hex, color: fg, padding: 20, fontFamily: mono, fontSize: 14, letterSpacing: 1.5, display: "flex", flexDirection: "column", justifyContent: "flex-end" }}><b>{n}</b>{hex}<br />{p}</div>
        ))}
      </div>
      <Note>BORDER #333333 · ELEVATED SURFACE #1C1C1C · WHITE #FFFFFF FOR HEADLINES · STATE IS NEVER COLOR-ONLY (ADD SYMBOL OR TEXT)</Note>
    </Sec>

    <Sec n="03" title="Typography" top={1950}>
      <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr 1fr", gap: 24 }}>
        <Card label="DISPLAY · ARIAL BOLD, TIGHT TRACKING"><div style={{ fontSize: 96, fontWeight: 700, letterSpacing: -5, color: c.white, lineHeight: 1 }}>Decentralized<br />learning.</div></Card>
        <Card label="BODY · ARIAL"><div style={{ fontSize: 26, lineHeight: 1.4, color: c.stone }}>Learned capabilities move between autonomous platforms and are validated by the receiver before adoption.</div></Card>
        <Card label="LABELS + TELEMETRY · CONSOLAS"><div style={{ fontFamily: mono, fontSize: 20, letterSpacing: 3, color: c.orange }}>CANDIDATE ACCEPTED</div><div style={{ fontFamily: mono, fontSize: 16, color: c.grey, marginTop: 14, letterSpacing: 1.5 }}>NODE-02 · TICK 4812 · LINK LOST</div></Card>
      </div>
      <Note>SCALE (PX @1920): DISPLAY 80–120 · H1 56–64 · H2 36 · BODY 24–28 · LABEL 14–18 MONO, +10–16% TRACKING</Note>
    </Sec>

    <Sec n="04" title="Spacing + grid" top={2380}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 24 }}>
        {[4, 8, 12, 16, 24, 32, 48, 64, 96].map((s) => <div key={s} style={{ textAlign: "center", fontFamily: mono, fontSize: 14, color: c.grey }}><div style={{ width: s, height: s, background: c.orange, margin: "0 auto 10px" }} />{s}</div>)}
        <div style={{ marginLeft: 60, display: "flex", gap: 20 }}>
          {[["DOT GRID", "radial-gradient(#ffffff2a 1.2px, transparent 1.3px) 0 0/32px 32px"], ["GRATICULE", "linear-gradient(#ffffff14 1px, transparent 1px) 0 0/40px 40px, linear-gradient(90deg,#ffffff14 1px, transparent 1px) 0 0/40px 40px"]].map(([n, bg]) => (
            <div key={n} style={{ width: 260, height: 130, border: `1px solid ${c.border}`, background: bg, fontFamily: mono, fontSize: 13, color: c.grey, padding: 10 }}>{n}</div>
          ))}
        </div>
      </div>
    </Sec>

    <Sec n="05" title="UI motifs" top={2700}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 24 }}>
        <Card label="CARD · ACCENT" accent><div style={{ fontSize: 28, fontWeight: 700, color: c.white }}>Recipient-side validation</div></Card>
        <Card label="TELEMETRY"><Telemetry k="NODE-01" v="LINKED" /><Telemetry k="OFFER" v="ACCEPTED" /></Card>
        <Card label="TAGS"><div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}><Tag>Grey</Tag><Tag tone="stone">Stone</Tag><Tag tone="orange">Alert</Tag></div><div style={{ marginTop: 22 }}><Divider w={300} /><Divider w={300} kind="dashed" /><Divider w={300} kind="ticks" /></div></Card>
        <Card label="ICONS · 2.5 PX STROKE"><div style={{ display: "flex", gap: 16 }}>{(["learn", "transfer", "validate", "partition"] as const).map((k) => <Icon key={k} kind={k} size={52} />)}</div></Card>
      </div>
      <div style={{ marginTop: 24, display: "grid", gridTemplateColumns: "1fr 2fr", gap: 24 }}>
        <Card label="CALLOUT FRAME"><svg width={300} height={110}><Callout x={20} y={22} w={250} h={70} label="REGION OF INTEREST" /></svg></Card>
        <Card label="DIAGRAM LANGUAGE">
          <svg width={900} height={130}><ArrowDefs />
            <FixedWing x={60} y={60} size={70} heading={90} accent /><line x1={110} y1={60} x2={250} y2={60} stroke={c.stone} strokeWidth={2} markerEnd="url(#ah)" /><text x={110} y={100} fill={c.grey} fontFamily={mono} fontSize={13}>LIVE LINK</text>
            <rect x={160} y={52} width={16} height={16} fill={c.orange} /><text x={200} y={32} fill={c.grey} fontFamily={mono} fontSize={13}>CANDIDATE</text>
            <line x1={300} y1={60} x2={430} y2={60} stroke={c.grey} strokeWidth={2} strokeDasharray="5 7" /><text x={300} y={100} fill={c.grey} fontFamily={mono} fontSize={13}>LINK LOST</text>
            <FixedWing x={480} y={60} size={70} heading={90} /><rect x={560} y={30} width={150} height={60} rx={3} fill="none" stroke={c.orange} strokeWidth={2} strokeDasharray="6 5" /><text x={575} y={66} fill={c.orange} fontFamily={mono} fontSize={13}>VALIDATE</text>
            <circle cx={815} cy={55} r={14} fill={c.bg} stroke={c.orange} strokeWidth={3} /><circle cx={815} cy={55} r={4} fill={c.orange} /><text x={760} y={110} fill={c.grey} fontFamily={mono} fontSize={13}>COMMAND NODE</text>
          </svg>
        </Card>
      </div>
    </Sec>
  </Canvas>
);
