// Mission replay: types (FRONTEND_INTEGRATION.md 19.a), pure render helpers and the live/offline loaders.
// No RF maths here: link fields are rendered exactly as emitted.
import type { TerrainGrid } from "@archipelago/contracts";
export type Id = string;
export interface XY { x: number; y: number }
export type PoiType = "INFRASTRUCTURE" | "VEHICLE" | "SIGNAL";
export type RFState = "EXCELLENT" | "GOOD" | "DEGRADED" | "MARGINAL" | "DISCONNECTED";

export interface Skill {
  id: string; name: string; version: number; sourceNodeId: Id; createdAt: number; receivedAt: number | null; receivedFrom: Id | null;
  confidence: number; utilityScore: number; status: "LOCAL" | "RECEIVED" | "VALIDATING" | "ADOPTED" | "REJECTED";
  metadata: { spacing_m: number; trigger: string };
}
export interface UavState {
  id: Id; status: "OPERATIONAL" | "FAILED"; position: XY; heading: number; speed: number; health: number;
  sensorRadius: number; altitudeMeters: number; commRadius: number;
  currentObjective: string; currentAction: string; sensorState: "NOMINAL" | "DEGRADED" | "OFFLINE";
  communicationState: "CONNECTED" | "DEGRADED" | "ISOLATED" | "OFFLINE"; neighbors: Id[]; networkComponent: number;
  activeSkill: string | null; skills: Skill[]; localKnowledgeCount: number; knownPois: Id[]; verifiedPois: Id[];
  searchedCells: number; lastSync: Record<Id, number>;
}
export interface PoiState {
  id: Id; position: XY; trueType: PoiType; state: "UNKNOWN" | "DISCOVERED" | "VERIFIED";
  classification: PoiType | "UNKNOWN"; confidence: number; knownBy: Id[]; verifiedBy: Id[];
}
export interface RFLink {
  id: string; sourceNodeId: Id; targetNodeId: Id; distanceKm: number; horizontalDistanceMeters: number;
  sourceAltitudeMeters: number; targetAltitudeMeters: number; geometricHorizonMeters: number;
  lineOfSight: "CLEAR" | "PARTIAL" | "BLOCKED" | "NOT_EVALUATED"; rfQuality: number; bandwidthFactor: number;
  state: RFState; connected: boolean; attenuationFactor: number; disruptionFactor: number; lastUpdated: number;
  debug: { platformFactor: number; minClearanceMeters: number | null; linkClass: string; rejectReason: "BEYOND_HORIZON" | "BEYOND_MAX_RANGE" | null };
}
export interface Disruption {
  id: Id; type: "COMMUNICATION_DEGRADATION" | "NAVIGATION_DEGRADATION" | "PLATFORM_FAILURE"; active: boolean;
  startTime: number; endTime: number | null; position: XY | null; radius: number | null; severity: number; nodeId: Id | null;
}
export interface MissionState {
  seed: number; status: "RUNNING" | "SUCCESS" | "FAILED"; elapsedTime: number; timeLimit: number; totalPois: number;
  requiredPois: number; discoveredPois: number; verifiedPois: number; fleetKnowledgeCoverage: number;
  knowledgeThreshold: number; operationalNodes: number; totalNodes: number;
}
export interface Frame {
  tick: number; time: number; mission: MissionState; uavs: UavState[]; pois: PoiState[]; links: RFLink[];
  disruptions: Disruption[]; eventCount: number; decisionCount: number;
}
export interface MissionEvent { id: string; type: string; timestamp: number; demo: boolean; [k: string]: any } // eslint-disable-line @typescript-eslint/no-explicit-any
export interface DecisionEvent {
  timestamp: number; nodeId: Id; state: string; action: string; reason: string; skillUsed: string | null; target: [number, number] | null;
  metrics: { altitudeMeters?: number };
}
export interface Stats {
  redundantCellMarks: number; uniqueCellMarks: number; skillsLearned: number; skillTransfers: number; skillAdoptions: number;
  skillRejections: number; partitions: number; dataSyncs: number; redundancyRatio: number; missionStatus: "RUNNING" | "SUCCESS" | "FAILED";
  elapsedTime: number; firstSkillLearnedAt: number | null; finalSkillHolders: number;
}
export interface Meta {
  seed: number; dt: number; skillsEnabled: boolean;
  world: { width: number; height: number; tileMeters: number; tilesX: number; tilesY: number; units: "meters"; cellMeters: number; terrain: TerrainGrid };
  searchGrid: { nx: number; ny: number };
  uavSpec: any; rfModel: any; missionRules: any; config: { skill_transfer_s: number; n_uavs: number }; // eslint-disable-line @typescript-eslint/no-explicit-any
}
export interface Buffer { meta: Meta | null; frames: Frame[]; events: MissionEvent[]; decisions: DecisionEvent[]; stats: Stats | null }
export const emptyBuffer = (): Buffer => ({ meta: null, frames: [], events: [], decisions: [], stats: null });

// ---- units / formatting ----
export const pct = (x: number) => `${Math.round(x * 100)}%`;
export const km = (m: number) => { const k = m / 1000; return k < 100 ? k.toFixed(1) : String(Math.round(k)); };
export const hms = (s: number) => {
  const t = Math.max(0, Math.round(s)), p = (n: number) => String(n).padStart(2, "0");
  return `${Math.floor(t / 3600)}:${p(Math.floor((t % 3600) / 60))}:${p(t % 60)}`;
};
const DISRUPTION_LABEL: Record<string, string> = { COMMUNICATION_DEGRADATION: "Communication degradation", NAVIGATION_DEGRADATION: "Navigation degradation", PLATFORM_FAILURE: "Platform failure" };
export const disruptionLabel = (t: string) => DISRUPTION_LABEL[t] ?? t;

// ---- world to screen (19.d): y grows downward, no flip ----
export function worldTransform(w: Pick<Meta["world"], "width" | "height">, viewW: number, viewH: number) {
  const scale = Math.min(viewW / w.width, viewH / w.height), offX = (viewW - w.width * scale) / 2, offY = (viewH - w.height * scale) / 2;
  return { scale, project: (p: XY): [number, number] => [offX + p.x * scale, offY + p.y * scale] };
}

// ---- playback buffer ----
export function applyMessage(b: Buffer, name: "meta" | "tick" | "end", data: any): Buffer { // eslint-disable-line @typescript-eslint/no-explicit-any
  if (name === "meta") return { ...emptyBuffer(), meta: data };
  if (name === "end") return { ...b, stats: data.stats };
  return { ...b, frames: [...b.frames, data.frame], events: [...b.events, ...data.events], decisions: [...b.decisions, ...data.decisions] };
}

export interface View { floor: Frame; uavs: UavState[]; t: number }
const wrap = (hA: number, hB: number, a: number) => hA + a * ((((hB - hA + 3 * Math.PI) % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI) - Math.PI);
/** Floor frame holds everything discrete; only position/altitude/heading are interpolated (19.c). */
export function frameAt(frames: Frame[], dt: number, t: number): View | null {
  if (!frames.length) return null;
  const last = frames.length - 1, i = Math.min(last, Math.max(0, Math.floor(t / dt)));
  const A = frames[i], B = frames[Math.min(i + 1, last)], a = i === last ? 0 : Math.min(1, Math.max(0, (t - A.time) / dt));
  const uavs = A.uavs.map((u, k) => {
    const v = B.uavs[k];
    if (!v || u.status === "FAILED" || v.status === "FAILED" || a === 0) return u;
    return {
      ...u, heading: wrap(u.heading, v.heading, a), altitudeMeters: u.altitudeMeters + a * (v.altitudeMeters - u.altitudeMeters),
      position: { x: u.position.x + a * (v.position.x - u.position.x), y: u.position.y + a * (v.position.y - u.position.y) },
    };
  });
  return { floor: A, uavs, t };
}

export const feedAt = <T extends { timestamp: number }>(items: T[], t: number) => items.filter((e) => e.timestamp <= t);
export const demoFeed = (events: MissionEvent[], t: number) => feedAt(events, t).filter((e) => e.demo);

/** Ground truth is only revealed once verified (19.e). */
export const poiLabel = (p: PoiState) =>
  p.state === "VERIFIED" ? p.trueType : p.state === "DISCOVERED" ? `${p.classification} ${pct(p.confidence)}?` : null;

// ---- link styling (section 4): colour from state, opacity from rfQuality, never from distance ----
const LINK_COLOR: Record<RFState, string> = { EXCELLENT: "#3ddc84", GOOD: "#7bd88f", DEGRADED: "#f5b942", MARGINAL: "#ef6a4c", DISCONNECTED: "#ef4444" };
export function linkStyle(l: RFLink, showWeak = false) {
  if (l.connected) return { color: LINK_COLOR[l.state], width: 1 + 3 * l.bandwidthFactor, opacity: Math.min(1, Math.max(0.35, 0.35 + 0.65 * l.rfQuality)), dash: undefined as string | undefined };
  if (showWeak && l.debug.rejectReason === null) return { color: LINK_COLOR.DISCONNECTED, width: 1, opacity: 0.25, dash: "4 4" };
  return null;
}

export function explainLink(l: RFLink): string {
  const d = l.debug;
  if (d.rejectReason === "BEYOND_MAX_RANGE") return `${l.sourceNodeId} to ${l.targetNodeId} is ${l.distanceKm.toFixed(1)} km apart, beyond the maximum routine range.`;
  if (d.rejectReason === "BEYOND_HORIZON") return `Radio horizon is ${km(l.geometricHorizonMeters)} km but the link is ${l.distanceKm.toFixed(1)} km; climbing would extend it.`;
  if (l.lineOfSight === "BLOCKED" || l.lineOfSight === "PARTIAL") return `Terrain blocks the path (min clearance ${d.minClearanceMeters} m).`;
  if (l.disruptionFactor < 1) return `Communication-degradation zone reduces quality to ${Math.round(l.disruptionFactor * 100)}%.`;
  if (!l.connected) return `Quality ${l.rfQuality.toFixed(3)} is below the 0.15 threshold: ${l.distanceKm.toFixed(1)} km is too far for this pair.`;
  return `${d.linkClass} link, ${l.state}.`;
}

export function feedText(e: MissionEvent): string {
  switch (e.type) {
    case "MISSION_STARTED": return `Mission started: ${e.requiredPois}/${e.totalPois} POIs required, limit ${e.timeLimit / 3600} h`;
    case "POI_DISCOVERED": return `${e.nodeId} discovered ${e.poiId} (confidence ${pct(e.confidence)})`;
    case "POI_VERIFIED": return `${e.nodeId} verified ${e.poiId} as ${e.classification} (${pct(e.confidence)})`;
    case "DISRUPTION_STARTED": return `${disruptionLabel(e.disruptionType)} started (radius ${Math.round(e.radius / 1000)} km, severity ${pct(e.severity)})`;
    case "DISRUPTION_ENDED": return `${disruptionLabel(e.disruptionType)} ended`;
    case "UAV_FAILED": return `${e.nodeId} failed`;
    case "NETWORK_PARTITIONED": return `Network partitioned into ${e.components.length} groups: ${e.components.map((c: Id[]) => c.join(", ")).join(" | ")}`;
    case "NETWORK_RECONNECTED": return "Network reconnected";
    case "SKILL_LEARNED": return `${e.nodeId} learned skill ${e.skillId}: ${e.reason}`;
    case "SKILL_TRANSFERRED": return `${e.sourceNodeId} sent ${e.skillId} to ${e.targetNodeId} (RF ${pct(e.rfQuality)}, bandwidth ${pct(e.bandwidthFactor)})`;
    case "SKILL_ADOPTED": return `${e.nodeId} adopted ${e.skillId} from ${e.fromNodeId}`;
    case "SKILL_REJECTED": return `${e.nodeId} rejected ${e.skillId}: ${e.reason}`;
    case "SKILL_USED": return `${e.nodeId} is using ${e.skillId} to choose search cells`;
    case "MISSION_SUCCESS": return `Mission succeeded at ${hms(e.elapsedTime)}: ${e.verifiedPois} POIs verified, coverage ${pct(e.fleetKnowledgeCoverage)}`;
    case "MISSION_FAILED": return `Mission failed at ${hms(e.elapsedTime)}: ${e.verifiedPois} POIs verified, coverage ${pct(e.fleetKnowledgeCoverage)}`;
    default: return e.type;
  }
}

export function decisionText(d: DecisionEvent): string {
  if (d.action === "climb_for_los") return `${d.nodeId} is climbing to ${d.metrics.altitudeMeters} m to regain line of sight`;
  const tgt = d.target ? ` -> (${(d.target[0] / 1000).toFixed(0)}, ${(d.target[1] / 1000).toFixed(0)}) km` : "";
  return `${d.nodeId}: ${d.action}${tgt}. ${d.reason}${d.skillUsed ? ` [skill ${d.skillUsed}]` : ""}`;
}

// ---- batch of maps: skills on vs off ----
export interface Arm { mission: MissionState; stats: Stats }
export interface MapSummary { seed: number; uavs: number; on: Arm; off: Arm }
const mean = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
export function armAggregate(arms: Arm[]) {
  const ok = arms.filter((a) => a.mission.status === "SUCCESS");
  return {
    n: arms.length, successes: ok.length, successRate: arms.length ? ok.length / arms.length : 0,
    meanTime: mean(ok.map((a) => a.mission.elapsedTime)),
    meanVerified: mean(arms.map((a) => a.mission.verifiedPois / a.mission.totalPois)),
    meanCoverage: mean(arms.map((a) => a.mission.fleetKnowledgeCoverage)),
    meanRedundancy: mean(arms.map((a) => a.stats.redundancyRatio)),
    meanPartitions: mean(arms.map((a) => a.stats.partitions)),
    meanTransfers: mean(arms.map((a) => a.stats.skillTransfers)),
  };
}
export function aggregate(rows: MapSummary[]) {
  const on = armAggregate(rows.map((r) => r.on)), off = armAggregate(rows.map((r) => r.off));
  const better = (r: MapSummary) => {
    const a = r.on.mission, b = r.off.mission;
    if (a.status !== b.status) return a.status === "SUCCESS" ? 1 : -1;
    return a.status === "SUCCESS" ? Math.sign(b.elapsedTime - a.elapsedTime) : Math.sign(a.verifiedPois - b.verifiedPois);
  };
  const v = rows.map(better);
  return { on, off, skillsWin: v.filter((x) => x > 0).length, skillsLose: v.filter((x) => x < 0).length, ties: v.filter((x) => x === 0).length };
}

// ---- loaders ----
export const BASE: string = (import.meta as any).env?.VITE_MISSION_API ?? ""; // eslint-disable-line @typescript-eslint/no-explicit-any
export const SERVER_CMD = 'PYTHONPATH="packages/mission:packages/sim" python -m archipelago_mission.serve --port 8765';

export async function fetchSummary(seed: number, uavs: number, signal?: AbortSignal): Promise<MapSummary> {
  const r = await fetch(`${BASE}/api/mission/summary?seed=${seed}&uavs=${uavs}`, { signal });
  if (!r.ok) throw new Error(`Mission server returned HTTP ${r.status}. Start it: ${SERVER_CMD}`);
  return r.json();
}

/** Offline fallback: committed replay file, valid JSON only (a dev server may answer 200 with index.html). */
export async function loadOfflineReplay(seed: number): Promise<Buffer> {
  const r = await fetch(`/mission/seed-${seed}.json`);
  if (!r.ok) throw new Error(`no offline replay for seed ${seed} (HTTP ${r.status})`);
  const j = await r.json();
  if (!j.frames?.length || j.meta?.world?.units !== "meters") throw new Error("offline replay is malformed");
  return { meta: j.meta, frames: j.frames, events: j.events, decisions: j.decisions, stats: j.stats };
}
