export type Source = "live" | "replay";

// Never label disconnected data as live: stale wins over source.
export function statusLabel(source: Source, connected: boolean): string {
  if (source === "replay") return "REPLAY";
  return connected ? "LIVE" : "DISCONNECTED - showing last state, STALE";
}
