import { useEffect, useState } from "react";
import { listRuns, type RunSummary } from "./client";
import { TICK_S } from "./replay";

const clock = (tick: number) => { const s = Math.round(tick * TICK_S); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };

// Stored runs from the API, newest first. Renders nothing when there is no API (static demo) or the user is signed out.
export function PastRuns() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  useEffect(() => { listRuns().then(setRuns).catch(() => setRuns([])); }, []);
  if (!runs.length) return null;
  return (
    <>
      <h2>Past runs</h2>
      <table aria-label="Past runs">
        <thead><tr><th>Run</th><th>Status</th><th>Mission time</th><th>Reason</th><th /></tr></thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.run_id}>
              <td>{r.run_id}</td><td>{r.status}</td><td>{clock(r.tick)}</td><td>{r.completion_reason ?? ""}</td>
              <td><a className="button" href={`?run=${encodeURIComponent(r.run_id)}&replay=1`}>Replay</a></td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
