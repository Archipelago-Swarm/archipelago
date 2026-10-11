import { linkStyle, poiLabel, type RFLink, type View } from "./missionReplay";

const OBJ_COLOR: Record<string, string> = { DISCOVER_POI: "#4aa3ff", VERIFY_POI: "#f5b942", STAY_OPERATIONAL: "#f47b3c", MAINTAIN_CONNECTIVITY: "#a78bfa", SHARE_INFORMATION: "#3ddc84" };
export const objectiveColor = (u: { status: string; currentObjective: string }) => (u.status === "FAILED" ? "#666" : OBJ_COLOR[u.currentObjective] ?? "#ccc");
const COMP = ["#3ddc84", "#4aa3ff", "#f5b942", "#ef6a4c", "#a78bfa", "#2dd4bf", "#f472b6"]; // one colour per connected group
export const ZONE_NAV = "74,163,255", ZONE_COMM = "245,185,66"; // rgb triples of the hazard zones
export type LegendRow = { kind: "uav" | "zone" | "poi-ok" | "poi-unk" | "group" | "skill" | "link" | "sensor"; color: string; label: string };
/** Key for everything the overlay draws; FlightMap renders these rows under its own legend entries. Labels stay under ~26 characters. */
export const MISSION_LEGEND: LegendRow[] = [
  { kind: "zone", color: ZONE_NAV, label: "NAV-JAMMED ZONE" },
  { kind: "zone", color: ZONE_COMM, label: "COMMS-JAMMED ZONE" },
  { kind: "poi-ok", color: "#3ddc84", label: "POI VERIFIED" },
  { kind: "poi-unk", color: "#f5b942", label: "POI FOUND, UNVERIFIED" },
  { kind: "uav", color: OBJ_COLOR.DISCOVER_POI, label: "UAV: SEARCHING" },
  { kind: "uav", color: OBJ_COLOR.VERIFY_POI, label: "UAV: VERIFYING POI" },
  { kind: "uav", color: OBJ_COLOR.MAINTAIN_CONNECTIVITY, label: "UAV: KEEPING LINK" },
  { kind: "uav", color: OBJ_COLOR.SHARE_INFORMATION, label: "UAV: SHARING DATA" },
  { kind: "uav", color: OBJ_COLOR.STAY_OPERATIONAL, label: "UAV: SURVIVING" },
  { kind: "uav", color: "#666", label: "UAV: FAILED" },
  { kind: "group", color: "#3ddc84", label: "RING = RADIO GROUP" },
  { kind: "skill", color: "#f47b3c", label: "DASHED = USING SKILL" },
  { kind: "link", color: "#3ddc84", label: "RADIO LINK" },
  { kind: "sensor", color: "#4aa3ff", label: "SENSOR RANGE" },
];
const COMM_STATE: Record<string, string> = { CONNECTED: "#3ddc84", DEGRADED: "#f5b942", ISOLATED: "#ef4444", OFFLINE: "#777" };
const MONO = "Consolas, 'Courier New', monospace";

/** What FlightMap hands an overlay each frame: the 2D context plus the map's own projection, so overlays sit on the 3D terrain. */
export interface MapOverlay {
  g: CanvasRenderingContext2D;
  S(x: number, y: number, z?: number): [number, number]; // world metres -> screen px (perspective when tilted)
  ground(x: number, y: number): number; // terrain height at a world point (0 when flat)
  air(x: number, y: number): [number, number]; // where FlightMap draws an aircraft at (x, y): same height, so markers sit exactly on it
  ring(x: number, y: number, r: number): void; // path of a circle lying on the ground
}

export interface MissionDraw { view: View; showWeak: boolean; showRings: boolean; selUav: string | null; selLink: string | null }

/** Hazard zones, RF links, sensor rings and POI markers of the mission viewer, drawn over FlightMap's terrain. */
export function drawMission({ g, S, ground, air, ring }: MapOverlay, { view, showWeak, showRings, selUav, selLink }: MissionDraw): void {
  const P = (x: number, y: number, agl: number) => S(x, y, ground(x, y) + agl);
  for (const d of view.floor.disruptions) { // area-denial zones: nav = blue, comms = amber
    if (!d.active || !d.position || !d.radius) continue;
    const col = d.type === "COMMUNICATION_DEGRADATION" ? ZONE_COMM : ZONE_NAV;
    ring(d.position.x, d.position.y, d.radius);
    g.fillStyle = `rgba(${col},0.16)`; g.fill(); g.strokeStyle = `rgb(${col})`; g.lineWidth = 1.5; g.setLineDash([6, 4]); g.stroke(); g.setLineDash([]);
  }
  const at: Record<string, [number, number]> = {};
  for (const u of view.uavs) at[u.id] = air(u.position.x, u.position.y);
  for (const l of view.floor.links as RFLink[]) {
    const s = linkStyle(l, showWeak), a = at[l.sourceNodeId], b = at[l.targetNodeId];
    if (!s || !a || !b) continue;
    g.beginPath(); g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]);
    g.globalAlpha = s.opacity; g.strokeStyle = s.color; g.lineWidth = l.id === selLink ? s.width + 2 : s.width;
    g.setLineDash(s.dash ? s.dash.split(/[ ,]+/).map(Number) : []); g.stroke(); g.setLineDash([]); g.globalAlpha = 1;
  }
  for (const u of view.uavs) {
    if (u.status === "FAILED") continue;
    const col = objectiveColor(u), [x, y] = at[u.id];
    if (u.networkComponent >= 0) { g.beginPath(); g.arc(x, y, 14, 0, 2 * Math.PI); g.strokeStyle = COMP[u.networkComponent % COMP.length]; g.lineWidth = 2; g.stroke(); } // which RF group the UAV is in
    if (u.activeSkill) { g.beginPath(); g.arc(x, y, 18, 0, 2 * Math.PI); g.strokeStyle = "#f47b3c"; g.lineWidth = 1.5; g.setLineDash([2, 3]); g.stroke(); g.setLineDash([]); } // using a learned skill
    if (showRings) { ring(u.position.x, u.position.y, u.sensorRadius); g.fillStyle = col + "14"; g.fill(); g.strokeStyle = col + "66"; g.lineWidth = 1; g.stroke(); }
    g.font = `11px ${MONO}`; g.fillStyle = "#EDE7DF"; g.fillText(u.id.replace("UAV-", "U"), x + 16, y - 10);
    g.font = `9px ${MONO}`; g.fillStyle = COMM_STATE[u.communicationState] ?? "#ccc";
    g.fillText(`${Math.round(u.altitudeMeters)} m${u.sensorState === "DEGRADED" ? " ⚠" : ""}`, x + 14, y + 2);
    if (u.id === selUav) { g.beginPath(); g.arc(x, y, 20, 0, 2 * Math.PI); g.strokeStyle = "#fff"; g.lineWidth = 1; g.stroke(); }
  }
  for (const p of view.floor.pois) { // unknown POIs stay hidden: ground truth appears only once discovered or verified
    const label = poiLabel(p);
    if (!label) continue;
    const [x, y] = P(p.position.x, p.position.y, 0), ok = p.state === "VERIFIED", col = ok ? "#3ddc84" : "#f5b942";
    g.beginPath(); g.arc(x, y, 7, 0, 2 * Math.PI); g.fillStyle = "#101214"; g.fill(); g.strokeStyle = col; g.lineWidth = 2; g.stroke();
    g.fillStyle = col; g.font = `10px ${MONO}`; g.textAlign = "center"; g.fillText(ok ? "✓" : "?", x, y + 3.5); g.textAlign = "left";
    g.fillStyle = "#EDE7DF"; g.font = `9px ${MONO}`; g.fillText(`${p.id} ${label}`, x + 10, y + 3);
  }
}
