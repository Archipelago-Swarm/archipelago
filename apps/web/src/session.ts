import type { WorldSnapshot } from "@archipelago/contracts";
import type { Source } from "./model";

export type RunControl = "start" | "pause" | "resume" | "step" | "stop";
export interface Transfer { sender: string; recipient: string; model_version: number }
export interface Learning { node: string; new_version: number; transfer: string; reason: string }
export interface Frame { snapshot: WorldSnapshot; transfers: Transfer[]; learning: Learning[] }

// The seam T03/T04 will fill: a WebSocket/SSE transport implements this same shape.
export interface Transport {
  open(seed: number, source: Source, onFrame: (f: Frame) => void, onClose: () => void): void;
  send(c: RunControl): void;
  close(): void;
}

export interface SessionState {
  source: Source;
  seed: number;
  connected: boolean;
  running: boolean;
  frame: Frame | null; // cleared on disconnect-reopen so stale state is never shown as fresh
}

// Minimal store: subscribe + imperative commands; React reads via useSyncExternalStore.
export function createSession(t: Transport) {
  let s: SessionState = { source: "live", seed: 1, connected: false, running: false, frame: null };
  const subs = new Set<() => void>();
  const set = (p: Partial<SessionState>) => { s = { ...s, ...p }; subs.forEach((f) => f()); };
  const open = () => t.open(s.seed, s.source,
    (frame) => set({ connected: true, frame }),
    () => set({ connected: false, running: false })); // keep last frame; UI labels it STALE
  return {
    get: () => s,
    subscribe: (f: () => void) => { subs.add(f); return () => { subs.delete(f); }; },
    connect(source: Source, seed: number) { t.close(); set({ source, seed, frame: null, running: false }); open(); },
    reconnect() { t.close(); set({ frame: null }); open(); },
    control(c: RunControl) {
      if (!s.connected) return; // never send commands into a dead stream
      t.send(c);
      set({ running: c === "start" || c === "resume" ? true : c === "step" ? s.running : false });
    },
  };
}

// Fixture-backed transport: advances sim_tick locally; used until a real API exists.
export function fixtureTransport(base: WorldSnapshot, transfers: Transfer[], learning: Learning[]): Transport & { drop(): void } {
  let timer: ReturnType<typeof setInterval> | undefined;
  let emit: ((f: Frame) => void) | undefined;
  let closeCb: (() => void) | undefined;
  let tick = 0, running = false;
  const push = () => emit?.({ snapshot: { ...base, sim_tick: tick, run_status: running ? "running" : tick === 0 ? "created" : "paused" }, transfers, learning });
  const stop = () => { clearInterval(timer); timer = undefined; };
  return {
    open(seed, _source, onFrame, onClose) {
      emit = onFrame; closeCb = onClose; tick = seed; running = false;
      setTimeout(push, 0);
    },
    send(c) {
      if (c === "start" || c === "resume") { running = true; stop(); timer = setInterval(() => { tick++; push(); }, 500); }
      else { running = false; stop(); if (c === "step") tick++; if (c === "stop") tick = 0; }
      push();
    },
    close() { stop(); emit = undefined; closeCb = undefined; },
    drop() { stop(); const cb = closeCb; emit = undefined; cb?.(); },
  };
}
