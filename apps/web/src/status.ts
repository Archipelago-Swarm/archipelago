export type Source = "fixture" | "live" | "replay";
export type Conn = "connected" | "disconnected";

// Stale state must never read as live: any non-connected live stream is labelled stale.
export function sourceLabel(source: Source, conn: Conn): string {
  if (source === "fixture") return "FIXTURE (not a live run)";
  if (source === "replay") return "REPLAY";
  return conn === "connected" ? "LIVE" : "DISCONNECTED (showing stale state)";
}

import type { LearningEvent, WorldSnapshot } from "@archipelago/contracts";
export interface Live { snap: WorldSnapshot | null; conn: Conn; learning?: Record<string, LearningEvent> }
export type LiveEvent = { t: "open" } | { t: "close" } | { t: "message"; data: string };

// Disconnect drops the snapshot so stale state cannot be mistaken for live; the server re-sends one on reconnect.
export function liveReducer(s: Live, e: LiveEvent): Live {
  if (e.t === "open") return { ...s, conn: "connected" };
  if (e.t === "close") return { snap: null, conn: "disconnected" };
  try {
    const m = JSON.parse(e.data);
    const r = m.snapshot ?? m.event ?? m;
    if (r?.kind === "world_snapshot") return { ...s, snap: r };
    // Latest event per node: its new_version is the node's reported policy version.
    if (r?.kind === "learning_event") return { ...s, learning: { ...s.learning, [r.source_node_id]: r } };
    return s;
  } catch { return s; }
}
