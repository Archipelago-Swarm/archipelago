import { useRef, useState } from "react";
import { MissionViewer } from "./MissionViewer";
import { SERVER_CMD, aggregate, fetchSummary, hms, pct, type MapSummary } from "./missionReplay";

/** n distinct seeds: consecutive from `base` when given, else random (the list is shown so any map can be replayed). */
export function pickSeeds(n: number, base?: number): number[] {
  if (base !== undefined) return Array.from({ length: n }, (_, i) => base + i);
  const s = new Set<number>();
  while (s.size < n) s.add(Math.floor(Math.random() * 1_000_000));
  return [...s];
}

const num = (x: number | null, d = 2) => (x == null ? "-" : x.toFixed(d));
const Row = ({ k, a, b }: { k: string; a: string; b: string }) => <tr><th>{k}</th><td>{a}</td><td>{b}</td></tr>;

function Results({ rows, onWatch }: { rows: MapSummary[]; onWatch(r: MapSummary): void }) {
  const g = aggregate(rows), maxT = Math.max(1, ...rows.flatMap((r) => [r.on.mission.elapsedTime, r.off.mission.elapsedTime]));
  const t = (x: number | null) => (x == null ? "-" : hms(x));
  return (
    <section aria-label="Results">
      <h2>Results across {rows.length} maps</h2>
      <p className="lede">Skills on beat skills off on <b>{g.skillsWin}</b> maps, lost on <b>{g.skillsLose}</b>, tied on {g.ties}. Success rate {pct(g.on.successRate)} with skills vs {pct(g.off.successRate)} without.</p>
      <table aria-label="Aggregate">
        <thead><tr><th>Metric (mean over maps)</th><th>Skills on</th><th>Skills off</th></tr></thead>
        <tbody>
          <Row k="Missions succeeded" a={`${g.on.successes} / ${g.on.n}`} b={`${g.off.successes} / ${g.off.n}`} />
          <Row k="Mean time to success" a={t(g.on.meanTime)} b={t(g.off.meanTime)} />
          <Row k="POIs verified" a={pct(g.on.meanVerified ?? 0)} b={pct(g.off.meanVerified ?? 0)} />
          <Row k="Fleet knowledge coverage" a={pct(g.on.meanCoverage ?? 0)} b={pct(g.off.meanCoverage ?? 0)} />
          <Row k="Redundancy ratio (lower is better)" a={num(g.on.meanRedundancy, 3)} b={num(g.off.meanRedundancy, 3)} />
          <Row k="Network partitions" a={num(g.on.meanPartitions, 1)} b={num(g.off.meanPartitions, 1)} />
          <Row k="Skill transfers" a={num(g.on.meanTransfers, 1)} b={num(g.off.meanTransfers, 1)} />
        </tbody>
      </table>
      <h2>Per map</h2>
      <table aria-label="Per map">
        <thead><tr><th>Map seed</th><th>Skills on</th><th>Skills off</th><th>Mission time</th><th>Redundancy on / off</th><th /></tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={r.seed}>
            <td>{r.seed}</td>
            <td className={r.on.mission.status}>{r.on.mission.status} {r.on.mission.verifiedPois}/{r.on.mission.totalPois}</td>
            <td className={r.off.mission.status}>{r.off.mission.status} {r.off.mission.verifiedPois}/{r.off.mission.totalPois}</td>
            <td>
              <div className="m-bars"><div><i className="on" style={{ width: pct(r.on.mission.elapsedTime / maxT) }} />{hms(r.on.mission.elapsedTime)}</div>
                <div><i className="off" style={{ width: pct(r.off.mission.elapsedTime / maxT) }} />{hms(r.off.mission.elapsedTime)}</div></div>
            </td>
            <td>{r.on.stats.redundancyRatio.toFixed(3)} / {r.off.stats.redundancyRatio.toFixed(3)}</td>
            <td><button onClick={() => onWatch(r)}>Watch</button></td>
          </tr>))}
        </tbody>
      </table>
    </section>
  );
}

export function MissionApp() {
  const q = new URLSearchParams(location.search);
  const [watch, setWatch] = useState<{ seed: number; uavs: number; compare?: MapSummary } | null>(q.has("seed") ? { seed: +q.get("seed")!, uavs: +(q.get("uavs") ?? 6) } : null);
  const [rows, setRows] = useState<MapSummary[]>([]), [total, setTotal] = useState(0), [running, setRunning] = useState(false), [error, setError] = useState("");
  const abort = useRef<AbortController | null>(null);

  const start = async (f: FormData) => {
    const uavs = +String(f.get("uavs")), maps = +String(f.get("maps")), base = String(f.get("seed")).trim();
    const seeds = pickSeeds(maps, base ? +base : undefined), ac = new AbortController();
    abort.current = ac; setRows([]); setTotal(maps); setError(""); setRunning(true);
    try {
      for (const s of seeds) {
        const r = await fetchSummary(s, uavs, ac.signal);
        setRows((x) => [...x, r]);
      }
    } catch (e) {
      if (!ac.signal.aborted) setError(e instanceof TypeError ? `Mission server not reachable. Start it from the repo root: ${SERVER_CMD}` : String(e instanceof Error ? e.message : e));
    }
    setRunning(false);
  };

  if (watch) return <main className="m-main"><MissionViewer {...watch} onBack={() => setWatch(null)} /></main>;
  return (
    <main className="m-main">
      <header><h1><img src="/archipelago-logo.svg" alt="" />Mission simulator</h1></header>
      <p className="lede">Generate random 400 x 500 km maps, fly the POI mission with your fleet, and compare the swarm with and without skill sharing.</p>
      <form className="m-form" onSubmit={(e) => { e.preventDefault(); void start(new FormData(e.currentTarget)); }}>
        <label>Drones <input name="uavs" type="number" min={1} max={24} defaultValue={6} required /></label>
        <label>Test maps <input name="maps" type="number" min={1} max={20} defaultValue={5} required /></label>
        <label>Base seed <input name="seed" type="number" min={0} step={1} placeholder="random" /></label>
        <button disabled={running}>{running ? "Running…" : "Run simulation"}</button>
        {running && <button type="button" onClick={() => abort.current?.abort()}>Stop</button>}
      </form>
      <p className="note">Each map is generated from its own seed (POI sites, UAV starts, disruptions). Every map flies twice: skills on, skills off.</p>
      {running && <p role="status"><progress max={total} value={rows.length} /> {rows.length} / {total} maps simulated</p>}
      {error && <p role="alert">{error}</p>}
      {rows.length > 0 && <Results rows={rows} onWatch={(r) => setWatch({ seed: r.seed, uavs: r.uavs, compare: r })} />}
    </main>
  );
}
