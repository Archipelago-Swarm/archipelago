import { Ctx } from "../ctx";
import { EventBadge } from "../components/EventBadge";
import { Uav3D } from "../components/Uav3D";
import { theme } from "../styles/theme";
import { pulse, win } from "../world/paths";
import { ghostAt, THREAT_R, trackB } from "../world/scenario";
import { groundRing, LosRay, Marker, poly } from "./draw";

const N3 = 2;

/** NODE-03 meets a different valley system with the peer-acquired capability; the ghost shows what it would have done without it */
export const Generalize: React.FC<{ ctx: Ctx }> = ({ ctx }) => {
  const { t, nodes, scr, cam } = ctx;
  const live = pulse(t, 37.8, 38.6, 54.2, 54.9);
  const b = trackB(t);
  const n = nodes[N3];
  const g = ghostAt(t);
  const gO = pulse(t, 38.5, 39.3, 53, 54);
  const [x, y] = scr[N3];
  const gs = ctx.proj(g);
  const trail = Array.from({ length: 30 }, (_, k) => {
    const s = ghostAt(t - (k / 29) * 5);
    return ctx.proj(s);
  });
  const hist = Array.from({ length: 36 }, (_, k) => {
    const p = trackB(t - (k / 35) * Math.min(14, Math.max(0, t - 38) * 1.5 + 2));
    return ctx.gnd(p.x, p.y);
  });
  const yaw = Math.atan2(g.hy, g.hx);
  const sc = cam.scale(cam.project(g).d);
  const gl = Math.min(7, Math.max(3.4, 110 / sc));
  return (
    <>
      <polyline points={poly(hist)} fill="none" stroke={theme.accent} strokeOpacity={0.5 * live} strokeWidth={2} strokeDasharray="1 6" strokeLinecap="round" />
      <g opacity={live}>
        <polyline points={poly(groundRing(ctx, b, THREAT_R, 72))} fill="none" stroke={theme.accent} strokeOpacity={0.5} strokeDasharray="8 8" strokeWidth={1.2} />
      </g>
      <Marker ctx={ctx} p={b} label="TRACK-B · MOBILE" sub="different valley system · same class of problem" o={live} unc={0.8 + (1 - n.conf) * 3} />
      <LosRay ctx={ctx} from={{ x: n.x, y: n.y, z: n.z }} to={b} o={live * pulse(t, 38.5, 39.3, 54, 54.6)} />

      <g opacity={gO}>
        <polyline points={poly(trail)} fill="none" stroke={theme.muted} strokeOpacity={0.8} strokeWidth={1.6} strokeDasharray="4 5" />
        <Uav3D cam={cam} pos={g} yaw={yaw} len={gl} color={[138, 138, 138]} opacity={0.75} />
        <LosRay ctx={ctx} from={{ x: g.x, y: g.y, z: g.z }} to={b} o={0.5} />
      </g>
      <EventBadge at={gs} slot="d" title="WITHOUT CAPABILITY" sub="baseline pursuit · exposed · track intermittent" tone="muted" opacity={gO * pulse(t, 40, 40.8, 50, 51)} />
      <EventBadge at={[x, y]} slot="b" title="PEER-ACQUIRED CAPABILITY ACTIVE" sub="source: NODE-02 · standoff from first contact" opacity={pulse(t, 39.6, 40.2, 43.5, 44.2)} />
      <EventBadge at={[x, y]} slot="b" title="TRACK MAINTAINED" sub="terrain-masked approach · zero exposure" opacity={pulse(t, 44.8, 45.4, 48, 48.6) * win(t, 44, 45)} />
    </>
  );
};
