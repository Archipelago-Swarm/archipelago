import { searchBoost, type Panels } from "./live";
import { TICK_S } from "./replay";

const clock = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const LABEL: Record<string, string> = { search_rescue: "search & rescue", coverage: "area coverage" };
const OBJECTIVE: Record<string, string> = { find_targets: "Find targets", cover_fraction: "Cover area" };
const DYNAMICS: Record<string, string> = { targets_move: "targets move", targets_appear: "targets appear", obstacles_shift: "obstacles shift" };

// Active mission (type, objectives, success/time budget, map seed) plus the search & rescue scoreboard;
// renders nothing until the run reports a mission or a target count.
export function MissionHUD({ p }: { p: Panels }) {
  const m = p.mission, ms = p.missionStatus;
  if (m.total === null && !ms) return null;
  const found = m.finds.length;
  const boost = p.tick === null ? null : searchBoost(m, p.tick);
  const pill = m.adoptTick === null ? "P2P Capability Sync: waiting for first shared policy"
    : boost === null ? "P2P Capability Sync: measuring search speed"
    : `P2P Capability Sync: ${boost >= 0 ? "+" : ""}${boost}% Search Speed Boost`;
  const done = ms ? ms.objectives.filter((o) => o.done).length : 0;
  return (
    <section aria-label="Mission scoreboard">
      <h2>Mission: {ms ? (LABEL[ms.type] ?? ms.type) : "search & rescue"}</h2>
      {ms && (
        <div aria-label="Active mission" data-status={ms.status}>
          <p>
            <strong>{ms.id}</strong> · <span data-testid="mission-status">{ms.status}</span> · map seed <span data-testid="map-seed">{ms.map_seed}</span>
            {ms.status === "succeeded" && ms.completed_tick != null ? ` · completed in ${clock(ms.completed_tick * TICK_S)}` : ` · time budget ${clock(ms.time_budget_ticks * TICK_S)}`}
            {ms.energy_budget != null ? ` · energy ${((ms.energy_spent ?? 0) * 100).toFixed(0)}% of ${(ms.energy_budget * 100).toFixed(0)}% budget` : ""}
            {ms.dynamics && ms.dynamics.length > 0 ? ` · dynamic: ${ms.dynamics.map((d) => DYNAMICS[d] ?? d).join(", ")}` : ""}
          </p>
          <ul aria-label="Mission objectives">
            {ms.objectives.map((o) => (
              <li key={o.id} data-done={o.done}>
                {o.done ? "[done] " : "[open] "}{OBJECTIVE[o.kind] ?? o.kind} ({o.kind === "cover_fraction" ? `${(o.target * 100).toFixed(0)}%` : o.target}): {(o.progress * 100).toFixed(0)}%
              </li>
            ))}
          </ul>
          <p>{done} / {ms.objectives.length} objectives complete</p>
        </div>
      )}
      {m.total !== null && (
        <>
          <progress aria-label="Targets found" max={m.total || 1} value={found} />{" "}
          <strong>{`${found} / ${m.total} Targets Found`}</strong>
        </>
      )}
      <p>
        Mission time: {p.tick === null ? "not reported" : clock(p.tick * TICK_S)} · coverage: {p.coverage === null ? "not reported" : `${(p.coverage * 100).toFixed(1)}%`}
        {found > 0 && m.total !== null && m.total > 0 && found === m.total ? " · complete" : ""} <span data-testid="boost" className="pill">{pill}</span>
      </p>
    </section>
  );
}
