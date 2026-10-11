import { linkStyle, poiLabel, worldTransform, type Meta, type MissionEvent, type View } from "./missionReplay";

const OBJ_COLOR: Record<string, string> = { DISCOVER_POI: "#4aa3ff", VERIFY_POI: "#f5b942", STAY_OPERATIONAL: "#f47b3c", MAINTAIN_CONNECTIVITY: "#a78bfa", SHARE_INFORMATION: "#3ddc84" };
const COMP = ["#3ddc84", "#4aa3ff", "#f5b942", "#ef6a4c", "#a78bfa", "#2dd4bf", "#f472b6"];
const COMM_STATE: Record<string, string> = { CONNECTED: "#3ddc84", DEGRADED: "#f5b942", ISOLATED: "#ef4444", OFFLINE: "#777" };
const VW = 640;

export interface Props {
  meta: Meta; view: View; events: MissionEvent[]; selUav: string | null; selLink: string | null; showWeak: boolean; showRings: boolean;
  onUav(id: string): void; onLink(id: string): void;
}

export function MissionMap({ meta, view, events, selUav, selLink, showWeak, showRings, onUav, onLink }: Props) {
  const w = meta.world, VH = Math.round((VW * w.height) / w.width), { scale, project } = worldTransform(w, VW, VH);
  const pos = Object.fromEntries(view.uavs.map((u) => [u.id, project(u.position)]));
  const t = view.t, { floor } = view;
  const recentTransfers = events.filter((e) => e.type === "SKILL_TRANSFERRED" && e.timestamp <= t && t - e.timestamp <= 60);
  const km100 = 100 * 1000 * scale;
  return (
    <svg className="m-map" viewBox={`0 0 ${VW} ${VH}`} role="img" aria-label="Mission map">
      <defs><marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L8 4L0 8z" fill="#f47b3c" /></marker></defs>
      <rect x={0} y={0} width={VW} height={VH} fill="#101214" />
      {Array.from({ length: w.tilesX + 1 }, (_, k) => <line key={`vx${k}`} x1={project({ x: k * w.tileMeters, y: 0 })[0]} x2={project({ x: k * w.tileMeters, y: 0 })[0]} y1={0} y2={VH} stroke="#2a2d31" />)}
      {Array.from({ length: w.tilesY + 1 }, (_, k) => <line key={`hy${k}`} y1={project({ x: 0, y: k * w.tileMeters })[1]} y2={project({ x: 0, y: k * w.tileMeters })[1]} x1={0} x2={VW} stroke="#2a2d31" />)}
      {floor.disruptions.filter((d) => d.active && d.position && d.radius).map((d) => {
        const [cx, cy] = project(d.position!), comm = d.type === "COMMUNICATION_DEGRADATION";
        return <circle key={d.id} cx={cx} cy={cy} r={d.radius! * scale} fill={comm ? "#f5b94222" : "#4aa3ff22"} stroke={comm ? "#f5b942" : "#4aa3ff"} strokeDasharray="6 4"><title>{d.type} {d.id}</title></circle>;
      })}
      {floor.links.map((l) => {
        const s = linkStyle(l, showWeak), a = pos[l.sourceNodeId], b = pos[l.targetNodeId];
        if (!s || !a || !b) return null;
        return (
          <g key={l.id} onClick={() => onLink(l.id)} style={{ cursor: "pointer" }}>
            <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke="transparent" strokeWidth={10} />
            <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={s.color} strokeWidth={l.id === selLink ? s.width + 2 : s.width} strokeOpacity={s.opacity} strokeDasharray={s.dash} />
          </g>
        );
      })}
      {recentTransfers.map((e) => {
        const a = pos[e.sourceNodeId], b = pos[e.targetNodeId];
        return a && b ? <line key={e.id} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke="#f47b3c" strokeWidth={2} strokeDasharray="5 3" markerEnd="url(#arrow)" /> : null;
      })}
      {floor.pois.map((p) => {
        const label = poiLabel(p);
        if (!label) return null; // UNKNOWN: ground truth stays hidden
        const [x, y] = project(p.position), ok = p.state === "VERIFIED";
        return (
          <g key={p.id}>
            <circle cx={x} cy={y} r={7} fill="#101214" stroke={ok ? "#3ddc84" : "#f5b942"} strokeWidth={2} />
            <text x={x} y={y + 3.5} textAnchor="middle" fontSize={10} fill={ok ? "#3ddc84" : "#f5b942"}>{ok ? "✓" : "?"}</text>
            <text x={x + 10} y={y + 3} fontSize={9} fill="#cfc8bf">{p.id} {label}</text>
            <title>{p.id}: known by {p.knownBy.length}, verified by {p.verifiedBy.length}</title>
          </g>
        );
      })}
      {view.uavs.map((u) => {
        const [x, y] = pos[u.id], dead = u.status === "FAILED", col = dead ? "#666" : OBJ_COLOR[u.currentObjective] ?? "#ccc";
        const climbing = !dead && u.altitudeMeters > meta.uavSpec.cruiseAltitudeAglMeters + 1;
        return (
          <g key={u.id} onClick={() => onUav(u.id)} style={{ cursor: "pointer" }}>
            {showRings && !dead && <circle cx={x} cy={y} r={u.sensorRadius * scale} fill="none" stroke={col} strokeOpacity={0.25} />}
            {!dead && u.networkComponent >= 0 && <circle cx={x} cy={y} r={11} fill="none" stroke={COMP[u.networkComponent % COMP.length]} strokeWidth={2} />}
            {u.activeSkill && !dead && <circle cx={x} cy={y} r={15} fill="none" stroke="#f47b3c" strokeWidth={1.5} strokeDasharray="2 3" />}
            <g transform={`translate(${x} ${y}) rotate(${(u.heading * 180) / Math.PI})`}><path d="M7 0L-5 4.5L-3 0L-5 -4.5z" fill={col} stroke={u.id === selUav ? "#fff" : "none"} /></g>
            <text x={x + 12} y={y - 9} fontSize={9} fill={dead ? "#777" : "#ede7df"} textDecoration={dead ? "line-through" : undefined}>{u.id.replace("UAV-", "U")}</text>
            {!dead && <text x={x + 12} y={y + 1} fontSize={8} fill={COMM_STATE[u.communicationState]}>{Math.round(u.altitudeMeters)} m{climbing ? " ↑" : ""}{u.sensorState === "DEGRADED" ? " ⚠" : ""}</text>}
          </g>
        );
      })}
      <line x1={12} x2={12 + km100} y1={VH - 14} y2={VH - 14} stroke="#ede7df" strokeWidth={2} />
      <text x={12} y={VH - 20} fontSize={10} fill="#ede7df">100 km</text>
    </svg>
  );
}
