import { expect, it } from "vitest";
import { isTerminal, liveReducer, sourceLabel, type Live } from "./status";

it("never labels a disconnected live stream as live", () => {
  expect(sourceLabel("live", "connected")).toBe("LIVE");
  expect(sourceLabel("live", "disconnected")).toMatch(/no live data/);
  expect(sourceLabel("fixture", "connected")).toMatch(/not a live/);
  expect(sourceLabel("replay", "disconnected")).toBe("REPLAY");
});

it("labels terminal runs honestly even while the stream is connected", () => {
  expect(sourceLabel("live", "connected", "completed")).toBe("COMPLETED (not live)");
  expect(sourceLabel("live", "connected", "interrupted")).toBe("INTERRUPTED (not live)");
  expect(sourceLabel("live", "connected", "running")).toBe("LIVE");
});

it("a recovered run (status only, empty snapshot) reads interrupted, has no snapshot, and disables commands", () => {
  let s: Live = { snap: null, conn: "disconnected" };
  s = liveReducer(s, { t: "open" });
  s = liveReducer(s, { t: "message", data: JSON.stringify({ type: "snapshot", status: "interrupted", snapshot: {} }) });
  expect(s.snap).toBeNull();
  expect(isTerminal(s.status)).toBe(true);
  expect(sourceLabel("live", s.conn, s.status)).toBe("INTERRUPTED (not live)");
});
