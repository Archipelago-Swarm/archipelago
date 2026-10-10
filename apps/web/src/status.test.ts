import { expect, it } from "vitest";
import { sourceLabel } from "./status";

it("never labels a disconnected live stream as live", () => {
  expect(sourceLabel("live", "connected")).toBe("LIVE");
  expect(sourceLabel("live", "disconnected")).toMatch(/no live data/);
  expect(sourceLabel("fixture", "connected")).toMatch(/not a live/);
  expect(sourceLabel("replay", "disconnected")).toBe("REPLAY");
});
