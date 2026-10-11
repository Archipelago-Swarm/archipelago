import { FixedWing } from "../components/FixedWing";
import { Callout, Card, SectionTitle, Tag, Telemetry } from "../components/motifs";
import { StraitMap } from "../components/StraitMap";
import { ArrowDefs, BrandLogo, Canvas, Wordmark } from "../components/primitives";
import { c, mono, TAGLINE } from "../tokens";
import { H, P, Slide, W } from "./frame";

const box = (x: number, y: number, w: number, h: number, title: string, sub: string, accent = false, dashed = false) => (
  <g key={title + x}>
    <rect x={x} y={y} width={w} height={h} rx={4} fill={c.surface} stroke={accent ? c.orange : "#555"} strokeWidth={1.5} strokeDasharray={dashed ? "7 6" : undefined} />
    <text x={x + 20} y={y + 34} fill={c.white} fontFamily={mono} fontSize={19} fontWeight={700} letterSpacing={2}>{title}</text>
    <text x={x + 20} y={y + 62} fill={c.grey} fontSize={17}>{sub}</text>
  </g>
);

/** 06 Architecture: layered bands */
export const S6Arch = () => (
  <Slide n={6} label="ARCHITECTURE" note="DECISION LOOP · OBSERVATION PLANE">
    <div style={{ position: "absolute", left: 80, top: 120 }}><SectionTitle kicker="ARCHITECTURE" title="Decentralized decisions. Separate observation plane." size={54} /></div>
    <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
      <ArrowDefs />
      <rect x={80} y={290} width={1760} height={470} rx={8} fill="none" stroke={c.orange} strokeOpacity={0.5} strokeDasharray="4 8" />
      <text x={104} y={282} fill={c.orange} fontFamily={mono} fontSize={14} letterSpacing={4}>DECISION LOOP · NO CENTRAL LEARNER</text>
      {box(120, 320, 1680, 92, "SIMULATED WORLD · COORDINATOR", "continuous operational environment · lockstep ticks · simulator adapter (2D, 3D spike)")}
      {[0, 1, 2, 3].map((i) => {
        const x = 120 + i * 430;
        return (
          <g key={i}>
            {box(x, 470, 380, 150, `NODE 0${i + 1}`, "local policy (PyTorch) · replay · validator", true)}
            <FixedWing x={x + 322} y={582} size={44} heading={-20 + i * 15} />
            <line x1={x + 190} y1={412} x2={x + 190} y2={470} stroke="#aaa" strokeWidth={1.6} markerEnd="url(#ah)" markerStart="url(#ah)" />
          </g>
        );
      })}
      <rect x={120} y={660} width={1680} height={70} rx={4} fill="none" stroke={c.stone} strokeWidth={1.5} />
      <text x={144} y={702} fill={c.stone} fontFamily={mono} fontSize={19} letterSpacing={3}>P2P EXCHANGE LAYER · candidate models · validation-gated · partitionable</text>
      {[0, 1, 2, 3].map((i) => <line key={i} x1={310 + i * 430} y1={620} x2={310 + i * 430} y2={660} stroke="#aaa" strokeWidth={1.6} markerStart="url(#ah)" markerEnd="url(#ah)" />)}
      {/* observation plane */}
      <text x={80} y={810} fill={c.grey} fontFamily={mono} fontSize={14} letterSpacing={4}>OBSERVATION PLANE · OUTSIDE THE LOOP</text>
      <line x1={310} y1={620} x2={310} y2={640} stroke="none" />
      {[["TELEMETRY", "non-blocking spool"], ["API", "FastAPI · WebSocket"], ["DATA", "TimescaleDB"], ["OBSERVE", "Grafana · React replay"]].map(([t, s], i) => (
        <g key={t}>{box(80 + i * 450, 830, 390, 100, t, s, false, false)}{i < 3 && <line x1={470 + i * 450} y1={880} x2={530 + i * 450} y2={880} stroke="#aaa" strokeWidth={1.6} markerEnd="url(#ah)" />}</g>
      ))}
      <path d="M1700 730 V790 H275 V830" stroke="#777" strokeDasharray="6 6" fill="none" markerEnd="url(#ah)" />
      <text x={990} y={782} textAnchor="middle" fill={c.grey} fontFamily={mono} fontSize={13} letterSpacing={2} style={{ paintOrder: "stroke", stroke: c.bg, strokeWidth: 6 }}>NODE EVENTS</text>
    </svg>
  </Slide>
);

/** 07 Results / replay / observability template (no numbers: awaiting a real run) */
export const S7Results = () => (
  <Slide n={7} label="REPLAY + OBSERVABILITY" note="TEMPLATE · NO RUN LOADED · NO VALUES SHOWN">
    <div style={{ position: "absolute", left: 80, top: 110 }}><SectionTitle kicker="REPLAY + OBSERVABILITY" title="See every offer, validation and decision" size={50} /></div>
    <div style={{ position: "absolute", right: 80, top: 130 }}><Tag tone="orange">Template · awaiting measured data</Tag></div>
    <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
      {/* replay bar */}
      <rect x={80} y={250} width={1760} height={70} rx={6} fill={c.surface} stroke={c.border} />
      <path d="M110 270 L110 300 L136 285Z" fill={c.stone} /><rect x={160} y={270} width={8} height={30} fill={c.stone} /><rect x={176} y={270} width={8} height={30} fill={c.stone} />
      <path d="M206 270 L206 300 L226 285Z M226 270 L226 300 L246 285Z" fill={c.stone} />
      <line x1={290} y1={285} x2={1500} y2={285} stroke="#444" strokeWidth={4} />
      {Array.from({ length: 61 }, (_, i) => <line key={i} x1={290 + i * 20.17} x2={290 + i * 20.17} y1={i % 5 ? 305 : 300} y2={312} stroke="#555" />)}
      <rect x={284} y={272} width={12} height={26} fill={c.orange} />
      <text x={1540} y={293} fill={c.grey} fontFamily={mono} fontSize={18} letterSpacing={2}>TICK —  ·  RUN —</text>
      {/* learning over rounds */}
      <rect x={80} y={350} width={1030} height={380} rx={6} fill={c.surface} stroke={c.border} />
      <text x={104} y={384} fill={c.grey} fontFamily={mono} fontSize={14} letterSpacing={3}>LEARNING OVER ROUNDS</text>
      {[0, 1, 2, 3].map((i) => <line key={i} x1={110} x2={1080} y1={420 + i * 82} y2={420 + i * 82} stroke="#fff" strokeOpacity={0.07} />)}
      <path d="M110 410 V690 H1080" stroke="#555" fill="none" />
      <text x={595} y={565} textAnchor="middle" fill={c.grey} fontFamily={mono} fontSize={22} letterSpacing={4}>AWAITING MEASURED DATA</text>
      {/* node telemetry */}
      <rect x={1140} y={350} width={700} height={380} rx={6} fill={c.surface} stroke={c.border} />
      <text x={1164} y={384} fill={c.grey} fontFamily={mono} fontSize={14} letterSpacing={3}>NODE TELEMETRY</text>
      {["POLICY", "UPDATES", "BACKLOG"].map((t, i) => <text key={t} x={1380 + i * 160} y={425} fill={c.grey} fontFamily={mono} fontSize={14} letterSpacing={2}>{t}</text>)}
      {[1, 2, 3, 4].map((n, r) => (
        <g key={n}>
          <line x1={1164} x2={1816} y1={445 + r * 66} y2={445 + r * 66} stroke={c.border} />
          <text x={1164} y={485 + r * 66} fill={c.stone} fontFamily={mono} fontSize={19}>NODE-0{n}</text>
          {[0, 1, 2].map((i) => <text key={i} x={1380 + i * 160} y={485 + r * 66} fill="#555" fontFamily={mono} fontSize={19}>—</text>)}
        </g>
      ))}
      {/* event timeline lanes */}
      <rect x={80} y={760} width={1030} height={225} rx={6} fill={c.surface} stroke={c.border} />
      <text x={104} y={794} fill={c.grey} fontFamily={mono} fontSize={14} letterSpacing={3}>EVENT TIMELINE</text>
      {["OFFER", "VALIDATE", "ACCEPT / REJECT", "PARTITION"].map((t, i) => (
        <g key={t}><text x={104} y={832 + i * 42} fill={c.stone} fontFamily={mono} fontSize={14} letterSpacing={2}>{t}</text><line x1={310} x2={1080} y1={827 + i * 42} y2={827 + i * 42} stroke="#444" strokeDasharray="2 8" strokeWidth={2} /></g>
      ))}
      {/* lineage */}
      <rect x={1140} y={760} width={700} height={225} rx={6} fill={c.surface} stroke={c.border} />
      <text x={1164} y={794} fill={c.grey} fontFamily={mono} fontSize={14} letterSpacing={3}>CAPABILITY LINEAGE</text>
      {[[1200, 880, "ORIGIN"], [1440, 840, "NODE"], [1440, 940, "NODE"], [1680, 880, "NODE"]].map(([x, y, t], i) => (
        <g key={i}><rect x={(x as number) - 50} y={(y as number) - 22} width={100} height={44} rx={3} fill="none" stroke={i === 0 ? c.orange : "#666"} strokeDasharray="5 5" /><text x={x as number} y={(y as number) + 6} textAnchor="middle" fill="#777" fontFamily={mono} fontSize={14}>{t}</text></g>
      ))}
      <path d="M1250 872 L1390 846 M1250 888 L1390 934 M1490 846 L1630 872 M1490 934 L1630 888" stroke="#666" strokeDasharray="5 5" fill="none" />
    </svg>
  </Slide>
);

/** 08 Stack: typographic rows */
export const S8Stack = () => {
  const rows: [string, [string, boolean?][]][] = [
    ["NODE RUNTIME", [["Python 3.12"], ["PyTorch"], ["NumPy"]]],
    ["SIMULATION", [["PettingZoo"], ["Sim2D adapter"], ["PyBullet (3D spike)"]]],
    ["PEER NETWORK", [["HTTP peer transport"], ["Pydantic contracts"]]],
    ["BACKEND", [["FastAPI"], ["Uvicorn"], ["WebSockets"]]],
    ["DATA", [["TimescaleDB"], ["TigerData (managed target)", true], ["psycopg"]]],
    ["OBSERVABILITY", [["Grafana"]]],
    ["FRONTEND", [["React"], ["TypeScript"], ["Vite"], ["Canvas map"]]],
    ["INFRASTRUCTURE", [["Docker Compose"], ["Caddy"], ["Vultr (target)", true]]],
  ];
  return (
    <Slide n={8} label="STACK" note="DASHED = DEPLOYMENT TARGET, NOT YET PROVISIONED">
      <div style={{ position: "absolute", left: 80, top: 120 }}><SectionTitle kicker="STACK" title="Built from real components" size={56} /></div>
      <div style={{ position: "absolute", left: 80, right: 80, top: 270 }}>
        {rows.map(([cat, items]) => (
          <div key={cat} style={{ display: "flex", alignItems: "center", gap: 40, padding: "13px 0", borderBottom: `1px solid ${c.border}` }}>
            <div style={{ width: 280, fontFamily: mono, fontSize: 17, letterSpacing: 3, color: c.orange }}>{cat}</div>
            <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
              {items.map(([n, planned]) => <span key={n} style={{ fontSize: 28, fontWeight: 700, color: c.white, border: `1px ${planned ? "dashed" : "solid"} ${planned ? c.orange : "#444"}`, background: c.elevated, borderRadius: 3, padding: "7px 18px", letterSpacing: -0.5 }}>{n}</span>)}
            </div>
          </div>
        ))}
      </div>
    </Slide>
  );
};

/** 09 Insight */
export const S9Insight = () => (
  <Slide n={9} label="WHAT WE LEARNED" note="THE DISTINCTION THAT MATTERS">
    <div style={{ position: "absolute", left: 80, top: 130 }}><SectionTitle kicker="WHAT WE LEARNED" title="Adaptation, not just computation" size={62} /></div>
    {[["Distributed computation", "Distributed adaptation", 360], ["Sharing observations", "Sharing learned capabilities", 640]].map(([a, b, y]) => (
      <div key={a as string} style={{ position: "absolute", left: 80, right: 80, top: y as number, display: "flex", alignItems: "center", gap: 40 }}>
        <div style={{ flex: 1, fontSize: 52, fontWeight: 700, color: "#6a6a6a", letterSpacing: -2, textDecoration: "line-through", textDecorationColor: "#444" }}>{a}</div>
        <svg width={120} height={30}><path d="M0 15 H100 M84 3 L102 15 L84 27" stroke={c.orange} strokeWidth={3} fill="none" /></svg>
        <div style={{ flex: 1.2, fontSize: 60, fontWeight: 700, color: c.white, letterSpacing: -2.5, lineHeight: 1 }}>{b}</div>
      </div>
    ))}
    <div style={{ position: "absolute", left: 80, right: 80, top: 900 }}>
      <div style={{ borderLeft: `4px solid ${c.orange}`, paddingLeft: 28, fontSize: 28, color: c.stone, maxWidth: 1300, lineHeight: 1.4 }}>One platform learns a useful behavior. Another evaluates it, and adopts it without repeating the full learning process.</div>
    </div>
  </Slide>
);

/** 10 Roadmap: timeline */
export const S10Roadmap = () => {
  const items: [string, string, "NOW" | "NEXT" | "LATER"][] = [
    ["Continuous environment", "Headings, velocities, curved paths", "NOW"],
    ["Terrain", "Elevation, line of sight, cover", "NEXT"],
    ["Large-area operations", "Wide-area squadron coverage", "NEXT"],
    ["Dynamic seeded actors", "Reproducible moving threats and targets", "NEXT"],
    ["Richer validation", "Beyond shape and finite checks", "LATER"],
    ["Persistent transfer under attrition", "Capabilities outlive lost nodes", "LATER"],
  ];
  return (
    <Slide n={10} label="WHAT'S NEXT" note="STATUS TAGS NEED OWNER REVIEW">
      <div style={{ position: "absolute", left: 80, top: 130 }}><SectionTitle kicker="WHAT'S NEXT" title="From grid-world to wide-area operations" size={58} /></div>
      <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
        <line x1={80} y1={620} x2={1840} y2={620} stroke={c.border} strokeWidth={2} />
        <line x1={80} y1={620} x2={420} y2={620} stroke={c.orange} strokeWidth={4} />
        {items.map(([t, d, s], i) => {
          const x = 120 + i * 290, up = i % 2 === 0, y = up ? 360 : 680;
          return (
            <g key={t}>
              <line x1={x} y1={620} x2={x} y2={up ? 520 : 680} stroke="#555" />
              <rect x={x - 11} y={609} width={22} height={22} fill={s === "NOW" ? c.orange : c.bg} stroke={s === "LATER" ? "#777" : c.orange} strokeWidth={2} strokeDasharray={s === "LATER" ? "4 4" : undefined} />
              <text x={x - 11} y={y + (up ? 0 : 40)} fill={s === "NOW" ? c.orange : c.grey} fontFamily={mono} fontSize={15} letterSpacing={3}>{s}</text>
              <foreignObject x={x - 11} y={y + (up ? 14 : 54)} width={270} height={150}>
                <div style={{ fontFamily: "Arial", fontSize: 28, fontWeight: 700, color: "#fff", letterSpacing: -0.8, lineHeight: 1.08 }}>{t}<div style={{ fontFamily: mono, fontWeight: 400, fontSize: 15, color: "#8A8A8A", marginTop: 10, letterSpacing: 0.5, lineHeight: 1.4 }}>{d}</div></div>
              </foreignObject>
            </g>
          );
        })}
      </svg>
    </Slide>
  );
};

/** 11 End / CTA */
export const S11End = () => (
  <Canvas w={W} h={H}>
    <div style={{ position: "absolute", left: 900, top: 0, opacity: 0.85 }}><StraitMap w={1020} h={1080} view={[84, 52, 150, 117]} /></div>
    <div style={{ position: "absolute", left: 600, top: 0, width: 500, height: H, background: `linear-gradient(90deg, ${c.bg} 20%, rgba(10,10,10,0))` }} />
    <div style={{ position: "absolute", left: 110, top: 0, bottom: 0, display: "flex", flexDirection: "column", justifyContent: "center", gap: 34 }}>
      <BrandLogo size={170} />
      <Wordmark size={96} />
      <div style={{ fontFamily: mono, fontSize: 24, letterSpacing: 6, color: c.orange }}>{TAGLINE}</div>
      <P size={30} w={780}>Autonomous platforms that transfer learned capabilities, adapt collectively and keep operating without central AI infrastructure.</P>
      <div style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 10 }}>
        {[["GITHUB", "github.com/Archipelago-Swarm/archipelago"], ["DEVPOST", "devpost.com/software/archipelago-wpa5k9"], ["DEMO", "COMING SOON"]].map(([k, v]) => (
          <div key={k} style={{ display: "flex", gap: 28, fontFamily: mono, fontSize: 22, letterSpacing: 2 }}><span style={{ width: 130, color: c.grey }}>{k}</span><span style={{ color: v === "COMING SOON" ? c.grey : c.stone }}>{v}</span></div>
        ))}
      </div>
    </div>
  </Canvas>
);
