import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { WorldSnapshot } from "@archipelago/contracts";
import events from "./fixtures/partition_run.json";
import { emptyPanels, freshness, MAX_CURVE_POINTS, MAX_OFFERS, panelLabel, panelsReducer, recordOf, STALE_AFTER_MS, type Panels } from "./live";
import { View } from "./View";

const T0 = 1_000_000;
const run = (upto = events.length, start = emptyPanels()): Panels =>
  events.slice(0, upto).reduce((s, r, i) => panelsReducer(s, { t: "record", record: r, at: T0 + i * 1000 }), start);

describe("panelsReducer over the recorded partition run", () => {
  it("tracks fault phase connected -> partitioned -> recovering -> connected", () => {
    const phaseAfter = (seq: number) => run(seq).faultPhase;
    const idx = events.map((e, i) => (e.kind === "metric_sample" && (e as { metric: string }).metric === "fault_phase" ? i + 1 : 0)).filter(Boolean);
    expect(idx.map(phaseAfter)).toEqual(["connected", "partitioned", "recovering", "connected"]);
  });
  it("tracks topology links through partition and reconnect", () => {
    const snaps = events.map((e, i) => (e.kind === "world_snapshot" ? i + 1 : 0)).filter(Boolean);
    expect(snaps.map((n) => run(n).links.length)).toEqual([1, 1, 0, 1, 1]);
  });
  it("records offers newest last in state with accepted and rejected decisions", () => {
    const p = run();
    expect(p.offers.map((o) => [o.node, o.transfer, o.reason, o.score, o.bytes, o.version])).toEqual([
      ["node-01", "accepted", "score_improved", 0.8, 2048, 2],
      ["node-02", "rejected", "score_below_tolerance", -0.5, 1024, 1],
      ["node-02", "accepted", "score_improved", 1.5, 4096, 3],
    ]);
  });
  it("builds node cards from learning events and metrics", () => {
    const p = run();
    expect(p.nodes["node-02"]).toMatchObject({ policyVersion: 3, updateCount: 16, loss: 0.25, rssBytes: 115343360, lastAction: "move (+0, +1) cells" });
    expect(p.nodes["node-01"]).toMatchObject({ replaySize: 64, backlog: 7, dropped: 1, rssBytes: 104857600, lastAction: "hold" });
    expect(p.coverage).toBe(0.5);
  });
  it("separates training and frozen evaluation curves", () => {
    const p = run();
    expect(p.train.points.map((q) => q.value)).toEqual([-3, 2]);
    expect(p.eval.points.map((q) => q.value)).toEqual([1, 3]);
    expect(p.eval.unit).toBe("return");
  });
  it("ignores duplicate and out-of-order sequences", () => {
    const once = run();
    const dup = panelsReducer(once, { t: "record", record: events[3], at: T0 });
    expect(dup).toBe(once);
    const stale = { ...events[events.length - 1], sequence: 1, kind: "learning_event" };
    expect(panelsReducer(once, { t: "record", record: stale, at: T0 })).toBe(once);
    expect(panelsReducer(once, { t: "record", record: { kind: "other" }, at: T0 })).toBe(once);
  });
  it("resets when the run id changes and keeps history bounded", () => {
    const other = panelsReducer(run(), { t: "record", record: { ...events[0], run_id: "run-b", sequence: 1 }, at: T0 });
    expect(other.runId).toBe("run-b");
    expect(other.offers).toEqual([]);
    let s = emptyPanels();
    const base = events.find((e) => e.kind === "learning_event")!;
    const ret = events.find((e) => (e as { metric?: string }).metric === "episode_return")!;
    for (let i = 1; i <= MAX_OFFERS + 10; i++) s = panelsReducer(s, { t: "record", record: { ...base, sequence: i, transfer: "accepted" }, at: T0 });
    expect(s.offers).toHaveLength(MAX_OFFERS);
    expect(s.offers[0].sequence).toBe(11);
    for (let i = 1; i <= MAX_CURVE_POINTS + 5; i++) s = panelsReducer(s, { t: "record", record: { ...ret, sequence: 1000 + i }, at: T0 });
    expect(s.train.points).toHaveLength(MAX_CURVE_POINTS);
  });
  it("unwraps stream and page envelopes", () => {
    expect(recordOf({ snapshot: { a: 1 } })).toEqual({ a: 1 });
    expect(recordOf({ event: { b: 2 } })).toEqual({ b: 2 });
    expect(recordOf({ c: 3 })).toEqual({ c: 3 });
  });
});

describe("labels", () => {
  const last = T0;
  it("is LIVE only when connected and fresh", () => {
    expect(panelLabel("live", "connected", "running", last, last + STALE_AFTER_MS)).toBe("LIVE");
    expect(panelLabel("live", "connected", "running", last, last + STALE_AFTER_MS + 1)).toMatch(/^STALE/);
    expect(panelLabel("live", "connected", "running", null, last)).toMatch(/^STALE/);
    expect(panelLabel("live", "disconnected", "running", last, last)).toMatch(/^DISCONNECTED/);
    expect(panelLabel("live", "connected", "completed", last, last)).toBe("COMPLETED (not live)");
    expect(panelLabel("replay", "connected", undefined, last, last)).toBe("REPLAY");
    expect(panelLabel("fixture", "connected", undefined, last, last)).not.toContain("LIVE");
    expect(freshness(last, last + 1)).toBe("fresh");
  });
});

describe("rendered panels", () => {
  const snap = events[0] as unknown as WorldSnapshot;
  const render = (p: Panels, now: number, conn: "connected" | "disconnected" = "connected", source: "live" | "replay" = "live") =>
    renderToString(<View source={source} conn={conn} snap={snap} panels={p} now={now} status="running" />).replaceAll("<!-- -->", "");
  const p = run();
  const lastAt = T0 + (events.length - 1) * 1000;

  it("renders LIVE with node cards, offers newest first, curves and resources", () => {
    const html = render(p, lastAt + 1000);
    expect(html).toContain("LIVE");
    expect(html).toContain("connected");
    expect(html).toContain("Policy version");
    expect(html).toContain("110.0"); // node-02 rss 115343360 B in MiB
    expect(html).toContain("fresh (2 s ago)");
    const rows = html.split("<tr>").filter((r) => r.includes("sender not reported"));
    expect(rows).toHaveLength(3);
    for (const t of ["node-02", "accepted", "4096"]) expect(rows[0]).toContain(t);
    for (const t of ["rejected", "score_below_tolerance", "-0.50"]) expect(rows[1]).toContain(t);
    expect(html).toContain('data-series="train"');
    expect(html).toContain('data-series="eval"');
    expect(html).toContain("sim tick");
    expect(html).toContain("Total RSS: 210.0 MiB");
    expect(html).toContain("telemetry dropped: 1 events");
  });
  it("shows the partition banner at the partition point", () => {
    const part = run(events.findIndex((e) => (e as { phase?: string }).phase === "partition") + 2);
    const html = render(part, lastAt);
    expect(html).toContain('data-phase="partitioned"');
    expect(html).toContain("links: none");
  });
  it("labels stale and disconnected, and never LIVE for them or replay", () => {
    const stale = render(p, lastAt + STALE_AFTER_MS + 5000);
    expect(stale).toContain("STALE");
    expect(stale).not.toContain("LIVE");
    expect(stale).toContain("stale (");
    const gone = render(p, lastAt, "disconnected");
    expect(gone).toContain("DISCONNECTED");
    expect(gone).not.toContain("LIVE");
    expect(gone).not.toContain("Policy version");
    const replay = render(p, lastAt, "connected", "replay");
    expect(replay).toContain("REPLAY");
    expect(replay).not.toContain("LIVE");
    expect(replay).toContain("recorded");
  });
  it("shows empty placeholders without inventing metrics", () => {
    const html = render(emptyPanels(), T0);
    expect(html).toContain("No node data received yet");
    expect(html).toContain("No offers recorded");
    expect(html).toContain("not reported");
    expect(html).toContain("STALE");
  });
});
