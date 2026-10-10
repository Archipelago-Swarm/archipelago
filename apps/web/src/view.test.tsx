import { renderToString } from "react-dom/server";
import { expect, it } from "vitest";
import type { WorldSnapshot } from "@archipelago/contracts";
import snapshot from "../../../packages/contracts/fixtures/good/world_snapshot.json";
import { liveReducer, type Live } from "./status";
import { View } from "./View";

const snap = snapshot as unknown as WorldSnapshot;
const msg = (s: WorldSnapshot) => ({ t: "message", data: JSON.stringify({ snapshot: s }) }) as const;

it("clears state on disconnect and re-syncs on reconnect", () => {
  let s: Live = { snap: null, conn: "disconnected" };
  s = liveReducer(liveReducer(s, { t: "open" }), msg(snap));
  expect(s.snap?.run_id).toBe(snap.run_id);
  s = liveReducer(s, { t: "close" });
  expect(s).toEqual({ snap: null, conn: "disconnected" });
  expect(renderToString(<View source="live" conn={s.conn} snap={s.snap} />)).not.toContain(snap.run_id);
  s = liveReducer(liveReducer(s, { t: "open" }), msg(snap));
  expect(s.snap).toEqual(snap);
  expect(liveReducer(s, { t: "message", data: "not json" })).toBe(s);
});

it("shows label, run id and units", () => {
  const html = renderToString(<View source="live" conn="connected" snap={snap} />);
  expect(html).toContain("LIVE");
  expect(html).toContain(snap.run_id);
  expect(html).toContain("% of free cells");
  expect(html).toContain("cells");
  expect(html).toContain("not reported");
});
