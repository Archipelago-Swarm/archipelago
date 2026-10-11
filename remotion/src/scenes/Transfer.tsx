import { Ctx } from "../ctx";
import { CapabilityPulse } from "../components/CapabilityPulse";
import { EventBadge } from "../components/EventBadge";
import { HaloRing } from "../components/NodeLabel";
import { theme } from "../styles/theme";
import { pulse, smooth, win } from "../world/paths";
import { sampleAt, T } from "../world/scenario";
import { recent } from "./Track";

type Bars = { conf: number; expo: number; cover: number };
export const barsFor = (i: number, t: number): Bars => {
  let st = 0;
  for (let k = 0; k < 10; k++) st += sampleAt(i, t - k * 0.15).phase === "standoff" ? 1 : 0;
  const s = st / 10;
  const e = recent(i, t, "exposed");
  return { conf: sampleAt(i, t).conf, expo: e, cover: s * (1 - e) * 0.9 + (1 - s) * 0.12 };
};

const Bar: React.FC<{ k: string; v: number; hot?: boolean }> = ({ k, v, hot }) => (
  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
    <span style={{ width: 104, color: theme.muted, letterSpacing: 2, fontSize: 14 }}>{k}</span>
    <div style={{ width: 190, height: 7, background: "rgba(237,231,223,0.14)" }}>
      <div style={{ width: `${Math.round(Math.min(1, Math.max(0, v)) * 100)}%`, height: 7, background: hot ? theme.accent : theme.primary }} />
    </div>
  </div>
);

export type CardProps = { slot: number; title: string; policy: string; capability: string; source: string; i: number; ctx: Ctx; o: number; fresh?: boolean };
/** Fixed telemetry card (left column). One per node that carries the learned capability. */
export const NodeCard: React.FC<CardProps> = ({ slot, title, policy, capability, source, i, ctx, o, fresh }) => {
  if (o < 0.01) return null;
  const b = barsFor(i, ctx.t);
  const row = (k: string, v: string, hot = false) => (
    <div style={{ display: "flex", gap: 12 }}>
      <span style={{ width: 128, color: theme.muted, letterSpacing: 2, fontSize: 14 }}>{k}</span>
      <span style={{ color: hot ? theme.accent : theme.textPrimary, fontWeight: hot ? 700 : 400 }}>{v}</span>
    </div>
  );
  return (
    <foreignObject x={44} y={104} width={470} height={280} style={{ overflow: "visible" }} opacity={o}>
      <div style={{ display: "inline-flex", flexDirection: "column", gap: 7, padding: "15px 20px", background: "rgba(10,10,10,0.82)", border: "1px solid rgba(237,231,223,0.16)", borderLeft: `4px solid ${fresh ? theme.accent : theme.muted}`, borderRadius: theme.borderRadius, fontFamily: theme.fontFamily, fontSize: 17, whiteSpace: "nowrap" }}>
        <span style={{ fontSize: 21, fontWeight: 700, letterSpacing: 3.5, color: theme.textPrimary, marginBottom: 3 }}>{title}</span>
        {row("POLICY", policy, policy.includes("v15"))}
        {row("CAPABILITY", capability)}
        {row("SOURCE", source)}
        <div style={{ height: 5 }} />
        <Bar k="TRACK" v={b.conf} />
        <Bar k="EXPOSURE" v={b.expo} hot={b.expo > 0.3} />
        <Bar k="COVER" v={b.cover} />
      </div>
    </foreignObject>
  );
};

export const Cards: React.FC<{ ctx: Ctx }> = ({ ctx }) => {
  const { t } = ctx;
  const learned = win(t, T.learn + 0.3, T.learn + 0.8) > 0.5;
  const lost = win(t, T.loss + 0.4, T.loss + 0.9) > 0.5;
  // one card at a time, handed from node to node as the story moves
  const cx = (a: number, b: number, c: number, d: number) => pulse(t, a, b, c, d);
  return (
    <>
      <NodeCard slot={0} i={1} ctx={ctx} title={lost ? "NODE-02 · OFFLINE" : "NODE-02"} policy={learned ? "v15 (local)" : "v14"} capability={learned ? "terrain-masking-v7" : "none"} source={learned ? "learned locally" : "—"} o={cx(T.contact + 1, T.contact + 1.8, 36.4, 36.9) + cx(T.loss, T.loss + 0.5, T.handoff - 0.3, T.handoff + 0.2) * 0.7} fresh={learned} />
      <NodeCard slot={0} i={2} ctx={ctx} title="NODE-03" policy="v15" capability="terrain-masking-v7" source={lost ? "NODE-02 (offline)" : "NODE-02"} o={cx(36.6, 37.2, T.loss - 0.5, T.loss)} fresh />
      <NodeCard slot={0} i={3} ctx={ctx} title="NODE-04" policy="v15" capability="terrain-masking-v7" source="NODE-03 (peer relay)" o={cx(T.handoff - 0.2, T.handoff + 0.4, 62, 62.8)} fresh />
    </>
  );
};

/** capability offer -> policy delta -> evaluate -> accept, NODE-02 -> NODE-03, then on to NODE-04 */
export const Transfer: React.FC<{ ctx: Ctx }> = ({ ctx }) => {
  const { t, scr } = ctx;
  const [a, b, c] = [scr[1], scr[2], scr[3]];
  const p1 = smooth((t - 33.2) / 1.7);
  const p2 = smooth((t - 39.6) / 1.8);
  const head: [number, number] = [a[0] + (b[0] - a[0]) * p1, a[1] + (b[1] - a[1]) * p1];
  return (
    <>
      <CapabilityPulse a={a} b={b} p={p1} opacity={pulse(t, 33.0, 33.3, 35.2, 35.7)} />
      <EventBadge at={a} slot="a" title="CAPABILITY OFFER" sub="NODE-02 → NODE-03 · learned behaviour, not coordinates" opacity={pulse(t, T.transfer + 0.3, T.transfer + 0.9, 34.2, 34.7)} />
      <EventBadge at={head} slot="c" title="POLICY DELTA" sub="terrain-masking-v7" opacity={pulse(t, 33.5, 33.9, 35.0, 35.5)} />
      <HaloRing x={b[0]} y={b[1]} r={46} opacity={pulse(t, 35.4, 35.8, 36.2, 36.5)} t={t} spin />
      <EventBadge at={b} slot="b" title="EVALUATING" sub="peer validation · local replay" tone="muted" opacity={pulse(t, 35.4, 35.8, 36.2, 36.5)} />
      <HaloRing x={b[0]} y={b[1]} r={46} opacity={pulse(t, 36.4, 36.9, 38, 38.8)} t={t} />
      <EventBadge at={b} slot="b" title="ACCEPTED" sub="POLICY v14 → v15" opacity={pulse(t, 36.5, 37.0, 38.3, 38.9)} />
      <CapabilityPulse a={b} b={c} p={p2} opacity={pulse(t, 39.5, 39.8, 41.6, 42.1)} />
      <EventBadge at={c} slot="c" title="ACCEPTED" sub="v15 propagated · NODE-03 → NODE-04" opacity={pulse(t, 41.5, 42.0, 43.4, 44.0)} />
    </>
  );
};
