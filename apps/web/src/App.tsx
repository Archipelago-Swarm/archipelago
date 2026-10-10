import { useEffect, useReducer, useState } from "react";
import type { WorldSnapshot } from "@archipelago/contracts";
import runConfig from "../../../packages/contracts/fixtures/good/run_config.json";
import snapshot from "../../../packages/contracts/fixtures/good/world_snapshot.json";
import { ApiError, getRun, loadReplay, login, sendCommand, startRun } from "./client";
import { connectStream, isTerminal, liveReducer, type Source } from "./status";
import { View } from "./View";

// JSON imports widen tuples; the fixture is schema-validated by the contracts tests.
const fixture = snapshot as unknown as WorldSnapshot;
const COMMANDS = ["resume", "pause", "step", "stop"] as const;

export function App() {
  const params = new URLSearchParams(location.search);
  const runId = params.get("run");
  const source: Source = runId ? (params.get("replay") ? "replay" : "live") : "fixture";
  const [live, dispatch] = useReducer(liveReducer, { snap: null, conn: "disconnected" });
  const [frames, setFrames] = useState<WorldSnapshot[]>([]);
  const [frame, setFrame] = useState(0);
  const [error, setError] = useState("");
  const [needLogin, setNeedLogin] = useState(false);

  const fail = (e: unknown) => { if (e instanceof ApiError && e.status === 401) setNeedLogin(true); setError(e instanceof Error ? e.message : String(e)); };

  useEffect(() => {
    if (!runId || source !== "live") return;
    const stop = connectStream(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/v1/runs/${runId}/stream`, dispatch);
    getRun(runId).catch(fail);
    return stop;
  }, [runId, source]);

  useEffect(() => {
    if (!runId || source !== "replay") return;
    loadReplay(runId).then((f) => { setFrames(f); setFrame(0); }).catch(fail);
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
      <View source={source} conn={conn} snap={snap} runId={runId} learning={live.learning} status={source === "live" ? live.status : undefined} />
      {source === "replay" && frames.length > 0 && (
        <label>Frame {frame + 1}/{frames.length} <input type="range" min={0} max={frames.length - 1} value={frame} onChange={(e) => setFrame(+e.target.value)} /></label>
      )}
      <div role="group" aria-label="Run controls">
        {COMMANDS.map((c) => <button key={c} disabled={source !== "live" || conn !== "connected" || isTerminal(live.status)} onClick={() => run(c)}>{c}</button>)}
      </div>
      {error && <p role="alert">{error}</p>}
    </main>
  );
}
