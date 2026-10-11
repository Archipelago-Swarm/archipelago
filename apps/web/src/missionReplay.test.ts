import { expect, it } from "vitest";
import { aggregate, applyMessage, emptyBuffer, explainLink, feedAt, frameAt, linkStyle, poiLabel, worldTransform, type Arm, type Frame, type RFLink } from "./missionReplay";
import { pickSeeds } from "./MissionApp";

const uav = (id: string, x: number, h: number, status = "OPERATIONAL") => ({ id, status, position: { x, y: 0 }, heading: h, altitudeMeters: 400 + x }) as never;
const frame = (tick: number, x: number, h: number, st = "OPERATIONAL"): Frame => ({ tick, time: tick * 30, uavs: [uav("U", x, h, st)], pois: [], links: [], disruptions: [], mission: {} as never, eventCount: 0, decisionCount: 0 });
const link = (o: Partial<RFLink>): RFLink => ({ id: "a~b", sourceNodeId: "a", targetNodeId: "b", distanceKm: 22, horizontalDistanceMeters: 22000, geometricHorizonMeters: 164800, lineOfSight: "CLEAR", rfQuality: 0.8, bandwidthFactor: 0.9, state: "EXCELLENT", connected: true, attenuationFactor: 1, disruptionFactor: 1, debug: { platformFactor: 1, minClearanceMeters: 400, linkClass: "NORMAL", rejectReason: null }, ...o }) as RFLink;

it("interpolates motion between ticks and floors everything else; heading takes the shortest arc", () => {
  const v = frameAt([frame(0, 0, 3.0), frame(1, 100, -3.0)], 30, 15)!;
  expect(v.uavs[0].position.x).toBe(50);
  expect(v.uavs[0].altitudeMeters).toBe(450);
  expect(Math.cos(v.uavs[0].heading)).toBeCloseTo(-1, 1); // crosses pi, not 0
  expect(v.floor.tick).toBe(0);
  expect(frameAt([frame(0, 0, 0), frame(1, 100, 0)], 30, 999)!.uavs[0].position.x).toBe(100); // clamps at last frame
  expect(frameAt([frame(0, 0, 0), frame(1, 100, 0, "FAILED")], 30, 15)!.uavs[0].position.x).toBe(0);
  expect(frameAt([], 30, 0)).toBeNull();
});

it("filters feeds by playhead and appends stream deltas", () => {
  expect(feedAt([{ timestamp: 10 }, { timestamp: 40 }], 30)).toHaveLength(1);
  let b = applyMessage(emptyBuffer(), "meta", { dt: 30 });
  b = applyMessage(b, "tick", { frame: frame(0, 0, 0), events: [{ id: "E1" }], decisions: [] });
  b = applyMessage(b, "tick", { frame: frame(1, 0, 0), events: [{ id: "E2" }], decisions: [] });
  expect(b.frames).toHaveLength(2); expect(b.events.map((e) => e.id)).toEqual(["E1", "E2"]);
  expect(applyMessage(b, "meta", { dt: 30 }).frames).toHaveLength(0); // reconnect clears buffers
});

it("never reveals trueType before verification", () => {
  const p = { state: "DISCOVERED", trueType: "VEHICLE", classification: "SIGNAL", confidence: 0.5 } as never;
  expect(poiLabel(p)).not.toContain("VEHICLE");
  expect(poiLabel({ state: "UNKNOWN", trueType: "VEHICLE" } as never)).toBeNull();
  expect(poiLabel({ state: "VERIFIED", trueType: "VEHICLE" } as never)).toBe("VEHICLE");
});

it("maps world corners and styles links by state", () => {
  const w = { width: 400000, height: 500000, tileMeters: 100000, tilesX: 4, tilesY: 5, units: "meters" as const };
  const { project } = worldTransform(w, 640, 800);
  expect(project({ x: 0, y: 0 })).toEqual([0, 0]); expect(project({ x: 400000, y: 500000 })).toEqual([640, 800]);
  expect(linkStyle(link({}))!.color).toBe("#3ddc84");
  expect(linkStyle(link({ connected: false, state: "DISCONNECTED" }))).toBeNull();
  expect(linkStyle(link({ connected: false, state: "DISCONNECTED" }), true)!.opacity).toBe(0.25);
  expect(linkStyle(link({ connected: false, debug: { rejectReason: "BEYOND_MAX_RANGE" } as never }), true)).toBeNull();
  expect(explainLink(link({ disruptionFactor: 0.359, connected: false }))).toContain("36%");
});

it("aggregates skills on vs off across maps and picks distinct seeds", () => {
  const arm = (status: string, t: number): Arm => ({ mission: { status, elapsedTime: t, verifiedPois: 6, totalPois: 6, fleetKnowledgeCoverage: 1 }, stats: { redundancyRatio: 0.5, partitions: 1, skillTransfers: 2 } }) as never;
  const g = aggregate([{ seed: 1, uavs: 6, on: arm("SUCCESS", 100), off: arm("FAILED", 900) }, { seed: 2, uavs: 6, on: arm("SUCCESS", 100), off: arm("SUCCESS", 200) }]);
  expect(g.on.successRate).toBe(1); expect(g.off.successRate).toBe(0.5); expect(g.skillsWin).toBe(2); expect(g.off.meanTime).toBe(200);
  expect(new Set(pickSeeds(20)).size).toBe(20); expect(pickSeeds(3, 10)).toEqual([10, 11, 12]);
});
