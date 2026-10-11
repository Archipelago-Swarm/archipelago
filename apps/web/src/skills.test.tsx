import { renderToString } from "react-dom/server";
import { expect, it } from "vitest";
import { emptyPanels, panelsReducer } from "./live";
import { SkillList } from "./SkillList";

const metric = (sequence: number, node: string, metric: string, value: number, unit: string) => ({
  kind: "metric_sample", run_id: "r", sequence, source_node_id: node, sim_tick: sequence, metric, value, unit, phase: "eval",
});
const fold = (recs: object[]) => recs.reduce((s: ReturnType<typeof emptyPanels>, r) => panelsReducer(s, { t: "record", record: r, at: 0 }), emptyPanels());

it("folds skill metrics into proficiency, version and source, and lists them", () => {
  const p = fold([
    metric(1, "node-01", "skill.explore", 0.25, "score"),
    metric(2, "node-01", "skill_version.explore", 1, "source:node-01"),
    metric(3, "node-01", "skill.explore", 0.75, "score"),
    metric(4, "node-01", "skill_version.explore", 2, "source:node-02"),
  ]);
  expect(p.skills["node-01"].explore).toEqual({ proficiency: 0.75, version: 2, source: "node-02" });
  const html = renderToString(<SkillList skills={p.skills} />);
  expect(html).toContain('data-skill="node-01/explore"');
  expect(html).toContain("75%");
  expect(html).toContain("v2");
  expect(html).toContain("node-02");
});

it("shows an empty state and ignores non-skill metrics", () => {
  const p = fold([metric(1, "node-01", "train_loss", 0.5, "loss")]);
  expect(p.skills).toEqual({});
  expect(renderToString(<SkillList skills={p.skills} />)).toContain("No skills measured yet.");
});
