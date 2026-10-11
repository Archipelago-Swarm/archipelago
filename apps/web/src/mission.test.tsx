import { renderToString } from "react-dom/server";
import { expect, it } from "vitest";
import { emptyPanels, panelsReducer, searchBoost } from "./live";
import { MissionHUD } from "./MissionHUD";

const metric = (sequence: number, metric: string, value: number, tick: number, node?: string) => ({
  kind: "metric_sample", run_id: "r", sequence, metric, value, unit: "count", phase: "train", sim_tick: tick, source_node_id: node,
});
const adopt = { kind: "learning_event", run_id: "r", sequence: 5, source_node_id: "b", sim_tick: 100, new_version: 1, update_count: 1, loss: null, previous_version: 0, bytes: 1, transfer: "accepted", policy_id: "p1", parent_ids: [] };

it("tracks finds and reports the search speed boost after the first adoption", () => {
  const recs = [
    metric(1, "targets_total", 4, 10), metric(2, "target_found", 1, 50, "a"), adopt,
    metric(6, "target_found", 2, 120, "b"), metric(7, "target_found", 3, 140, "a"), metric(8, "target_found", 4, 160, "b"),
  ];
  const p = recs.reduce((s, r) => panelsReducer(s, { t: "record", record: r, at: 0 }), emptyPanels());
  expect(p.mission.adoptTick).toBe(100);
  // before: 1 find / 100 ticks; after: 3 finds / 100 ticks (tick 200) => +200%
  expect(searchBoost(p.mission, 200)).toBe(200);
  expect(searchBoost({ ...p.mission, adoptTick: null }, 200)).toBeNull();
  const html = renderToString(<MissionHUD p={{ ...p, tick: 200, coverage: 0.5 }} />);
  expect(html).toContain("4 / 4 Targets Found");
  expect(html).toContain("+200% Search Speed Boost");
});

const text = (h: string) => h.replace(/<!-- -->/g, "");
const mission = (status: string, completed: number | null, found: number) => ({
  id: "sr-demo", type: "search_rescue", map_seed: 123456789, status, time_budget_ticks: 120, energy_budget: null, energy_spent: 0.25,
  completed_tick: completed, dynamics: ["targets_move", "obstacles_shift"],
  objectives: [{ id: "find_targets", kind: "find_targets", target: 4, progress: found / 4, done: found === 4 }],
});
const snap = (sequence: number, m: unknown) => ({
  kind: "world_snapshot", run_id: "r", sequence, sim_tick: sequence * 10, run_status: "running", poses: {}, obstacles: [], coverage: 0.4,
  topology: { links: [] }, mission: m,
});

it("shows the active mission, its objectives, dynamics and map seed from the newest snapshot", () => {
  const recs = [snap(1, mission("active", null, 1)), snap(2, mission("active", null, 3))];
  const p = recs.reduce((s, r) => panelsReducer(s, { t: "record", record: r, at: 0 }), emptyPanels());
  expect(p.missionStatus?.objectives[0].progress).toBe(0.75);
  const html = text(renderToString(<MissionHUD p={p} />));
  expect(html).toContain("Mission: search &amp; rescue");
  expect(html).toContain("sr-demo");
  expect(html).toContain("123456789");
  expect(html).toContain("targets move, obstacles shift");
  expect(html).toContain("Find targets (4): 75%");
  expect(html).toContain("0 / 1 objectives complete");
});

it("reports mission success with the time to complete", () => {
  const p = panelsReducer(emptyPanels(), { t: "record", record: snap(1, mission("succeeded", 90, 4)), at: 0 });
  const html = text(renderToString(<MissionHUD p={p} />));
  expect(html).toContain("succeeded");
  expect(html).toContain("completed in 11:15"); // 90 ticks * 7.5 s
  expect(html).toContain("1 / 1 objectives complete");
});

it("renders nothing without a mission or a target count", () => {
  expect(renderToString(<MissionHUD p={emptyPanels()} />)).toBe("");
});
