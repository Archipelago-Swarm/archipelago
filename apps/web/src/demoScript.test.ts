import { expect, it } from "vitest";
import { ACTS, END, createDemoController, eventsAt, sceneAt } from "./demoScriptController";
import { emptyPanels, panelsReducer } from "./live";

it("steps every tick at 5x, pauses at the end, and jumps to act starts", () => {
  const c = createDemoController();
  c.setSpeed(5);
  expect(c.step()).toEqual([1, 2, 3, 4, 5]);
  c.jump(3);
  expect(c.get().t).toBe(ACTS[3].start);
  c.jump(4);
  expect(c.get()).toMatchObject({ t: END, playing: false });
  expect(c.step()).toEqual([]);
});

it("replaying the whole script yields a 3-generation lineage and removes Alpha", () => {
  let p = emptyPanels(), seq = 0;
  for (let t = 0; t <= END; t++) for (const e of eventsAt(t)) p = panelsReducer(p, { t: "record", at: 0, record: { ...e, run_id: "r", sequence: ++seq } });
  expect(Object.keys(p.lineage.dag)).toHaveLength(3);
  expect(Object.keys(p.lineage.holders).sort()).toEqual(["node-01", "node-02", "node-03"]);
  expect(sceneAt(0).poses["node-01"]).toBeDefined();
  expect(sceneAt(END).poses["node-01"]).toBeUndefined();
  expect(sceneAt(END).poses["node-02"]).toBeDefined();
});
