// API-level smoke for the dashboard's run lifecycle (not a browser test: no Playwright is installed).
// Usage: ARCHIPELAGO_URL=http://127.0.0.1:8000 [ARCHIPELAGO_API_TOKEN=..] node tests/web/smoke.mjs
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";

const base = process.env.ARCHIPELAGO_URL ?? "http://127.0.0.1:8000";
const headers = { "content-type": "application/json", ...(process.env.ARCHIPELAGO_API_TOKEN && { authorization: `Bearer ${process.env.ARCHIPELAGO_API_TOKEN}` }) };
const api = async (path, body, extra = {}) => {
  const r = await fetch(base + path, { method: body ? "POST" : "GET", headers: { ...headers, ...extra }, body: body && JSON.stringify(body) });
  assert.ok(r.ok, `${path} -> ${r.status} ${await r.clone().text()}`);
  return r.json();
};
const cfg = JSON.parse(readFileSync(new URL("../../packages/contracts/fixtures/good/run_config.json", import.meta.url)));
cfg.run_id = `smoke-${Date.now()}`;
await api("/v1/runs", cfg, { "Idempotency-Key": cfg.run_id });
const id = cfg.run_id;
const cmd = async (command) => { // same fresh-revision protocol as apps/web/src/client.ts
  const { revision } = await api(`/v1/runs/${id}`);
  return api(`/v1/runs/${id}/commands`, { command, command_id: crypto.randomUUID(), expected_revision: revision });
};
assert.equal((await cmd("pause")).status, "paused");
assert.equal((await cmd("resume")).status, "running");
assert.equal((await cmd("pause")).status, "paused");
await cmd("step");
await cmd("stop");
const ev = await api(`/v1/runs/${id}/events?after_sequence=0&limit=500`);
assert.ok(ev.events.some((e) => e.snapshot?.kind === "world_snapshot"), "replay has recorded world snapshots");
console.log(`ok: ${id} ${ev.events.length} replayable events`);
