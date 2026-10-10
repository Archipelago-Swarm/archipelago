import { expect, it } from "vitest";
import { sourceLabel } from "./status";

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
