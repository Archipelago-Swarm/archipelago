import { searchBoost, type Panels } from "./live";
import { TICK_S } from "./replay";

const clock = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

// Search & rescue scoreboard; renders nothing until the run reports a target count.
export function MissionHUD({ p }: { p: Panels }) {
  const m = p.mission;
  if (m.total === null) return null;
  const found = m.finds.length;
  const boost = p.tick === null ? null : searchBoost(m, p.tick);
  const pill = m.adoptTick === null ? "P2P Capability Sync: waiting for first shared policy"
    : boost === null ? "P2P Capability Sync: measuring search speed"
    : `P2P Capability Sync: ${boost >= 0 ? "+" : ""}${boost}% Search Speed Boost`;
  return (
    <section aria-label="Mission scoreboard">
      <h2>Mission: search &amp; rescue</h2>
      <progress aria-label="Targets found" max={m.total || 1} value={found} />{" "}
      <strong>{`${found} / ${m.total} Targets Found`}</strong>
      <p>
        Mission time: {p.tick === null ? "not reported" : clock(p.tick * TICK_S)} · coverage: {p.coverage === null ? "not reported" : `${(p.coverage * 100).toFixed(1)}%`}
        {found > 0 && m.total > 0 && found === m.total ? " · complete" : ""} <span data-testid="boost" className="pill">{pill}</span>
      </p>
    </section>
  );
}
