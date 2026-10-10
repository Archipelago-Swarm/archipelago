import type { LearningEvent, MetricSample, WorldSnapshot } from "@archipelago/contracts";
import type { Conn, Source } from "./status";
import { isTerminal } from "./status";

// A connected stream whose newest event is older than this is labelled STALE, never LIVE.
export const STALE_AFTER_MS = 10_000;
// Bounded history so a long run cannot grow the page without limit.
export const MAX_CURVE_POINTS = 200;
export const MAX_OFFERS = 50;
export const CURVE_METRIC = "episode_return";

export type FaultPhase = "connected" | "partitioned" | "recovering";
export interface CurvePoint { tick: number; value: number }
export interface Curve { unit: string; points: CurvePoint[] }
export interface NodeCard {
  policyVersion?: number; updateCount?: number; loss?: number;
  replaySize?: number; rssBytes?: number; backlog?: number; dropped?: number;
  lastEventAt?: number; lastAction?: string;
}
// LearningEvent names only the deciding node (source_node_id). The sender comes from the PeerEnvelope
// (record kind peer_envelope) for the same recipient and model version, when one was seen.
export interface Envelope { sequence: number; sender: string; recipient: string; version: number }
export interface Offer {
  sequence: number; at: number; tick: number; node: string; sender: string | null; version: number;
  transfer: "accepted" | "rejected"; reason: string | null; score: number | null; bytes: number | null;
}
export interface Panels {
  runId: string | null; lastSequence: number; lastEventAt: number | null;
  nodes: Record<string, NodeCard>; offers: Offer[]; envelopes: Envelope[]; links: [string, string][];
  positions: Record<string, { x: number; y: number }>;
  runStatus: string | null; coverage: number | null; tick: number | null;
  faultPhase: FaultPhase | null;
  train: Curve; eval: Curve;
  counters: { deadlineMissed: number | null; nodeUnavailable: number | null };
}
export type PanelAction = { t: "record"; record: unknown; at: number } | { t: "reset" };

export const emptyPanels = (): Panels => ({
  runId: null, lastSequence: 0, lastEventAt: null, nodes: {}, offers: [], envelopes: [], links: [], positions: {},
  runStatus: null, coverage: null, tick: null, faultPhase: null,
  train: { unit: "", points: [] }, eval: { unit: "", points: [] },
  counters: { deadlineMissed: null, nodeUnavailable: null },
});

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null;
const bounded = <T,>(xs: T[], max: number): T[] => (xs.length > max ? xs.slice(xs.length - max) : xs);
const signed = (n: number) => (n >= 0 ? `+${n}` : `${n}`);

function touch(s: Panels, id: string, at: number, patch: Partial<NodeCard>): Panels {
  return { ...s, nodes: { ...s.nodes, [id]: { ...s.nodes[id], ...patch, lastEventAt: at } } };
}

function applySnapshot(s: Panels, r: WorldSnapshot): Panels {
  const positions: Panels["positions"] = {};
  const nodes = { ...s.nodes };
  for (const [id, p] of Object.entries(r.poses)) {
    positions[id] = { x: p.x, y: p.y };
    const prev = s.positions[id];
    const lastAction = !prev ? nodes[id]?.lastAction : prev.x === p.x && prev.y === p.y ? "hold" : `move (${signed(p.x - prev.x)}, ${signed(p.y - prev.y)}) cells`;
    nodes[id] = { ...nodes[id], lastAction };
  }
  return { ...s, nodes, positions, links: r.topology.links as [string, string][], runStatus: r.run_status, coverage: r.coverage, tick: r.sim_tick };
}

function applyMetric(s: Panels, r: MetricSample, at: number): Panels {
  const id = r.source_node_id ?? "";
  const v = r.value;
  const node = (patch: Partial<NodeCard>) => (id ? touch(s, id, at, patch) : s);
  switch (r.metric) {
    case "train_loss": return node({ loss: v });
    case "replay_size": return node({ replaySize: v });
    case "rss_bytes": return node({ rssBytes: v });
    case "telemetry_backlog": return node({ backlog: v });
    case "telemetry_dropped": return node({ dropped: v });
    case "deadline_missed": return { ...s, counters: { ...s.counters, deadlineMissed: v } };
    case "node_unavailable": return { ...s, counters: { ...s.counters, nodeUnavailable: v } };
    // The phase field of a fault_phase sample names the phase: partition / recovery / anything else = connected.
    case "fault_phase": return { ...s, faultPhase: r.phase === "partition" ? "partitioned" : r.phase === "recovery" ? "recovering" : "connected" };
    case "coverage": return { ...s, coverage: v };
    case CURVE_METRIC: {
      const key = r.phase === "train" ? "train" : r.phase === "eval" ? "eval" : null;
      if (!key) return s;
      return { ...s, [key]: { unit: r.unit, points: bounded([...s[key].points, { tick: r.sim_tick, value: v }], MAX_CURVE_POINTS) } };
    }
    default: return node({});
  }
}

function applyEnvelope(s: Panels, r: Record<string, unknown>): Panels {
  if (typeof r.sender !== "string" || typeof r.recipient !== "string" || typeof r.model_version !== "number") return s;
  const e: Envelope = { sequence: r.sequence as number, sender: r.sender, recipient: r.recipient, version: r.model_version };
  return { ...s, envelopes: bounded([...s.envelopes, e], MAX_OFFERS * 4) };
}

function applyLearning(s: Panels, r: LearningEvent, at: number): Panels {
  if (!r.source_node_id) return s;
  const next = touch(s, r.source_node_id, at, { policyVersion: r.new_version, updateCount: r.update_count, loss: r.loss ?? undefined });
  if (r.transfer === "none") return next;
  // Newest earlier envelope addressed to the deciding node for this model version.
  const env = [...next.envelopes].reverse().find((e) => e.recipient === r.source_node_id && e.version === r.new_version && e.sequence < r.sequence);
  const offer: Offer = { sequence: r.sequence, at, tick: r.sim_tick, node: r.source_node_id, sender: env?.sender ?? null, version: r.new_version, transfer: r.transfer, reason: r.reason ?? null, score: r.candidate_score ?? null, bytes: r.bytes ?? null };
  return { ...next, offers: bounded([...next.offers, offer], MAX_OFFERS) };
}

// Pure: builds panel state from canonical event records. Duplicate and out-of-order sequences are ignored.
export function panelsReducer(s: Panels, a: PanelAction): Panels {
  if (a.t === "reset") return emptyPanels();
  const r = a.record;
  if (!isObj(r) || typeof r.sequence !== "number" || typeof r.run_id !== "string") return s;
  if (s.runId !== null && r.run_id !== s.runId) s = emptyPanels();
  if (r.sequence <= s.lastSequence) return s;
  let next: Panels;
  if (r.kind === "world_snapshot") next = applySnapshot(s, r as unknown as WorldSnapshot);
  else if (r.kind === "metric_sample") next = applyMetric(s, r as unknown as MetricSample, a.at);
  else if (r.kind === "learning_event") next = applyLearning(s, r as unknown as LearningEvent, a.at);
  else if (r.kind === "peer_envelope") next = applyEnvelope(s, r);
  else return s;
  return { ...next, runId: r.run_id, lastSequence: r.sequence, lastEventAt: a.at };
}

// Extracts the canonical record from a stream message or a paged event.
export const recordOf = (m: unknown): unknown => (isObj(m) ? (m.snapshot ?? m.event ?? m) : m);

export type Freshness = "fresh" | "stale" | "never";
export function freshness(lastAt: number | null | undefined, now: number): Freshness {
  if (lastAt == null) return "never";
  return now - lastAt > STALE_AFTER_MS ? "stale" : "fresh";
}

// LIVE only while connected and the newest event is fresh. Replay, fixture and terminal runs never read LIVE.
export function panelLabel(source: Source, conn: Conn, status: string | undefined, lastAt: number | null | undefined, now: number): string {
  if (source === "fixture") return "FIXTURE (not a live run)";
  if (source === "replay") return "REPLAY";
  if (conn !== "connected") return "DISCONNECTED (no live data)";
  if (isTerminal(status)) return `${status!.toUpperCase()} (not live)`;
  if (status !== "paused" && freshness(lastAt, now) !== "fresh") return "STALE (no recent events)";
  return "LIVE";
}

// Replay scrubbing: panel state as of the selected world_snapshot (0-based among snapshots). Later records
// (policy versions, transfers, fault phase) must not appear at earlier frames.
export function panelsAtFrame(records: unknown[], frame: number): Panels {
  let seen = -1;
  let upto = -1;
  for (let i = 0; i < records.length; i++) {
    const r = records[i];
    if (isObj(r) && r.kind === "world_snapshot" && ++seen === frame) { upto = i; break; }
  }
  let s = emptyPanels();
  for (let i = 0; i <= upto; i++) s = panelsReducer(s, { t: "record", record: records[i], at: 0 });
  return s;
}
