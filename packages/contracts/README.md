# packages/contracts

Canonical v0 shared records. **Source of truth:** `src/archipelago_contracts/models.py` (Pydantic v2).

Pipeline: models -> `schemas/*.schema.json` (`python -m archipelago_contracts.export`) -> `generated/types.ts`
(`npm run gen:types`). Never hand-edit `schemas/` or `generated/`; CI fails on drift.

`fixtures/good` and `fixtures/bad` are consumed by both pytest (`tests/contracts`) and Vitest
(`test/fixtures.test.ts`). To add a record or field: edit models, regenerate, add good and bad fixtures.
Breaking changes need an ADR and same-sequence fixture updates (see agents/architecture/interfaces.md).

Checks that live outside JSON Schema: `SequenceTracker` (stale/duplicate sequence), tested in pytest only.
`adapter.py` defines the `SimulatorAdapter` protocol and a replay-only `FixtureAdapter`; it is not the simulator.
