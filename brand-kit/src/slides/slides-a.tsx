import { FixedWing } from "../components/FixedWing";
import { Icon, Card, SectionTitle, Tag } from "../components/motifs";
import { StraitScenario } from "../components/Scenario";
import { BrandLogo, Canvas, Wordmark } from "../components/primitives";
import { c, mono } from "../tokens";
import { H, P, Slide, W } from "./frame";

const fadeLeft = (x: number, w: number) => <div style={{ position: "absolute", left: x, top: 0, width: w, height: H, background: `linear-gradient(90deg, ${c.bg}, rgba(10,10,10,0))` }} />;

/** 01 Hero */
export const S1Hero = () => (
  <Canvas w={W} h={H}>
    <div style={{ position: "absolute", left: 760, top: 0 }}><StraitScenario w={1160} h={1080} view={[62, 50, 134, 117.2]} wing={58} /></div>
    {fadeLeft(760, 380)}
    <div style={{ position: "absolute", left: 110, top: 0, bottom: 0, display: "flex", flexDirection: "column", justifyContent: "center", gap: 36 }}>
      <BrandLogo size={230} />
      <Wordmark size={118} />
      <P size={34} w={780} style={{ opacity: 0.92 }}>Decentralized learning for collaborative autonomous platforms.</P>
      <div style={{ fontFamily: mono, fontSize: 24, letterSpacing: 6, color: c.orange }}>NO MAINLAND REQUIRED.</div>
    </div>
    <div style={{ position: "absolute", left: 110, bottom: 40, fontFamily: mono, fontSize: 14, letterSpacing: 2, color: c.grey }}>ILLUSTRATIVE SCENARIO · TAIWAN STRAIT TERRAIN FROM DEMO MAP</div>
  </Canvas>
);

/** 02 Problem / inspiration: centralized vs distributed adaptation */
export const S2Problem = () => (
  <Slide n={2} label="INSPIRATION" note="">
    <div style={{ position: "absolute", left: 80, top: 130 }}><SectionTitle kicker="INSPIRATION" title="Edge systems shouldn't wait on a mainland" size={62} /></div>
    <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
      {/* centralized */}
      <g transform="translate(80,330)">
        <text x={0} y={0} fill={c.grey} fontFamily={mono} fontSize={16} letterSpacing={4}>CENTRALIZED AI</text>
        <rect x={250} y={30} width={300} height={90} rx={4} fill={c.surface} stroke="#555" />
        <text x={400} y={85} textAnchor="middle" fill={c.stone} fontFamily={mono} fontSize={20} letterSpacing={3}>CENTRAL MODEL</text>
        {[0, 1, 2, 3].map((i) => {
          const x = 90 + i * 190;
          return (
            <g key={i}>
              <line x1={400} y1={120} x2={x} y2={330} stroke={c.grey} strokeWidth={1.8} strokeDasharray="6 8" />
              {i % 2 === 0 && <g><circle cx={(400 + x) / 2} cy={225} r={14} fill={c.bg} stroke={c.orange} strokeWidth={2} /><path d={`M${(400 + x) / 2 - 6} 219 l12 12 M${(400 + x) / 2 + 6} 219 l-12 12`} stroke={c.orange} strokeWidth={2.2} /></g>}
              <FixedWing x={x} y={375} size={80} heading={0} color={c.grey} />
              <text x={x} y={450} textAnchor="middle" fill={c.grey} fontFamily={mono} fontSize={14} letterSpacing={2}>CONSUMES</text>
            </g>
          );
        })}
        <text x={0} y={510} fill={c.stone} fontSize={26}>One slow loop. One point of failure.</text>
      </g>
      <line x1={960} y1={330} x2={960} y2={850} stroke={c.border} />
      {/* distributed */}
      <g transform="translate(1040,330)">
        <text x={0} y={0} fill={c.orange} fontFamily={mono} fontSize={16} letterSpacing={4}>ARCHIPELAGO</text>
        {[[110, 120], [330, 60], [620, 130], [200, 330], [470, 300], [720, 350]].map(([x, y], i, a) => (
          <g key={i}>
            {i < a.length - 1 && [[0, 1], [1, 2], [0, 3], [1, 4], [2, 5], [3, 4], [4, 5]].filter(([p]) => p === i).map(([, q], j) => <line key={j} x1={x} y1={y} x2={a[q][0]} y2={a[q][1]} stroke={c.stone} strokeOpacity={0.7} strokeWidth={1.8} />)}
          </g>
        ))}
        {[[110, 120], [330, 60], [620, 130], [200, 330], [470, 300], [720, 350]].map(([x, y], i) => (
          <g key={"u" + i}>
            <FixedWing x={x} y={y} size={72} heading={[-20, 10, 25, -35, 5, 30][i]} accent={i === 1} />
            <rect x={x + 30} y={y - 44} width={22} height={14} fill="none" stroke={c.orange} strokeWidth={2} />
          </g>
        ))}
        <text x={0} y={510} fill={c.stone} fontSize={26}>Every platform learns. Useful behavior spreads.</text>
      </g>
    </svg>
    <div style={{ position: "absolute", left: 80, bottom: 110, display: "flex", gap: 14 }}>
      {["CONTESTED COMMS", "GPS-DENIED", "ATTRITABLE NODES", "SLOW CENTRAL ADAPTATION", "SINGLE POINT OF FAILURE"].map((t) => <Tag key={t}>{t}</Tag>)}
    </div>
  </Slide>
);

/** 03 What it does: four capability cards */
export const S3What = () => {
  const cards = [
    ["learn", "Independent learning", "Each platform trains its own policy on its own experience.", "OWN POLICY · OWN REPLAY"],
    ["transfer", "Peer capability exchange", "Learned models move node to node. No central learner.", "TENSOR-ONLY · BOUNDED PAYLOADS"],
    ["validate", "Recipient-side validation", "The receiver checks a candidate before it changes behavior.", "ARCH · SHAPES · FINITE · PROVENANCE"],
    ["partition", "Resilient under partitions", "Links drop. Platforms keep acting and re-sync when links return.", "LINK GATES · LOCAL ACTION CONTINUES"],
  ] as const;
  return (
    <Slide n={3} label="WHAT IT DOES" note="CAPABILITIES, NOT OBSERVATIONS">
      <div style={{ position: "absolute", left: 80, top: 130 }}><SectionTitle kicker="WHAT IT DOES" title="A capability-sharing layer for autonomous platforms" size={62} /></div>
      <div style={{ position: "absolute", left: 80, right: 80, top: 400, display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 24 }}>
        {cards.map(([ic, t, d, s], i) => (
          <Card key={t} accent={i === 2} style={{ minHeight: 400, display: "flex", flexDirection: "column" }}>
            <Icon kind={ic} size={72} />
            <div style={{ fontSize: 34, fontWeight: 700, color: c.white, marginTop: 36, letterSpacing: -1, lineHeight: 1.1 }}>{t}</div>
            <P size={24} color={c.stone} style={{ marginTop: 20, opacity: 0.85 }}>{d}</P>
            <div style={{ marginTop: "auto", fontFamily: mono, fontSize: 14, letterSpacing: 2, color: c.grey, paddingTop: 24 }}>{s}</div>
          </Card>
        ))}
      </div>
    </Slide>
  );
};

/** 04 How it works: four-step lifecycle with a different visual per step */
export const S4How = () => {
  const X = [80, 530, 980, 1430], CW = 410;
  return (
    <Slide n={4} label="HOW IT WORKS" note="NO CENTRAL LEARNER">
      <div style={{ position: "absolute", left: 80, top: 130 }}><SectionTitle kicker="HOW IT WORKS" title="Learn. Offer. Validate. Adapt." size={62} /></div>
      <svg width={W} height={H} style={{ position: "absolute", inset: 0, transform: "translateY(60px)" }}>
        <line x1={80} y1={372} x2={1840} y2={372} stroke={c.border} strokeWidth={2} />
        {X.map((x, i) => (
          <g key={i}>
            <rect x={x} y={360} width={24} height={24} fill={i === 3 ? c.orange : c.bg} stroke={c.orange} strokeWidth={2} />
            <text x={x + 40} y={381} fill={c.orange} fontFamily={mono} fontSize={22} letterSpacing={3}>0{i + 1}</text>
            <text x={x} y={450} fill={c.white} fontSize={38} fontWeight={700} letterSpacing={-1}>{["Learn locally", "Offer a candidate", "Validate locally", "Accept · reject · adapt"][i]}</text>
            <rect x={x} y={490} width={CW} height={330} rx={6} fill={c.surface} stroke={c.border} />
          </g>
        ))}
        {/* 1: local learning curve (schematic) */}
        <g transform={`translate(${X[0] + 30},520)`}>
          <path d="M0 260 V20 M0 260 H350" stroke="#555" fill="none" /><path d="M0 230 C60 220 80 150 140 140 S250 60 350 40" stroke={c.orange} strokeWidth={4} fill="none" />
          <text x={0} y={290} fill={c.grey} fontFamily={mono} fontSize={14} letterSpacing={2}>OWN EXPERIENCE → OWN POLICY</text>
        </g>
        {/* 2: offer */}
        <g transform={`translate(${X[1] + 30},560)`}>
          <FixedWing x={55} y={70} size={64} heading={90} />
          <FixedWing x={295} y={70} size={64} heading={90} />
          <line x1={135} y1={70} x2={215} y2={70} stroke="#8a8a88" strokeWidth={1.5} />
          <rect x={155} y={52} width={40} height={36} fill={c.orange} stroke={c.bg} strokeWidth={4} />
          <text x={0} y={190} fill={c.grey} fontFamily={mono} fontSize={14} letterSpacing={2}>MODEL VERSION → NEIGHBOR</text>
          <text x={0} y={216} fill={c.grey} fontFamily={mono} fontSize={14} letterSpacing={2}>AT EPISODE BOUNDARIES</text>
        </g>
        {/* 3: validation checklist */}
        <g transform={`translate(${X[2] + 30},530)`}>
          {["ARCHITECTURE MATCH", "TENSOR SHAPES", "FINITE VALUES", "SIZE + AGE LIMITS", "PROVENANCE"].map((t, i) => (
            <g key={t} transform={`translate(0,${i * 54})`}>
              <rect width={26} height={26} fill="none" stroke={c.stone} strokeWidth={2} /><path d="M6 14 L12 20 L21 7" stroke={c.orange} strokeWidth={3} fill="none" />
              <text x={44} y={20} fill={c.stone} fontFamily={mono} fontSize={17} letterSpacing={2}>{t}</text>
            </g>
          ))}
        </g>
        {/* 4: decision */}
        <g transform={`translate(${X[3] + 30},530)`}>
          {[["ACCEPT", c.orange, "adopt into local policy"], ["ADAPT", c.stone, "mix a fraction in"], ["REJECT", c.grey, "log and discard"]].map(([t, col, d], i) => (
            <g key={t} transform={`translate(0,${i * 92})`}>
              <rect width={350} height={72} rx={3} fill="none" stroke={col} strokeWidth={2} strokeDasharray={i === 2 ? "6 6" : undefined} />
              <text x={22} y={32} fill={col} fontFamily={mono} fontSize={22} letterSpacing={4} fontWeight={700}>{t}</text>
              <text x={22} y={58} fill={c.grey} fontFamily={mono} fontSize={14} letterSpacing={1}>{d}</text>
            </g>
          ))}
        </g>
      </svg>
    </Slide>
  );
};

/** 05 Operational scenario: full-bleed map */
export const S5Scenario = () => (
  <Canvas w={W} h={H}>
    <div style={{ position: "absolute", left: 600, top: 0 }}><StraitScenario w={1320} h={1080} view={[55, 47, 135, 112.5]} wing={60} /></div>
    {fadeLeft(600, 300)}
    <div style={{ position: "absolute", left: 80, top: 44, display: "flex", alignItems: "center", gap: 16 }}><BrandLogo size={40} /><span style={{ fontWeight: 700, fontSize: 20, letterSpacing: 4, color: c.white }}>ARCHIPELAGO</span></div>
    <div style={{ position: "absolute", left: 80, top: 170, width: 640 }}>
      <SectionTitle kicker="OPERATIONAL SCENARIO" title="Wide-area autonomy where links fail" size={58} />
      <div style={{ marginTop: 44, display: "flex", flexDirection: "column", gap: 26 }}>
        {[["Squadrons patrol a continuous environment.", "UAV squadrons, curved routes, sensor footprints."], ["Links drop. Platforms keep acting locally.", "Partitions never block the decision loop."], ["Capabilities move when a link exists.", "Validated on receipt, adopted or rejected."]].map(([t, d]) => (
          <div key={t}><div style={{ fontSize: 28, fontWeight: 700, color: c.white }}>{t}</div><div style={{ fontFamily: mono, fontSize: 16, color: c.grey, marginTop: 6, letterSpacing: 1 }}>{d}</div></div>
        ))}
      </div>
    </div>
    <div style={{ position: "absolute", left: 80, bottom: 120, display: "flex", flexDirection: "column", gap: 12, fontFamily: mono, fontSize: 15, letterSpacing: 2, color: c.stone }}>
      <span><b style={{ color: c.orange }}>■</b> CAPABILITY CANDIDATE IN TRANSIT</span>
      <span><b style={{ color: c.orange }}>◉</b> COMMAND NODE</span>
      <span style={{ color: c.grey }}>— — LINK LOST (PARTITION)</span>
      <span>▭ SENSOR FOOTPRINT · ┄ PLANNED ROUTE</span>
    </div>
    <div style={{ position: "absolute", left: 80, right: 80, bottom: 40, display: "flex", justifyContent: "space-between", fontFamily: mono, fontSize: 15, letterSpacing: 2.5 }}>
      <span style={{ color: c.grey }}>ILLUSTRATIVE ROUTES · COASTLINE FROM DEMO TERRAIN MASK</span><span style={{ color: c.orange }}>NO MAINLAND REQUIRED.</span>
    </div>
    <div style={{ position: "absolute", right: 80, top: 54, fontFamily: mono, fontSize: 16, letterSpacing: 3, color: c.grey }}>05 / 11 · SCENARIO</div>
  </Canvas>
);
