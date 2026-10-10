# T33 handoff: dashboard live panels

Status: implemented, committed on worktree branch (not pushed).

## What changed (apps/web/src)
- `live.ts`: pure `panelsReducer` over canonical records (WorldSnapshot, MetricSample, LearningEvent). Ignores duplicate/out-of-order sequences (global per-run monotonic), resets on run_id change, bounded history (`MAX_OFFERS`, `MAX_CURVE_POINTS`), per-node last-event time. `STALE_AFTER_MS` (10 s) and `panelLabel` implement LIVE / STALE / DISCONNECTED; replay/fixture/terminal never LIVE (paused runs are exempt from staleness).
- `Panels.tsx`: fault banner + links, per-node table (version, updates, loss, replay size, RSS MiB, last action, telemetry freshness/backlog/dropped), peer offers newest first, SVG train vs eval curves (axis text, units, aria label), resources row.
- `View.tsx`: canvas shows last action next to each drone; label uses `panelLabel` when panels are passed; panels hidden while disconnected; replay panels show "recorded".
- `App.tsx`/`client.ts`: stream messages also feed the panels reducer; replay uses new `loadReplayRecords` (loadReplay behavior unchanged); 1 s clock tick.
- `fixtures/partition_run.json` (connected, partition, recovery, connected; accepted and rejected offers) and `live.test.tsx`.

## Assumptions to confirm
- LearningEvent has no sender, but PeerEnvelope (kind peer_envelope) has required sender/recipient/model_version. The reducer stores envelopes; each offer takes the sender of the newest earlier envelope with recipient == deciding node and model_version == new_version, else shows "not reported". Fixture now contains peer_envelope records (sequences renumbered).
- Fault phase is read from the `phase` of `fault_phase` samples (partition / recovery / other = connected), not the numeric value.
- Last action is derived from pose deltas between snapshots (no action records are streamed).
- Sequences are assumed globally monotonic per run (live-runtime.md section 12).

## Checks run
npm ci; web: lint, typecheck, test (41 pass), build; ruff check, ruff format --check, mypy, pytest -m "not docker" --ignore=tests/e2e (215 passed, 5 pre-existing skips).
Not run: Playwright / tests/web/browser-smoke.mjs (no browser here). Smoke text expectations preserved: no uppercase LIVE or DISCONNECTED outside the status label.
