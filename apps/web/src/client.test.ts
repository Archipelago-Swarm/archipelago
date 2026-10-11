import { describe, expect, it } from "vitest";
import { ApiError, loadReplay, nodeHealth, sendCommand } from "./client";

const res = (status: number, body: unknown) => new Response(JSON.stringify(body), { status });

describe("client", () => {
  it("re-reads the revision and retries once after a 409", async () => {
    const posts: number[] = [];
    let rev = 1;
    const f = (async (url: string, init?: RequestInit) => {
      if (!init) return res(200, { revision: rev });
      posts.push(JSON.parse(init.body as string).expected_revision);
      if (posts.length === 1) { rev = 2; return res(409, {}); }
      return res(200, { revision: 3 });
    }) as typeof fetch;
    expect((await sendCommand("r", "pause", f)).revision).toBe(3);
    expect(posts).toEqual([1, 2]);
  });
  it("surfaces 401 and network failure as errors", async () => {
    await expect(sendCommand("r", "pause", (async () => res(401, {})) as typeof fetch)).rejects.toMatchObject({ status: 401 });
    await expect(sendCommand("r", "pause", (async () => { throw new Error("x"); }) as typeof fetch)).rejects.toBeInstanceOf(ApiError);
  });
  it("pages replay events into frames", async () => {
    const snap = (t: number) => ({ kind: "world_snapshot", sim_tick: t });
    const pages = [
      { events: [{ sequence: 1, snapshot: snap(1) }, { sequence: 2 }], latest_sequence: 3 },
      { events: [{ sequence: 3, snapshot: snap(3) }], latest_sequence: 3 },
    ];
    let i = 0;
    const f = (async () => res(200, pages[i++])) as typeof fetch;
    expect((await loadReplay("r", f)).map((s) => s.sim_tick)).toEqual([1, 3]);
  });
  it("reports isolated drones", () => {
    const s = { poses: { a: {}, b: {}, c: {} }, topology: { links: [["a", "b"]] } } as never;
    expect(nodeHealth(s)).toEqual({ a: "linked", b: "linked", c: "isolated" });
  });
});

it("listRuns unwraps the runs array", async () => {
  const { listRuns } = await import("./client");
  const f = (async () => new Response(JSON.stringify({ runs: [{ run_id: "r1", status: "completed", tick: 3, completion_reason: null }] }))) as typeof fetch;
  expect((await listRuns(f)).map((r) => r.run_id)).toEqual(["r1"]);
});

it("startRun sends the map seed as map_offset and leaves the config seeds alone", async () => {
  const { startRun } = await import("./client");
  let body: Record<string, unknown> = {};
  const f = (async (_u: unknown, init?: RequestInit) => { body = JSON.parse(String(init?.body)); return new Response("{}"); }) as typeof fetch;
  await startRun({ seeds: { env: 1000 } }, 42, f);
  expect(body.map_offset).toBe(42);
  expect(body.seeds).toEqual({ env: 1000 });
  expect("mission" in body).toBe(false);
  await startRun({ seeds: { env: 1000 } }, 42, f, { type: "coverage", n_targets: 0 });
  expect(body.mission).toEqual({ type: "coverage", n_targets: 0 });
});
