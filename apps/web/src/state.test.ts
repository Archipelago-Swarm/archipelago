import type { View } from "./state";
import { describe, expect, it } from "vitest";
import { apply, initial, label, onClose } from "./state";

describe("view state", () => {
  it("ignores out-of-order events and marks stale on close", () => {
    let v: View = { ...initial("r1"), conn: "live" };
    v = apply(v, { sequence: 5, type: "status", tick: 3, status: "paused" });
    v = apply(v, { sequence: 4, type: "status", status: "running" });
    expect(v.status).toBe("paused");
    expect(label(onClose(v))).toContain("stale");
    expect(label(v)).toBe("LIVE");
  });
});
