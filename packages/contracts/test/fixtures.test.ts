import Ajv from "ajv";
import addFormats from "ajv-formats";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { ArchipelagoRecord } from "../generated/types.ts";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const schema = JSON.parse(readFileSync(join(root, "schemas/record.schema.json"), "utf8"));
const ajv = new Ajv({ strict: false, allErrors: true });
addFormats(ajv);
const validate = ajv.compile(schema);

const load = (dir: string) =>
  readdirSync(join(root, "fixtures", dir))
    .filter((f) => f.endsWith(".json"))
    .map((f) => [f, readFileSync(join(root, "fixtures", dir, f), "utf8")] as const);

describe("shared fixtures (same files as pytest)", () => {
  for (const [name, text] of load("good")) {
    it(`accepts good/${name}`, () => {
      const record = JSON.parse(text) as ArchipelagoRecord;
      expect(validate(record), JSON.stringify(validate.errors)).toBe(true);
      expect(record.kind).toBe(name.replace(".json", ""));
    });
  }
  for (const [name, text] of load("bad")) {
    it(`rejects bad/${name}`, () => {
      let ok = false;
      try {
        ok = validate(JSON.parse(text)) as boolean;
      } catch {
        ok = false; // unparseable JSON (e.g. NaN literal) is a rejection
      }
      expect(ok).toBe(false);
    });
  }
});
