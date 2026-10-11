import { AbsoluteFill, useCurrentFrame } from "remotion";
import { Ctx, mkGnd, mkProj } from "./ctx";
import { TerrainGL } from "./components/TerrainGL";
import { Uav3D } from "./components/Uav3D";
import { NodeLabel } from "./components/NodeLabel";
import { Generalize } from "./scenes/Generalize";
import { Overview } from "./scenes/Overview";
import { Links, Resilience } from "./scenes/Resilience";
import { Track } from "./scenes/Track";
import { Cards, Transfer } from "./scenes/Transfer";
import { theme } from "./styles/theme";
import { makeCam, viewAt } from "./world/camera3d";
import { viewshed } from "./world/geo";
import { alive, sampleAt, THREAT_R, trackA, trackB } from "./world/scenario";
import { FPS, H, pulse, SCALE, W, win } from "./world/paths";

export const ArchipelagoLoop: React.FC = () => {
  const t = useCurrentFrame() / FPS;
  const cam = makeCam(viewAt(t));
  const proj = mkProj(cam);
  const gnd = mkGnd(cam);
  const nodes = [0, 1, 2, 3].map((i) => sampleAt(i, t));
  const ctx: Ctx = { t, cam, proj, gnd, nodes, alpha: [0, 1, 2, 3].map((i) => alive(i, t)), scr: nodes.map((n) => proj(n)) };

  // terrain overlays: hostile line-of-sight risk (orange) and concealed ground (stone), per track
  const lA = pulse(t, 13.5, 14.5, 31, 33), cA = win(t, 25, 27) * (1 - win(t, 47, 49));
  const lB = pulse(t, 38, 39, 46, 48), cB = pulse(t, 40, 41, 53, 54.5);
  const a = trackA(t), b = trackB(t);
  const layers = [
    ...(lA + cA > 0.01 ? [{ vs: viewshed(a.x, a.y, THREAT_R), los: lA, cover: cA }] : []),
    ...(lB + cB > 0.01 ? [{ vs: viewshed(b.x, b.y, THREAT_R), los: lB, cover: cB }] : []),
  ];

  return (
    <AbsoluteFill style={{ background: theme.background }}>
      <div style={{ width: W, height: H, transform: `scale(${SCALE})`, transformOrigin: "0 0", position: "relative" }}>
      <TerrainGL cam={cam} layers={layers} />
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ position: "absolute", inset: 0 }}>
        <defs>
          <linearGradient id="scrimL" x1="0" x2="1" y1="0" y2="0">
            <stop offset="0" stopColor={theme.background} stopOpacity={0.9} />
            <stop offset="0.4" stopColor={theme.background} stopOpacity={0.55} />
            <stop offset="0.7" stopColor={theme.background} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Track ctx={ctx} />
        <Generalize ctx={ctx} />
        <Links ctx={ctx} />
        {nodes.map((n, i) => {
          const g = gnd(n.x, n.y);
          const [x, y] = ctx.scr[i];
          const yaw = Math.atan2(n.hy, n.hx);
          const p = sampleAt(i, t - 0.4);
          let dy = yaw - Math.atan2(p.hy, p.hx);
          dy = Math.atan2(Math.sin(dy), Math.cos(dy));
          const sc = cam.scale(cam.project(n).d);
          const lenW = Math.min(7, Math.max(3.4, 110 / sc));
          const a = ctx.alpha[i];
          return (
            <g key={i}>
              <line x1={x} y1={y} x2={g[0]} y2={g[1]} stroke={theme.primary} strokeOpacity={0.22 * a} strokeDasharray="2 4" />
              <ellipse cx={g[0]} cy={g[1]} rx={lenW * sc * 0.28} ry={lenW * sc * 0.1} fill="#000" opacity={0.45 * a} />
              <Uav3D cam={cam} pos={n} yaw={yaw} bank={Math.max(-0.45, Math.min(0.45, -dy * 1.6))} len={lenW} opacity={a} />
              <NodeLabel x={x} y={y} id={`NODE-0${i + 1}`} opacity={a} active={i === 1 && t > 25 && t < 40} />
            </g>
          );
        })}
        <Transfer ctx={ctx} />
        <Resilience ctx={ctx} />
        <Cards ctx={ctx} />
        <Overview ctx={ctx} />
      </svg>
      </div>
    </AbsoluteFill>
  );
};

