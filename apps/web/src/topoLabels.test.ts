import { describe, expect, it } from "vitest";
import type { TerrainGrid } from "@archipelago/contracts";
import { contourLabels } from "./topoLabels";

const grid = (elev: (x: number, y: number) => number, size = 20, height = 12): TerrainGrid => {
  const n = size * height, idx = Array.from({ length: n }, (_, i) => i);
  return { size, height, biome: "0".repeat(n), observed: "1".repeat(n), elev_m: idx.map((i) => elev(i % size, Math.floor(i / size))), veg_pct: idx.map(() => 50) } as TerrainGrid;
};

describe("contour labels", () => {
  it("labels only multiples of the 250 m index interval", () => {
    const ls = contourLabels(grid((x) => x * 80), 625);
    expect(ls.length).toBeGreaterThan(0);
    expect(ls.every((l) => l.z % 250 === 0 && l.text === String(l.z))).toBe(true);
  });

  it("finds no labels on flat ground", () => {
    expect(contourLabels(grid(() => 100), 625)).toEqual([]);
  });
});
