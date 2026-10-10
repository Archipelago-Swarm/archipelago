export type Source = "live" | "replay";

// Never label disconnected data as live: stale wins over source.
export function statusLabel(source: Source, connected: boolean): string {
  if (source === "replay") return connected ? "REPLAY" : "REPLAY - DISCONNECTED, STALE";
  return connected ? "LIVE" : "DISCONNECTED - showing last state, STALE";
}
