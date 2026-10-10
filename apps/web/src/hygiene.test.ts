import { readdirSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// Acceptance: no embedded credentials or hardcoded success metrics in shipped app code.
const dir = new URL(".", import.meta.url);
const sources = readdirSync(dir).filter((f) => /\.tsx?$/.test(f) && !/\.test\./.test(f) && f !== "fixture.ts");

describe("app source hygiene", () => {
  it("has sources to scan", () => expect(sources.length).toBeGreaterThan(3));
  for (const f of sources) {
    const text = readFileSync(new URL(f, dir), "utf8");
    it(`${f}: no credentials`, () => {
      expect(text).not.toMatch(/postgres(ql)?:\/\/|mongodb:\/\/|mysql:\/\/|Bearer\s+[A-Za-z0-9._-]{8,}|(password|secret|api_?key)\s*[:=]\s*["'][^"']+["']/i);
    });
    it(`${f}: no hardcoded success metrics`, () => {
      expect(text).not.toMatch(/(coverage|success|reward|score)\w*\s*[:=]\s*(0?\.\d+|[1-9]\d*(\.\d+)?)\s*[,;)}]/i);
    });
  }
});
