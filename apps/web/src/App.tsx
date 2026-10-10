import { useEffect, useReducer, useState } from "react";
import type { WorldSnapshot } from "@archipelago/contracts";
import runConfig from "../../../packages/contracts/fixtures/good/run_config.json";
import snapshot from "../../../packages/contracts/fixtures/good/world_snapshot.json";
import { ApiError, getRun, loadReplayRecords, login, sendCommand, startRun } from "./client";
import { emptyPanels, panelsReducer, recordOf } from "./live";
import { commandsDisabled, connectStream, liveReducer, type Source } from "./status";
import { View } from "./View";

// JSON imports widen tuples; the fixture is schema-validated by the contracts tests.
const fixture = snapshot as unknown as WorldSnapshot;
const COMMANDS = ["resume", "pause", "step", "stop"] as const;

export function App() {
  const params = new URLSearchParams(location.search);
  const runId = params.get("run");
  const source: Source = runId ? (params.get("replay") ? "replay" : "live") : "fixture";
  const [live, dispatch] = useReducer(liveReducer, { snap: null, conn: "disconnected" });
  const [panels, pdispatch] = useReducer(panelsReducer, undefined, emptyPanels);
  const [now, setNow] = useState(() => Date.now());
  const [frames, setFrames] = useState<WorldSnapshot[]>([]);
  const [frame, setFrame] = useState(0);
  const [error, setError] = useState("");
  const [needLogin, setNeedLogin] = useState(false);

  const fail = (e: unknown) => { if (e instanceof ApiError && e.status === 401) setNeedLogin(true); setError(e instanceof Error ? e.message : String(e)); };

  useEffect(() => {
    if (!runId || source !== "live") return;
    const stop = connectStream(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/v1/runs/${runId}/stream`, (e) => {
      dispatch(e);
      if (e.t === "message") { try { pdispatch({ t: "record", record: recordOf(JSON.parse(e.data)), at: Date.now() }); } catch { /* unparseable frames are ignored, as in liveReducer */ } }
    });
    getRun(runId).catch(fail);
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => { stop(); clearInterval(tick); };
  }, [runId, source]);

  useEffect(() => {
    if (!runId || source !== "replay") return;
    loadReplayRecords(runId).then((records) => {
      pdispatch({ t: "reset" });
      for (const r of records) pdispatch({ t: "record", record: r, at: 0 });
      setFrames(records.filter((r) => r.kind === "world_snapshot") as unknown as WorldSnapshot[]); setFrame(0);
    }).catch(fail);
  }, [runId, source]);

  const snap = source === "fixture" ? fixture : source === "replay" ? frames[frame] ?? null : live.snap;
  const conn = source === "live" ? live.conn : "connected";
  const run = (c: string) => { setError(""); sendCommand(runId!, c).catch(fail); };

  return (
    <main>
      <h1>Archipelago</h1>
      {needLogin && (
        <form onSubmit={(e) => { e.preventDefault(); login(String(new FormData(e.currentTarget).get("token"))).then(() => { setNeedLogin(false); setError(""); }).catch(fail); }}>
          <label>API token <input name="token" type="password" /></label> <button>Sign in</button>
        </form>
      )}
      <form onSubmit={(e) => { e.preventDefault(); setError(""); startRun(runConfig, +String(new FormData(e.currentTarget).get("seed")))
          .then((r) => { location.search = `?run=${r.run_id}`; }).catch(fail); }}>
        <label>Seed <input name="seed" type="number" min={0} step={1} defaultValue={1} required /></label> <button>Start run</button>
      </form>
      <View source={source} conn={conn} snap={snap} runId={runId} learning={live.learning} panels={source === "fixture" ? undefined : panels} now={now} status={source === "live" ? live.status : undefined} />
      {source === "replay" && frames.length > 0 && (
        <label>Frame {frame + 1}/{frames.length} <input type="range" min={0} max={frames.length - 1} value={frame} onChange={(e) => setFrame(+e.target.value)} /></label>
      )}
      <div role="group" aria-label="Run controls">
        {COMMANDS.map((c) => <button key={c} disabled={commandsDisabled(source, conn, live.status)} onClick={() => run(c)}>{c}</button>)}
      </div>
      {error && <p role="alert">{error}</p>}
    </main>
  );
}
