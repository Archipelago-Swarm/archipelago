import type { WorldSnapshot } from "@archipelago/contracts";
import snapshot from "../../../packages/contracts/fixtures/good/world_snapshot.json";

// Scaffold only: renders one contract fixture to prove the shared types compile.
// This is NOT the dashboard (T06) and shows no live or simulated data.
// JSON imports widen tuples; the fixture is schema-validated by the contracts tests.
const record = snapshot as unknown as WorldSnapshot;

export function App() {
  return (
    <main>
      <h1>Archipelago (scaffold)</h1>
      <p>Fixture record kind: {record.kind}</p>
    </main>
  );
}
