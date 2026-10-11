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
import { View } from "./View";

// JSON imports widen tuples; the fixture is schema-validated by the contracts tests.
const fixture = snapshot as unknown as WorldSnapshot;
const COMMANDS = ["resume", "pause", "step", "stop"] as const;

export function App() {
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
  const snap = source === "fixture" ? fixture : source === "replay" ? frames[frame] ?? null : pb.visible ?? live.snap;
  const conn = source === "live" ? live.conn : "connected";
  const run = (c: string) => { setError(""); sendCommand(runId!, c).catch(fail); };

  const scene = ds && sceneAt(ds.t);
  const landing = source === "fixture";
  const startForm = (
    <form className="row" onSubmit={(e) => { e.preventDefault(); setError(""); startRun(runConfig, +String(new FormData(e.currentTarget).get("seed")))
        .then((r) => { location.search = `?run=${r.run_id}`; }).catch(fail); }}>
      <label>Random seed <input name="seed" type="number" min={0} step={1} defaultValue={1} required /></label> <button>Start run</button>
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
            <p className="lede">A decentralized capability-sharing layer for autonomous edge systems. Simulated platforms explore together, share what they learn over unreliable links, and hand improved flight policies from one to another.</p>
            <p><a className="button" href="?demo=1">Watch the demo</a> <a className="button" href="?demo=guided">Guided showcase</a> <span className="note">Runs in your browser. No backend needed.</span></p>
          </section>
          <h2>Getting started</h2>
          <ol>
            <li><strong>Watch the demo.</strong> A fast synthetic run. Use the timeline to pause, rewind, or jump to a policy offer.</li>
            <li><strong>Start your own run.</strong> This needs the API: <code>python3 infra/demo/run_demo.py up --plan demo</code>, then <code>npm run dev</code> in <code>apps/web</code>. The seed fixes the random numbers, so the same seed gives the same run.{startForm}</li>
            <li><strong>Replay a finished run.</strong> Open <code>?run=&lt;id&gt;&amp;replay=1</code> and drag the frame slider.</li>
          </ol>
          <h2>Reading the map</h2>
          <dl>
            <dt>Aircraft</dt><dd>One per drone. Select one to see its heading, speed and policy version.</dd>
            <dt>Link</dt><dd>A radio connection between two drones. Links drop and return.</dd>
            <dt>Coverage</dt><dd>Share of free cells the swarm has sensed so far.</dd>
            <dt>Policy offer</dt><dd>A drone sends its learned policy to a neighbour, who accepts or rejects it.</dd>
          </dl>
          <h2>Example snapshot</h2>
        </>
      )}
      <View spotlight={scene?.spotlight} playback={source === "live" ? pb : undefined} present={present} details={details} source={source} conn={conn} snap={snap} runId={runId} learning={live.learning} panels={source === "fixture" ? undefined : shownPanels} now={now} status={source === "live" ? live.status : undefined} />
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
