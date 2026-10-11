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
