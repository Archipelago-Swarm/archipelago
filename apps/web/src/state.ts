import type { WorldSnapshot } from "@archipelago/contracts";

export type Conn = "connecting" | "live" | "disconnected" | "replay";
export interface View {
  conn: Conn;
  runId: string;
  status: string;
  revision: number;
  tick: number;
  seq: number;
  snap: WorldSnapshot | null;
}
export const initial = (runId: string): View => ({
  conn: "connecting", runId, status: "unknown", revision: 0, tick: 0, seq: 0, snap: null,
});

// Stream messages carry {sequence,type,tick,status,snapshot?}; a gap or stale sequence is ignored/flagged by the caller.
export function apply(v: View, m: { sequence?: number; type: string; tick?: number; status?: string; snapshot?: WorldSnapshot }): View {
  if (m.type === "resnapshot") return v;
  if (m.sequence !== undefined && m.sequence < v.seq) return v; // out-of-order: never regress
  const snap = m.snapshot && "poses" in m.snapshot ? m.snapshot : v.snap;
  return { ...v, seq: m.sequence ?? v.seq, tick: m.tick ?? v.tick, status: m.status ?? v.status, snap };
}

// Anything not currently streamed live is shown as such, never as live state.
export const onClose = (v: View): View => (v.conn === "replay" ? v : { ...v, conn: "disconnected" });
export const label = (v: View): string =>
  v.conn === "live" ? "LIVE" : v.conn === "replay" ? "REPLAY" : v.conn === "connecting" ? "CONNECTING" : "DISCONNECTED (state is stale)";
