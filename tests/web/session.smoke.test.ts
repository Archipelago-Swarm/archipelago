import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { WorldSnapshot } from "@archipelago/contracts";
import snapshot from "../../packages/contracts/fixtures/good/world_snapshot.json";
import { createSession, fixtureTransport } from "../../apps/web/src/session";

// Not a browser: drives the same session/transport the UI uses (no browser runner is installed).
const base = snapshot as unknown as WorldSnapshot;
beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });

describe("run lifecycle", () => {
  it("start, pause, resume, replay; disconnect clears connected and blocks controls", () => {
    const t = fixtureTransport(base, [], []);
    const s = createSession(t);
    s.connect("replay", 7);
    vi.advanceTimersByTime(1);
    expect(s.get().connected).toBe(true);
    expect(s.get().frame?.snapshot.sim_tick).toBe(7);

    s.control("start");
    vi.advanceTimersByTime(1000);
    expect(s.get().frame?.snapshot.run_status).toBe("running");
    expect(s.get().frame?.snapshot.sim_tick).toBe(9);
    s.control("pause");
    vi.advanceTimersByTime(2000);
    expect(s.get().frame?.snapshot.sim_tick).toBe(9);
    expect(s.get().frame?.snapshot.run_status).toBe("paused");
    s.control("resume");
    vi.advanceTimersByTime(500);
    expect(s.get().frame?.snapshot.sim_tick).toBe(10);

    t.drop(); // disconnect while running
    expect(s.get().connected).toBe(false);
    expect(s.get().running).toBe(false);
    vi.advanceTimersByTime(2000);
    expect(s.get().frame?.snapshot.sim_tick).toBe(10); // no updates after drop
    s.control("start");
    expect(s.get().running).toBe(false);

    s.reconnect();
    expect(s.get().frame).toBeNull(); // stale frame discarded until fresh data arrives
    vi.advanceTimersByTime(1);
    expect(s.get().connected).toBe(true);
    expect(s.get().frame?.snapshot.sim_tick).toBe(7);
  });
});
