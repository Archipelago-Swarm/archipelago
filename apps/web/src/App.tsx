import { useEffect, useMemo, useReducer, useState } from "react";
import type { WorldSnapshot } from "@archipelago/contracts";
// 4-node base config matching the deployed stack (generated from infra/demo/run_demo.py build_run_config, plan "demo").
import runConfig from "./live_run_config.json";
import snapshot from "../../../packages/contracts/fixtures/good/world_snapshot.json";
import { ApiError, getRun, loadReplayRecords, login, sendCommand, startRun } from "./client";
import { emptyPanels, panelsAtFrame, panelsReducer, recordOf } from "./live";
import { commandsDisabled, connectStream, liveReducer, type Source } from "./status";
import { startDemo } from "./demo";
import { createDemoController, sceneAt } from "./demoScriptController";
import { DemoControlsOverlay } from "./DemoControlsOverlay";
import { usePlayback } from "./replay";
import { PastRuns } from "./PastRuns";
import { View } from "./View";
import { MissionApp } from "./MissionApp";

// JSON imports widen tuples; the fixture is schema-validated by the contracts tests.
const fixture = snapshot as unknown as WorldSnapshot;
const COMMANDS = ["resume", "pause", "step", "stop"] as const;

export function App() {
  const p = new URLSearchParams(location.search);
  return p.has("mission") || p.has("seed") ? <MissionApp /> : <RunApp />;
}

function RunApp() {
  const params = new URLSearchParams(location.search);
  const demo = params.has("demo"), guided = params.get("demo") === "guided";
  const ctl = useMemo(() => (guided ? createDemoController() : undefined), [guided]);
  const [ds, setDs] = useState(() => ctl?.get());
  useEffect(() => ctl?.subscribe(setDs), [ctl]);
  const runId = params.get("run") ?? (demo ? "demo-run" : null);
  const source: Source = runId ? (params.get("replay") ? "replay" : "live") : "fixture";
  const [live, dispatch] = useReducer(liveReducer, { snap: null, conn: "disconnected" });
  const [panels, pdispatch] = useReducer(panelsReducer, undefined, emptyPanels);
  const [now, setNow] = useState(() => Date.now());
  const [frames, setFrames] = useState<WorldSnapshot[]>([]);
  const [replayRecords, setReplayRecords] = useState<unknown[]>([]);
  const [frame, setFrame] = useState(0);
  const [error, setError] = useState("");
  const [needLogin, setNeedLogin] = useState(false);
  const pb = usePlayback(source === "live" ? live.snap : null);
  const present = params.get("present") === "1";
  const [details, setDetails] = useState(!present);

  // Landing example: advance the synthetic demo to a mid-run frame, then freeze it (the old fixture has no terrain/world).
  const [preview, setPreview] = useState<WorldSnapshot | null>(null);
  useEffect(() => {
    if (runId) return;
    let n = 0;
    const stop = startDemo((e) => {
      if (e.t !== "message") return;
      const r = JSON.parse(e.data);
      if (r.kind === "world_snapshot" && ++n === 150) { setPreview(r); stop(); }
    }, 1);
    return stop;
  }, [runId]);

  const fail = (e: unknown) => { if (e instanceof ApiError && e.status === 401) setNeedLogin(true); setError(e instanceof Error ? e.message : String(e)); };

  useEffect(() => {
    if (!runId || source !== "live") return;
    const onEvent = (e: Parameters<typeof dispatch>[0]) => {
      dispatch(e);
      if (e.t === "message") { try { pdispatch({ t: "record", record: recordOf(JSON.parse(e.data)), at: Date.now() }); } catch { /* unparseable frames are ignored, as in liveReducer */ } }
    };
    const stop = demo ? startDemo(onEvent, 100, ctl) : connectStream(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/v1/runs/${runId}/stream`, onEvent);
    if (!demo) getRun(runId).catch(fail);
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => { stop(); clearInterval(tick); };
  }, [runId, source, demo, ctl]);

  useEffect(() => {
    if (!runId || source !== "replay") return;
    loadReplayRecords(runId).then((records) => {
      setReplayRecords(records);
      setFrames(records.filter((r) => r.kind === "world_snapshot") as unknown as WorldSnapshot[]); setFrame(0);
    }).catch(fail);
  }, [runId, source]);

  const shownPanels = useMemo(
    () => (source === "replay" ? panelsAtFrame(replayRecords, frame) : panels),
    [source, replayRecords, frame, panels],
  );
  const snap = source === "fixture" ? preview ?? fixture : source === "replay" ? frames[frame] ?? null : pb.visible ?? live.snap;
  const conn = source === "live" ? live.conn : "connected";
  const run = (c: string) => { setError(""); sendCommand(runId!, c).catch(fail); };

  const scene = ds && sceneAt(ds.t);
  const landing = source === "fixture";
  const startForm = (
    <form className="row" onSubmit={(e) => { e.preventDefault(); setError(""); const seedText = String(new FormData(e.currentTarget).get("seed")); startRun(runConfig, seedText ? +seedText : Math.floor(Math.random() * 1e6))
        .then((r) => { location.search = `?run=${r.run_id}`; }).catch(fail); }}>
      <label>Map seed <input name="seed" type="number" min={0} max={1000000} step={1} placeholder="random" /></label> <button>Start run</button>
    </form>
  );

  return (
    <main>
      {ctl && ds && <DemoControlsOverlay ctl={ctl} state={ds} scene={scene!} lineage={shownPanels.lineage} />}
      <header>
        <h1><img src="/archipelago-logo.svg" alt="" />{landing ? "Archipelago" : <a href={location.pathname}>Archipelago</a>}</h1>
        {!landing && startForm}
      </header>
      {needLogin && (
        <form className="row" onSubmit={(e) => { e.preventDefault(); login(String(new FormData(e.currentTarget).get("token"))).then(() => { setNeedLogin(false); setError(""); }).catch(fail); }}>
          <label>API token <input name="token" type="password" /></label> <button>Sign in</button>
        </form>
      )}
      {landing && (
        <>
          <section className="hero">
            <p className="kicker">No mainland required.</p>
            <h2>Decentralized learning across UAV squadrons.</h2>
            <p><a className="button" href="?demo=1">Watch the demo</a> <a className="button" href="?demo=guided">Guided showcase</a> <a className="button" href="?mission=1">Mission simulator</a> </p>
          </section>
          <PastRuns />
          <h2>Start a run</h2>
          <p>Needs the API: <code>python3 infra/demo/run_demo.py up --plan demo</code>. Leave the map seed blank for new random maps; reuse a seed to get the same maps.</p>
          {startForm}
          <h2>Reading the map</h2>
          <dl>
            <dt>Aircraft</dt><dd>One per drone. Select one for heading, speed and policy version.</dd>
            <dt>Link</dt><dd>A radio connection between two drones. Links drop and return.</dd>
            <dt>Coverage</dt><dd>Share of free cells sensed so far.</dd>
            <dt>Policy offer</dt><dd>A drone sends its policy to a neighbour, who accepts or rejects it.</dd>
          </dl>
          <h2>Example snapshot</h2>
        </>
      )}
      <View spotlight={scene?.spotlight} playback={source === "live" ? pb : undefined} present={present} details={details && !landing} source={source} conn={conn} snap={snap} runId={runId} learning={live.learning} panels={source === "fixture" ? undefined : shownPanels} now={now} status={source === "live" ? live.status : undefined} />
      {source === "replay" && frames.length > 0 && (
        <label>Frame {frame + 1}/{frames.length} <input type="range" min={0} max={frames.length - 1} value={frame} onChange={(e) => setFrame(+e.target.value)} /></label>
      )}
      {!landing && <div className="row" role="group" aria-label="Run controls">
        {COMMANDS.map((c) => <button key={c} disabled={commandsDisabled(source, conn, live.status)} onClick={() => run(c)}>{c}</button>)}
      </div>}
      {present && <label><input type="checkbox" checked={details} onChange={(e) => setDetails(e.target.checked)} /> Details</label>}
      {error && <p role="alert">{error}</p>}
    </main>
  );
}
