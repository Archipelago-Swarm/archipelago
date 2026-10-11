import type { ReactNode } from "react";
import { FixedWing } from "../components/FixedWing";
import { StraitScenario } from "../components/Scenario";
import { Tag } from "../components/motifs";
import { ArrowDefs, BrandLogo, Canvas, GridBackground, Wordmark } from "../components/primitives";
import { c, DESC, mono, TAGLINE, TAGLINE_CAPS } from "../tokens";

const fade = (x: number, w: number, h: number) => <div style={{ position: "absolute", left: x, top: 0, width: w, height: h, background: `linear-gradient(90deg, ${c.bg} 10%, rgba(10,10,10,0))` }} />;

/** Devpost 3:2 thumbnail, designed at 1500x1000 (export @2x = 3000x2000). */
export const DevpostThumb = ({ w = 1500, h = 1000 }: { w?: number; h?: number }) => (
  <Canvas w={w} h={h}>
    <div style={{ position: "absolute", left: 560, top: 0 }}><StraitScenario w={940} h={1000} view={[66, 56, 128, 118.4]} wing={66} detail={false} /></div>
    {fade(560, 300, h)}
    <div style={{ position: "absolute", left: 80, top: 0, bottom: 0, display: "flex", flexDirection: "column", justifyContent: "center", gap: 34 }}>
      <BrandLogo size={210} />
      <Wordmark size={100} />
      <div style={{ fontFamily: mono, fontSize: 25, letterSpacing: 6, color: c.orange }}>{TAGLINE}</div>
      <div style={{ fontSize: 34, lineHeight: 1.25, color: c.stone, maxWidth: 560 }}>{DESC}</div>
    </div>
    <div style={{ position: "absolute", right: 56, top: 52 }}><Tag tone="orange" size={18}>UAV squadrons · contested comms</Tag></div>
  </Canvas>
);

/** GitHub social preview, 1280x640. */
export const GithubSocial = ({ w = 1280, h = 640 }: { w?: number; h?: number }) => (
  <Canvas w={w} h={h}>
    <div style={{ position: "absolute", left: 540, top: 0 }}><StraitScenario w={740} h={640} view={[64, 70, 128, 120]} wing={50} detail={false} /></div>
    {fade(540, 240, h)}
    <div style={{ position: "absolute", left: 70, top: 0, bottom: 0, display: "flex", flexDirection: "column", justifyContent: "center", gap: 26 }}>
      <BrandLogo size={150} />
      <Wordmark size={80} />
      <div style={{ fontSize: 28, color: c.stone, maxWidth: 520, lineHeight: 1.3 }}>{DESC}</div>
      <div style={{ fontFamily: mono, fontSize: 20, letterSpacing: 5, color: c.orange }}>{TAGLINE}</div>
    </div>
  </Canvas>
);

/** README banner, 1600x400. */
export const ReadmeBanner = ({ w = 1600, h = 400 }: { w?: number; h?: number }) => (
  <Canvas w={w} h={h}>
    <GridBackground w={w} h={h} step={32} />
    <div style={{ position: "absolute", left: 760, top: 0 }}><StraitScenario w={840} h={400} view={[62, 78, 130, 112]} wing={44} detail={false} /></div>
    {fade(760, 260, h)}
    <div style={{ position: "absolute", left: 64, top: 0, bottom: 0, display: "flex", alignItems: "center", gap: 36 }}>
      <BrandLogo size={190} />
      <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
        <Wordmark size={74} />
        <div style={{ fontSize: 24, color: c.stone, maxWidth: 520, lineHeight: 1.3 }}>{DESC}</div>
        <div style={{ fontFamily: mono, fontSize: 17, letterSpacing: 5, color: c.orange }}>{TAGLINE}</div>
      </div>
    </div>
  </Canvas>
);

/** README concept figure: capability transfer with recipient-side validation. 1200x520. */
export const CapabilityTransfer = ({ w = 1200, h = 520 }: { w?: number; h?: number }) => (
  <Canvas w={w} h={h}>
    <GridBackground w={w} h={h} step={32} />
    <svg width={w} height={h} style={{ position: "absolute", inset: 0 }}>
      <ArrowDefs />
      <text x={48} y={60} fill={c.orange} fontFamily={mono} fontSize={14} letterSpacing={4}>CAPABILITY TRANSFER</text>
      <text x={48} y={100} fill={c.white} fontSize={34} fontWeight={700} letterSpacing={-1}>Learned behavior moves. The receiver decides.</text>
      {/* donor */}
      <rect x={48} y={170} width={260} height={250} rx={6} fill={c.surface} stroke="#555" />
      <FixedWing x={178} y={265} size={90} heading={90} accent />
      <text x={78} y={380} fill={c.stone} fontFamily={mono} fontSize={15} letterSpacing={2}>PLATFORM A</text>
      <text x={78} y={402} fill={c.grey} fontFamily={mono} fontSize={13}>learned locally</text>
      {/* candidate */}
      <line x1={308} y1={295} x2={470} y2={295} stroke="#aaa" strokeWidth={1.8} markerEnd="url(#ah)" />
      <rect x={340} y={262} width={100} height={66} rx={4} fill={c.orange} />
      <text x={390} y={302} textAnchor="middle" fill={c.bg} fontFamily={mono} fontSize={14} fontWeight={700} letterSpacing={1}>CANDIDATE</text>
      {/* gate */}
      <rect x={470} y={170} width={290} height={250} rx={6} fill="none" stroke={c.orange} strokeWidth={2} strokeDasharray="8 6" />
      <text x={490} y={202} fill={c.orange} fontFamily={mono} fontSize={14} letterSpacing={3}>VALIDATE LOCALLY</text>
      {["ARCHITECTURE", "SHAPES · FINITE", "SIZE · AGE", "PROVENANCE"].map((t, i) => (
        <g key={t}><path d={`M492 ${240 + i * 40} l7 7 l12 -14`} stroke={c.orange} strokeWidth={2.5} fill="none" /><text x={526} y={248 + i * 40} fill={c.stone} fontFamily={mono} fontSize={15} letterSpacing={1.5}>{t}</text></g>
      ))}
      <line x1={760} y1={295} x2={830} y2={295} stroke="#aaa" strokeWidth={1.8} markerEnd="url(#ah)" />
      {/* recipient */}
      <rect x={830} y={170} width={320} height={250} rx={6} fill={c.surface} stroke={c.orange} />
      <FixedWing x={960} y={250} size={90} heading={90} accent />
      <text x={856} y={348} fill={c.stone} fontFamily={mono} fontSize={15} letterSpacing={2}>PLATFORM B</text>
      {[["ACCEPT", c.orange], ["ADAPT", c.stone], ["REJECT", c.grey]].map(([t, col], i) => <text key={t} x={856 + i * 100} y={392} fill={col} fontFamily={mono} fontSize={14} letterSpacing={2}>{t}</text>)}
      <text x={48} y={480} fill={c.grey} fontFamily={mono} fontSize={14} letterSpacing={2}>NO CENTRAL LEARNER · {TAGLINE_CAPS}</text>
    </svg>
  </Canvas>
);

export const Scaled = ({ k, w, h, children }: { k: number; w: number; h: number; children?: ReactNode }) => (
  <div style={{ width: w * k, height: h * k, overflow: "hidden" }}>
    <div style={{ width: w, height: h, transform: `scale(${k})`, transformOrigin: "0 0" }}>{children}</div>
  </div>
);
