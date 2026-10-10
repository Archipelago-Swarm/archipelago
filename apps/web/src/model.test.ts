import { describe, expect, it } from "vitest";
import { statusLabel } from "./model";

describe("statusLabel", () => {
  it("labels replay and live", () => {
    expect(statusLabel("replay", false)).toBe("REPLAY");
    expect(statusLabel("live", true)).toBe("LIVE");
  });
  it("never shows disconnected live data as live", () => {
    expect(statusLabel("live", false)).toMatch(/STALE/);
  });
});
