export type Source = "fixture" | "live" | "replay";
export type Conn = "connected" | "disconnected";

// Stale state must never read as live: any non-connected live stream is labelled stale.
export function sourceLabel(source: Source, conn: Conn): string {
  if (source === "fixture") return "FIXTURE (not a live run)";
  if (source === "replay") return "REPLAY";
  return conn === "connected" ? "LIVE" : "DISCONNECTED (showing stale state)";
}
