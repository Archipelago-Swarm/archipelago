import type { Skills } from "./live";

// What each node has learned: measured proficiency per skill, its version, and the node it was learned from.
export function SkillList({ skills }: { skills: Skills }) {
  const rows = Object.entries(skills).sort(([a], [b]) => a.localeCompare(b)).flatMap(([node, byName]) =>
    Object.entries(byName).sort(([a], [b]) => a.localeCompare(b)).map(([name, s]) => ({ node, name, ...s })));
  return (
    <section aria-label="Skills">
      <h2>Skills learned</h2>
      {rows.length ? (
        <table aria-label="Node skills">
          <thead><tr><th>Node</th><th>Skill</th><th>Proficiency</th><th>Version</th><th>Learned from</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.node}/${r.name}`} data-skill={`${r.node}/${r.name}`}>
                <td>{r.node}</td><td>{r.name}</td>
                <td><progress aria-label={`${r.name} proficiency`} max={1} value={r.proficiency} /> {`${(r.proficiency * 100).toFixed(0)}%`}</td>
                <td>{`v${r.version}`}</td><td>{r.source === null ? "not reported" : r.source === r.node ? "own training" : r.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p>No skills measured yet.</p>}
    </section>
  );
}
