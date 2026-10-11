import type { WorldSnapshot } from "@archipelago/contracts";

export class ApiError extends Error {
  constructor(public status: number, msg: string) { super(msg); }
}
type Fetch = typeof fetch;
export interface RunView { run_id: string; status: string; revision: number; completion_reason: string | null; tick: number }

async function call<T>(f: Fetch, url: string, init?: RequestInit): Promise<T> {
  let r: Response;
  try { r = await f(url, init); } catch { throw new ApiError(0, "API unreachable"); }
  if (r.status === 401) throw new ApiError(401, "authentication required");
  if (!r.ok) throw new ApiError(r.status, `${r.status} ${await r.text().catch(() => "")}`.trim());
  return r.json() as Promise<T>;
}
const json = (b: unknown): RequestInit => ({ method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(b) });

export const login = (token: string, f: Fetch = fetch) => call(f, "/v1/login", json({ token }));
export const getRun = (id: string, f: Fetch = fetch) => call<RunView>(f, `/v1/runs/${id}`);

// The scenario is the shared run_config; map_offset shifts the server plan's episode seeds, so each offset is a different set of maps.
export function startRun(base: Record<string, unknown>, mapSeed: number, f: Fetch = fetch) {
  const run_id = `run-${Date.now().toString(36)}-${mapSeed}`;
  const config = { ...base, run_id, map_offset: mapSeed };
  return call<RunView>(f, "/v1/runs", { ...json(config), headers: { "content-type": "application/json", "Idempotency-Key": run_id } });
}

// Revision is re-read before every command and once more after a 409, so a status change never wedges the buttons.
export async function sendCommand(id: string, command: string, f: Fetch = fetch): Promise<RunView> {
  for (let attempt = 0; ; attempt++) {
    const { revision } = await getRun(id, f);
    try {
      return await call<RunView>(f, `/v1/runs/${id}/commands`, json({ command, command_id: crypto.randomUUID(), expected_revision: revision }));
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 409) || attempt > 0) throw e;
    }
  }
}

// Replays by paging the events endpoint; the result is recorded history, never live state.
export async function loadReplayRecords(id: string, f: Fetch = fetch): Promise<Record<string, unknown>[]> {
  const records: Record<string, unknown>[] = [];
  let after = 0;
  for (;;) {
    const p = await call<{ events: ({ sequence: number; snapshot?: unknown; event?: unknown } & Record<string, unknown>)[]; latest_sequence: number }>(f, `/v1/runs/${id}/events?after_sequence=${after}&limit=500`);
    for (const e of p.events) records.push((e.snapshot ?? e.event ?? e) as Record<string, unknown>);
    if (!p.events.length || p.events[p.events.length - 1].sequence >= p.latest_sequence) return records;
    after = p.events[p.events.length - 1].sequence;
  }
}

export async function loadReplay(id: string, f: Fetch = fetch): Promise<WorldSnapshot[]> {
  return (await loadReplayRecords(id, f)).filter((r) => r.kind === "world_snapshot") as unknown as WorldSnapshot[];
}

// Health is derived only from the topology we are given: a drone with no link is reported isolated.
export function nodeHealth(s: WorldSnapshot): Record<string, "linked" | "isolated"> {
  const linked = new Set((s.topology.links as [string, string][]).flat());
  return Object.fromEntries(Object.keys(s.poses).map((id) => [id, linked.has(id) ? "linked" : "isolated"] as const));
}

export type RunSummary = Pick<RunView, "run_id" | "status" | "tick" | "completion_reason">;
export const listRuns = (f: Fetch = fetch) => call<{ runs: RunSummary[] }>(f, "/v1/runs").then((r) => r.runs);
