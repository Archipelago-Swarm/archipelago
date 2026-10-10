import { describe, expect, it } from "vitest";
import snapshot from "../../../packages/contracts/fixtures/good/world_snapshot.json";

describe("web consumes the shared fixture", () => {
  it("has the pose count declared by the contract fixture", () => {
    expect(Object.keys(snapshot.poses)).toHaveLength(2);
    expect(snapshot.poses["node-01"].z).toBe(0);
  });
});
