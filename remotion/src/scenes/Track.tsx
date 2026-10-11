import { Ctx } from "../ctx";
import { EventBadge } from "../components/EventBadge";
import { HaloRing } from "../components/NodeLabel";
import { theme } from "../styles/theme";
import { pulse, smooth, win } from "../world/paths";
import { sampleAt, T, THREAT_R, trackA } from "../world/scenario";
import { groundRing, LosRay, Marker, poly } from "./draw";

const N2 = 1;
const N4 = 3;

/** mean of a flag over the last `len` seconds (smooths the sim's per-frame flicker for display) */
export const recent = (i: number, t: number, key: "exposed" | "tracked", len = 1.5) => {
  let s = 0;
  for (let k = 0; k < 10; k++) s += sampleAt(i, t - (k * len) / 10)[key] ? 1 : 0;
  return s / 10;
};

/** contact -> baseline pursuit -> pattern mapping -> learned standoff, all on TRACK-A */
export const Track: React.FC<{ ctx: Ctx }> = ({ ctx }) => {
  const { t, nodes, scr } = ctx;
  const k = t < T.loss + 0.2 ? N2 : N4; // after NODE-02 is lost NODE-04 inherits the picture
  const n = nodes[k];
  const a = trackA(t);
  const live = pulse(t, T.contact + 0.3, T.contact + 1.2, T.relay + 1.2, T.relay + 2);
  const conf = n.conf;
  const lost = smooth((0.55 - conf) / 0.35);
  const base = pulse(t, T.baseline, T.baseline + 0.8, T.learn, T.learn + 0.6);
  const [x, y] = scr[N2];

  // movement-pattern map: where the track has been, building up through the baseline phase
  const lookback = Math.min(20, Math.max(0, t - T.baseline) * 1.4 + 3);
  const hist = Array.from({ length: 42 }, (_, k) => {
    const p = trackA(t - (k / 41) * lookback);
    return ctx.gnd(p.x, p.y);
  });
  const mapO = win(t, T.baseline + 1, T.baseline + 3) * (1 - 0.0 * win(t, 60, 61));
  const pred = Array.from({ length: 20 }, (_, k) => {
    const p = trackA(t + (k / 19) * 8);
    return ctx.gnd(p.x, p.y);
  });
  const predO = pulse(t, T.learn - 0.5, T.learn + 0.7, T.loss, T.loss + 0.8);

  return (
    <>
      <polyline points={poly(hist)} fill="none" stroke={theme.accent} strokeOpacity={0.55 * mapO} strokeWidth={2} strokeDasharray="1 6" strokeLinecap="round" />
      <polyline points={poly(pred)} fill="none" stroke={theme.primary} strokeOpacity={0.7 * predO} strokeWidth={1.6} strokeDasharray="7 6" />
      <g opacity={base * 0.0 + live}>
        <polyline points={poly(groundRing(ctx, a, THREAT_R, 72))} fill="none" stroke={theme.accent} strokeOpacity={0.55} strokeDasharray="8 8" strokeWidth={1.2} />
      </g>
      <Marker ctx={ctx} p={a} label="TRACK-A · MOBILE" sub={conf > 0.45 ? "track maintained" : "track degraded"} o={live} unc={0.8 + (1 - conf) * 3.2} lost={lost} />
      {[N2, N4].map((j) => {
        // hand the sensor line from NODE-02 to NODE-04 as a cross-fade rather than a jump
        const w = j === N2 ? 1 - win(t, T.loss, T.loss + 1.2) : win(t, T.loss, T.loss + 1.2);
        return <LosRay key={j} ctx={ctx} from={{ x: nodes[j].x, y: nodes[j].y, z: nodes[j].z }} to={a} o={live * w * pulse(t, T.contact, T.contact + 1, T.relay + 1.2, T.relay + 2)} />;
      })}

      <HaloRing x={x} y={y} r={46} opacity={pulse(t, T.contact + 0.2, T.contact + 0.8, T.contact + 2.6, T.contact + 3.2)} t={t} />
      <EventBadge at={[x, y]} slot="a" title="TRACK ACQUIRED" sub="TRACK-A · mobile · hostile" opacity={pulse(t, T.contact + 0.6, T.contact + 1.2, T.contact + 4, T.contact + 4.8)} />
      <EventBadge at={[x, y]} slot="a" title="BASELINE PURSUIT" sub="terrain ignored · inside hostile sensor horizon" tone="muted" opacity={pulse(t, T.baseline + 0.2, T.baseline + 0.9, T.baseline + 4, T.baseline + 4.8)} />
      <EventBadge at={[x, y]} slot="b" title="TRACK DEGRADED" sub="line of sight masked by terrain" tone="muted" opacity={base * lost * 0.95} />
      <EventBadge at={[x, y]} slot="a" title="MAPPING MOVEMENT PATTERN" sub="valley-following · ridge-masking" opacity={pulse(t, T.baseline + 5.5, T.baseline + 6.2, T.learn - 1.2, T.learn - 0.6)} />
      <EventBadge at={[x, y]} slot="a" title="CAPABILITY LEARNED" sub="terrain-masking-v7" opacity={pulse(t, T.learn - 0.2, T.learn + 0.5, T.learn + 3, T.learn + 3.6)} />
      <EventBadge at={[x, y]} slot="a" title="ADAPTIVE STANDOFF" sub="ridge overwatch · outside hostile horizon · LOS held" opacity={pulse(t, T.learn + 3.8, T.learn + 4.4, T.transfer - 0.4, T.transfer + 0.2)} />
    </>
  );
};
