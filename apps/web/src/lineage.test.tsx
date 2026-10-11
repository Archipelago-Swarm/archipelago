import { renderToString } from "react-dom/server";
import { expect, it } from "vitest";
import { emptyPanels, panelsReducer } from "./live";
import { LineagePanel } from "./Lineage";

const ev = (sequence: number, node: string, extra: object) => ({
  kind: "learning_event", run_id: "r", sequence, source_node_id: node, sim_tick: sequence, new_version: sequence, update_count: 1, loss: null,
  previous_version: 0, bytes: 10, ...extra,
});

it("builds the lineage DAG, tracks adoption and flags poisoned peers", () => {
  const recs = [
    ev(1, "b", { transfer: "accepted", policy_id: "p1", parent_ids: ["root-a", "root-b"], origin_node: "a", generation_count: 1 }),
    ev(2, "c", { transfer: "rejected", reason: "output outside safety envelope", policy_id: "bad", parent_ids: ["p1"], origin_node: "b", generation_count: 2, flagged_peer: "b" }),
  ];
  const p = recs.reduce((s, r) => panelsReducer(s, { t: "record", record: r, at: 0 }), emptyPanels());
  expect(p.lineage.holders).toEqual({ b: "p1" });
  expect(p.lineage.status.c.state).toBe("flagged");
  expect(p.lineage.flagged).toEqual(["b"]);
  const html = renderToString(<LineagePanel lineage={p.lineage} />);
  expect(html).toContain('data-edge="p1&gt;bad"');
  expect(html).toContain("validated and adopted");
  expect(html).toContain("peer flagged");
});
