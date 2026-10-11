import { Ctx } from "../ctx";
import { CapabilityPulse } from "../components/CapabilityPulse";
import { EventBadge } from "../components/EventBadge";
import { HaloRing } from "../components/NodeLabel";
import { theme } from "../styles/theme";
import { pulse, smooth } from "../world/paths";
import { CMD, T } from "../world/scenario";
import { groundRing, poly } from "./draw";

export const JAM = { x: 84, y: 57, r: 15 };
export const EDGES: [number, number][] = [[0, 1], [0, 2], [0, 3], [1, 2], [2, 3]];
const jamAmt = (t: number) => pulse(t, 48.4, 49.4, 53.2, 54.2);
const segCut = (a: { x: number; y: number }, b: { x: number; y: number }) => {
  const dx = b.x - a.x, dy = b.y - a.y, l2 = dx * dx + dy * dy || 1;
  const u = Math.max(0, Math.min(1, ((JAM.x - a.x) * dx + (JAM.y - a.y) * dy) / l2));
  return Math.hypot(a.x + dx * u - JAM.x, a.y + dy * u - JAM.y) < JAM.r;
};

/** peer links between UAVs; links crossing the jammed zone drop while it is active */
export const Links: React.FC<{ ctx: Ctx }> = ({ ctx }) => {
  const { t, nodes, scr, alpha } = ctx;
  const j = jamAmt(t);
  return (
    <>
      {EDGES.map(([a, b]) => {
        const o = 0.3 * alpha[a] * alpha[b];
        const cut = j > 0.02 && segCut(nodes[a], nodes[b]);
        const x = (scr[a][0] + scr[b][0]) / 2, y = (scr[a][1] + scr[b][1]) / 2;
        return (
          <g key={`${a}${b}`}>
            <line x1={scr[a][0]} y1={scr[a][1]} x2={scr[b][0]} y2={scr[b][1]} stroke={theme.muted} strokeOpacity={o * (cut ? 1 - 0.8 * j : 1)} strokeWidth={1.2} strokeDasharray={cut ? "3 9" : "2 7"} strokeLinecap="round" />
            {cut && <path d={`M${x - 9} ${y - 9} L${x + 9} ${y + 9} M${x + 9} ${y - 9} L${x - 9} ${y + 9}`} stroke={theme.accent} strokeWidth={2} opacity={j * alpha[a] * alpha[b]} />}
          </g>
        );
      })}
    </>
  );
};

export const Resilience: React.FC<{ ctx: Ctx }> = ({ ctx }) => {
  const { t, scr, gnd, alpha } = ctx;
  const j = jamAmt(t);
  const [jx, jy] = gnd(JAM.x, JAM.y);
  const n2 = scr[1], n3 = scr[2], n4 = scr[3], n1 = scr[0];
  const cmd = gnd(CMD.x, CMD.y);
  const p41 = smooth((t - 61.6) / 1.7), p1c = smooth((t - 63.6) / 2);
  return (
    <>
      {/* contested comms / GPS-denied zone */}
      <g opacity={j}>
        <polyline points={poly(groundRing(ctx, JAM, JAM.r, 80))} fill={theme.accent} fillOpacity={0.07 + 0.03 * Math.sin(t * 5)} stroke={theme.accent} strokeOpacity={0.8} strokeDasharray="3 7" strokeWidth={1.5} />
        <polyline points={poly(groundRing(ctx, JAM, JAM.r * 0.62, 60))} fill="none" stroke={theme.accent} strokeOpacity={0.4} strokeDasharray="2 8" />
        <text x={jx} y={jy + 2} textAnchor="middle" fill={theme.textPrimary} fontFamily={theme.fontFamily} fontSize={22} fontWeight={700} letterSpacing={4}>COMMS DEGRADED</text>
        <text x={jx} y={jy + 32} textAnchor="middle" fill={theme.primary} fontFamily={theme.fontFamily} fontSize={16} letterSpacing={2.5}>GPS DENIED · TERRAIN-RELATIVE NAV</text>
      </g>
      <EventBadge at={n2} slot="a" title="LOCAL AUTONOMY" sub="no uplink · policy v15 runs on-node" opacity={pulse(t, 49.2, 49.8, 52.6, 53.2) * alpha[1]} />
      <EventBadge at={n3} slot="b" title="LOCAL AUTONOMY" sub="track held without network" opacity={pulse(t, 49.6, 50.2, 52.6, 53.2)} />
      <EventBadge at={n1} slot="c" title="LINKS RESTORED" sub="state sync · picture merged across nodes" opacity={pulse(t, 53.4, 54.0, 55.6, 56.2)} />

      {/* node loss */}
      <circle cx={n2[0]} cy={n2[1]} r={48} fill="none" stroke={theme.muted} strokeDasharray="4 6" opacity={pulse(t, T.loss, T.loss + 0.4, T.loss + 2.6, T.loss + 3.4)} />
      <EventBadge at={n2} slot="a" title="NODE-02" sub="OFFLINE" tone="muted" opacity={pulse(t, T.loss + 0.1, T.loss + 0.6, T.loss + 3.2, T.loss + 3.8)} />
      <EventBadge slot="b" title="NO INFORMATION LOST" sub="history + movement model replicated on NODE-01 · 03 · 04" opacity={pulse(t, T.loss + 0.8, T.loss + 1.5, T.relay - 0.6, T.relay) } />
      <EventBadge at={n4} slot="c" title="TRACK HANDOFF → NODE-04" sub="policy v15 inherited · no gap in track" opacity={pulse(t, T.handoff, T.handoff + 0.6, T.handoff + 3.6, T.handoff + 4.2)} />
      <HaloRing x={n4[0]} y={n4[1]} r={46} opacity={pulse(t, T.handoff, T.handoff + 0.6, T.handoff + 3.6, T.handoff + 4.2)} t={t} />

      {/* relay to command, store-and-forward */}
      <CapabilityPulse a={n4} b={n1} p={p41} opacity={pulse(t, 61.5, 61.8, 63.4, 63.9)} />
      <EventBadge at={n1} slot="a" title="RELAY · STORE & FORWARD" sub="NODE-04 → NODE-01 → COMMAND" opacity={pulse(t, 62.2, 62.8, 64.2, 64.8)} />
      <CapabilityPulse a={n1} b={cmd} p={p1c} opacity={pulse(t, 63.5, 63.8, 65.8, 66.3)} />
      <EventBadge at={cmd} slot="b" title="INTEL RECEIVED" sub="TRACK-A pattern · mission picture current" opacity={pulse(t, 65.4, 66.0, 67.6, 68.2)} />
    </>
  );
};
