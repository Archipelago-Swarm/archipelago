import { Ctx } from "../ctx";
import { theme } from "../styles/theme";
import { pulse, win } from "../world/paths";
import { CMD } from "../world/scenario";
import logo from "../../media/logo.png";

const MISSION = [
  { t: 7, label: "FIND & MAINTAIN TRACK" },
  { t: 14, label: "MAP THREAT MOVEMENT" },
  { t: 25, label: "ADAPT FROM LEARNED BEHAVIOR" },
  { t: 40, label: "SHADOW / AVOID · KEEP COVERAGE" },
  { t: 48, label: "AWARENESS UNDER COMMS LOSS" },
  { t: 61, label: "RELAY INTEL TO COMMAND" },
  { t: 67, label: "" },
  { t: 999, label: "" },
];
const LAYERS: { label: string; on: [number, number][] }[] = [
  { label: "ELEVATION", on: [[7, 67]] },
  { label: "REGION CLASS", on: [[7, 48]] },
  { label: "LOS RISK", on: [[14, 33], [38, 48]] },
  { label: "EXPOSURE", on: [[14, 33], [38, 54]] },
  { label: "COVER", on: [[25, 54]] },
];
const SOLVE = ["CONTESTED COMMS", "GPS-DENIED", "ATTRITABLE NODES", "SLOW CENTRAL ADAPTATION", "SINGLE POINT OF FAILURE", "POOR BEHAVIOR TRANSFER"];

const mono: React.CSSProperties = { fontFamily: theme.fontFamily };

export const Overview: React.FC<{ ctx: Ctx }> = ({ ctx }) => {
  const { t, gnd } = ctx;
  // title block is fully visible at 0 s and 72 s so the loop closes
  const vis = (d: number) => 1 - win(t, 5 + d, 6 + d) + win(t, 68.4 + d, 69.8 + d);
  const header = 1 - vis(0.1);
  const panel = pulse(t, 6.4, 7.4, 66.4, 67.4);
  const idx = MISSION.findIndex((m, i) => t >= m.t && t < MISSION[i + 1].t);
  const geo = 1 - win(t, 8, 10.5) + win(t, 66, 69); // region labels: overview only (and back for the loop)
  const cmd = gnd(CMD.x, CMD.y);
  const sol = (i: number) => pulse(t, 66.8 + i * 0.28, 67.3 + i * 0.28, 71.2, 71.9);
  return (
    <>
      <rect width={1920} height={1080} fill="url(#scrimL)" opacity={vis(0)} />

      {/* geography */}
      {[
        { l: "TAIWAN STRAIT", x: 88, y: 84, size: 3.2, sp: 1.3 },
        { l: "FUJIAN", x: 44, y: 44, size: 3.4, sp: 1.3 },
        { l: "TAIWAN", x: 124, y: 93, size: 3.2, sp: 1.2 },
      ].map((g) => {
        // lay the label on the terrain: map its x / y axes through the camera so it foreshortens with the map
        const P = (x: number, y: number) => ctx.proj({ x, y, z: 0.4 }); // flat plane, so the label does not shear over relief
        const o = P(g.x, g.y), u = P(g.x + 1, g.y), v = P(g.x, g.y + 1);
        return (
          <text key={g.l} transform={`matrix(${u[0] - o[0]} ${u[1] - o[1]} ${v[0] - o[0]} ${v[1] - o[1]} ${o[0]} ${o[1]})`} fill={theme.primary} opacity={0.9 * geo}
            style={{ ...mono, paintOrder: "stroke", stroke: "rgba(10,10,10,0.55)", strokeWidth: 0.55, strokeLinejoin: "round" }} fontSize={g.size} fontWeight={700} letterSpacing={g.sp}>
            {g.l}
          </text>
        );
      })}
      {/* command node */}
      <g opacity={0.95}>
        <rect x={cmd[0] - 11} y={cmd[1] - 11} width={22} height={22} fill="none" stroke={theme.primary} strokeWidth={3} />
        <rect x={cmd[0] - 4} y={cmd[1] - 4} width={8} height={8} fill={theme.accent} />
        <text x={cmd[0] + 26} y={cmd[1] + 7} fill={theme.primary} style={{ ...mono, paintOrder: "stroke", stroke: "#0A0A0A", strokeWidth: 5 }} fontSize={18} fontWeight={700} letterSpacing={3.5}>COMMAND NODE</text>
      </g>

      <g opacity={vis(0)}>
        <image href={logo} x={100} y={190} width={170} height={162} />
        <text x={96} y={500} fill={theme.textPrimary} style={mono} fontSize={104} fontWeight={700} letterSpacing={8} opacity={vis(0.1) / Math.max(vis(0), 0.001)}>ARCHIPELAGO</text>
        <text x={102} y={566} fill={theme.textSecondary} style={mono} fontSize={40}>Distributed Capability Learning at the Edge</text>
        <text x={102} y={618} fill={theme.primary} fillOpacity={0.8} style={mono} fontSize={26}>Collaborative autonomy for contested, degraded environments</text>
        <text x={102} y={676} fill={theme.accent} style={mono} fontSize={19} fontWeight={700} letterSpacing={6}>DISTRIBUTED LOCAL AI FABRIC</text>
      </g>

      <g opacity={header}>
        <image href={logo} x={44} y={30} width={50} height={48} />
        <text x={108} y={64} fill={theme.textPrimary} style={mono} fontSize={22} fontWeight={700} letterSpacing={5}>ARCHIPELAGO</text>
      </g>

      {/* mission checklist */}
      <g opacity={panel}>
        <text x={1420} y={110} fill={theme.primary} fillOpacity={0.7} style={mono} fontSize={16} fontWeight={700} letterSpacing={5}>MISSION</text>
        {MISSION.slice(0, 6).map((m, i) => {
          const on = i === idx, done = i < idx;
          const y = 160 + i * 52;
          return (
            <g key={m.label} opacity={on ? 1 : done ? 0.62 : 0.4}>
              <rect x={1420} y={y - 22} width={4} height={30} fill={on ? theme.accent : theme.muted} />
              <text x={1440} y={y} fill={on ? theme.textPrimary : theme.primary} style={mono} fontSize={17.5} fontWeight={on ? 700 : 400} letterSpacing={1.2}>
                {`0${i + 1}  ${m.label}`}
              </text>
              {done && <text x={1892} y={y} textAnchor="end" fill={theme.accent} style={mono} fontSize={18}>✓</text>}
            </g>
          );
        })}
      </g>

      {/* terrain-derived layers */}
      <g opacity={panel}>
        <text x={44} y={962} fill={theme.primary} fillOpacity={0.7} style={mono} fontSize={14} fontWeight={700} letterSpacing={5}>DERIVED TERRAIN LAYERS</text>
        {LAYERS.map((l, i) => {
          const on = l.on.some(([a, b]) => t >= a && t < b);
          const x = 44 + i * 190;
          return (
            <g key={l.label} opacity={on ? 1 : 0.4}>
              <rect x={x} y={976} width={178} height={40} fill="rgba(10,10,10,0.8)" stroke={on ? theme.accent : "rgba(237,231,223,0.2)"} strokeWidth={1.5} />
              <text x={x + 89} y={1002} textAnchor="middle" fill={on ? theme.textPrimary : theme.muted} style={mono} fontSize={14} fontWeight={700} letterSpacing={2}>{l.label}</text>
            </g>
          );
        })}
      </g>

      {/* what we solve + thesis */}
      <rect x={880} y={120} width={4} height={262} fill={theme.accent} opacity={pulse(t, 67.4, 68, 71.2, 71.9)} />
      {["LEARN LOCALLY.", "TRANSFER CAPABILITIES.", "ADAPT COLLECTIVELY."].map((l, i) => (
        <text key={l} x={906} y={170 + i * 66} fill={theme.textPrimary} style={mono} fontSize={54} fontWeight={700} letterSpacing={1} opacity={pulse(t, 67.4 + i * 0.35, 68 + i * 0.35, 71.2, 71.9)}>{l}</text>
      ))}
      <text x={906} y={376} fill={theme.textSecondary} style={mono} fontSize={30} opacity={pulse(t, 68.6, 69.2, 71.2, 71.9)}>No central intelligence dependency.</text>
      {SOLVE.map((s, i) => {
        const x = 44 + [0, 250, 450, 700, 1030, 1370][i];
        return (
          <g key={s} opacity={sol(i)}>
            <rect x={x} y={976} width={s.length * 11.4 + 34} height={42} fill="rgba(10,10,10,0.85)" stroke="rgba(237,231,223,0.25)" />
            <rect x={x} y={976} width={4} height={42} fill={theme.accent} />
            <text x={x + 20} y={1004} fill={theme.textPrimary} style={mono} fontSize={15} fontWeight={700} letterSpacing={2}>{s}</text>
          </g>
        );
      })}
      <text x={44} y={962} fill={theme.primary} fillOpacity={0.7} style={mono} fontSize={14} fontWeight={700} letterSpacing={5} opacity={sol(0)}>WHAT WE SOLVE</text>

      <text x={960} y={1068} textAnchor="middle" fill={theme.primary} fillOpacity={0.55} style={mono} fontSize={13} letterSpacing={2.5}>
        CONCEPTUAL ANIMATION · TERRAIN DERIVED FROM PUBLIC ELEVATION REFERENCE · BEHAVIOR IS ILLUSTRATIVE, NOT MEASURED RESULTS
      </text>
    </>
  );
};
