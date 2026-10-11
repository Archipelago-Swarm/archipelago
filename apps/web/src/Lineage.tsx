import type { Lineage } from "./live";

const COLORS = ["#08c", "#2a7", "#d33", "#c80", "#85c", "#0aa"];
const GX = 70, GY = 34, R = 10, PAD = 24;

// Capability lineage tree: columns = generation, colour = origin node, ring = policy a node currently runs.
export function LineageTree({ lineage }: { lineage: Lineage }) {
  const nodes = Object.values(lineage.dag);
  if (!nodes.length) return <p>No policy lineage reported yet.</p>;
  const origins = [...new Set(nodes.map((n) => n.origin))].sort();
  const col: Record<number, number> = {};
  const pos = Object.fromEntries(nodes.map((n) => [n.id, { x: PAD + n.gen * GX, y: PAD + (col[n.gen] = (col[n.gen] ?? -1) + 1) * GY }]));
  const W = PAD * 2 + Math.max(...nodes.map((n) => n.gen)) * GX, H = PAD * 2 + Math.max(...Object.values(col)) * GY;
  const holders = Object.entries(lineage.holders);
  const color = (o: string) => COLORS[origins.indexOf(o) % COLORS.length];
  return (
    <figure style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${W} ${H}`} width={Math.max(W, 320)} style={{ maxWidth: "100%" }} role="img" aria-label="Policy lineage tree: each circle is a policy, edges point from parent to child">
        {nodes.flatMap((n) => n.parents.filter((p) => pos[p]).map((p) => <line key={`${p}>${n.id}`} data-edge={`${p}>${n.id}`} x1={pos[p].x} y1={pos[p].y} x2={pos[n.id].x} y2={pos[n.id].y} stroke="#888" />))}
        {nodes.map((n) => {
          const held = holders.filter(([, id]) => id === n.id).map(([h]) => h);
          return (
            <g key={n.id} data-policy={n.id}>
              <circle cx={pos[n.id].x} cy={pos[n.id].y} r={R} fill={color(n.origin)} stroke={held.length ? "#000" : "none"} strokeWidth="3"><title>{`${n.id} · origin ${n.origin} · generation ${n.gen}${held.length ? ` · running on ${held.join(", ")}` : ""}`}</title></circle>
              {held.length > 0 && <text x={pos[n.id].x} y={pos[n.id].y + R + 11} fontSize="9" textAnchor="middle">{held.join(",")}</text>}
            </g>
          );
        })}
      </svg>
      <figcaption>Colour = originating node ({origins.join(", ")}) · x = generation · ringed = running now</figcaption>
    </figure>
  );
}

export function LineagePanel({ lineage }: { lineage: Lineage }) {
  const rows = Object.entries(lineage.status).sort(([a], [b]) => a.localeCompare(b));
  return (
    <section aria-label="Capability lineage">
      <h2>Capability lineage</h2>
      <LineageTree lineage={lineage} />
      <table aria-label="Capability adoption">
        <thead><tr><th>Node</th><th>Last candidate</th><th>Origin</th><th>Outcome</th></tr></thead>
        <tbody>
          {rows.length ? rows.map(([node, s]) => (
            <tr key={node} data-state={s.state}>
              <td>{node}</td><td>{s.policy}</td><td>{lineage.dag[s.policy]?.origin ?? "unknown"}</td>
              <td>{s.state === "adopted" ? "validated and adopted" : s.state === "flagged" ? `rejected, peer flagged (${s.reason})` : `rejected (${s.reason ?? "no reason"})`}</td>
            </tr>
          )) : <tr><td colSpan={4}>No capability transfers yet.</td></tr>}
        </tbody>
      </table>
      {lineage.flagged.length > 0 && <p role="status">Flagged peers: {lineage.flagged.join(", ")}</p>}
    </section>
  );
}
