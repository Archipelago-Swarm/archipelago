import { afterEach, expect, test, vi } from "vitest";
import { connectStream, liveReducer, type Live } from "./status";

class FakeWS {
  static all: FakeWS[] = [];
  onopen?: () => void; onmessage?: (e: { data: string }) => void; onclose?: () => void;
  constructor(public url: string) { FakeWS.all.push(this); }
  close() { this.onclose?.(); }
}
afterEach(() => { FakeWS.all = []; vi.useRealTimers(); });

test("disconnect clears state, reconnect after 2s re-syncs from the next snapshot", () => {
  vi.useFakeTimers();
  let s: Live = { snap: null, conn: "disconnected" };
  const stop = connectStream("ws://x/s", (e) => { s = liveReducer(s, e); }, FakeWS as unknown as typeof WebSocket);
  const snap = (tick: number) => JSON.stringify({ snapshot: { kind: "world_snapshot", tick } });
  FakeWS.all[0].onopen!(); FakeWS.all[0].onmessage!({ data: snap(1) });
  expect(s.conn).toBe("connected"); expect(s.snap).toMatchObject({ tick: 1 });
  FakeWS.all[0].onclose!();
  expect(s).toEqual({ snap: null, conn: "disconnected" });
  vi.advanceTimersByTime(1999); expect(FakeWS.all).toHaveLength(1);
  vi.advanceTimersByTime(1); expect(FakeWS.all).toHaveLength(2);
  FakeWS.all[1].onopen!(); expect(s.snap).toBeNull(); // no stale snapshot shown as live
  FakeWS.all[1].onmessage!({ data: snap(5) }); expect(s.snap).toMatchObject({ tick: 5 });
  stop(); vi.advanceTimersByTime(5000); expect(FakeWS.all).toHaveLength(2); // stopper cancels reconnect
});
