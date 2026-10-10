# Handoff: T32 (experiment protocol repair and offline five-mode harness)

- State: implementation complete, ready for review. Branch: worker worktree branch (not pushed).
- Acceptance: `uv run pytest tests/experiments -q` passes (25 tests, ~30 s); ruff, ruff format, mypy and
  `pytest -m "not docker" --ignore=tests/e2e` (227 passed, 5 pre-existing skips elsewhere) pass.

## What changed (experiments/**, tests/experiments/** only)

- `protocol_harness.py` (renamed from harness.py: it collided with tests/coordinator/harness.py): protocol v1 (config/reward/scenario hashes, seed splits, frozen scenarios, `InfoBus`,
  telemetry spool, episode loop). `run.py`: `Cell` + CLI (`--mode`, `--backend numpy`, `--obs`, per-seed
  CSV, manifest with commit/seeds/hashes/commands). `report.py`: REPORT.md generated from artifacts.
- Defects fixed with tests: (a) per-cell `train_env_steps` (fresh `Budget` per cell); (b) node_failure counts
  surviving-agent transitions (kill is tick-based, node leaves the world); (c) central_online budgets recorded
  (transitions exclude control-link cuts; blocked agent-steps reported); transitions, optimizer updates,
  update samples reported for every mode; (d) `info_only`/`p2p` share one deterministic map/status message
  (`InfoBus`); replay sharing kept only as secondary `replay_sharing`; (e) per-decision validation cost
  (evaluations, eval ticks, bytes; wall seconds in `timing.jsonl`).
- Config fix: the T09 world (8x8, 2 targets, 60 ticks) ended in ~7 ticks so faults never fired. Now 16x16,
  8 targets, 150 ticks; faults at ticks 10-25 / 20; tests assert every fault tick is reached by idle and rule
  episodes and battery outlasts the horizon.
- Prior results moved to `experiments/history/` with banners. Note: `experiments/out/` at HEAD was already
  inconsistent with its own manifest (documented); the verifiable T09 bundle in `agents/handoffs/T09/evidence`
  is untouched and still hash-checked.
- Diagnosis: `experiments/diagnosis/idle_vs_learners.md` (+ `pilot.py`, `summarize.py`, `pilot_results.json`;
  dev seeds only, ~42 s).
- Generated sample: `experiments/out/` (3 seeds x 20 episodes, all 8 modes x 4 scenarios, 188 s wall, PRELIMINARY; manifest records worktree_dirty=true because it was generated before the commit) and `REPORT.md`.

## Key findings to act on

1. Under `grid-flat-v0` the 5x5 crop equals the sensing radius, so shared map cells can never appear in an
   observation: `info_only` is byte-identical to `independent` (asserted by a test). Making map sharing matter
   needs a versioned observation; `grid-flat-v1-map` is implemented as opt-in only (`--obs`), not default.
2. Learners lack visit memory, loop and bump walls (collision -0.5 is below TD noise); proposals are in the
   diagnosis, none applied.

## Not run / limits

- No torch backend (only `numpy` registered; extension point `run.BACKENDS`). Sweep is 3 seeds: preliminary.
- `central_online` and `ctde` are labeled secondary approximations. central_online's cut path (node<->controller
  uses the peer cut window) is an assumption.
- p2p model swaps happen at episode boundaries; partition is applied to them by training-episode fraction
  (middle third), in-episode ticks cut the info channel. Documented in `experiments/README.md`.

## Shared changes requested from others

- T26/T30 (packages/learning): reward scaling/Huber loss, epsilon schedule, larger replay, per diagnosis table.
- Optional: `.github`/Makefile may add `PYTHONPATH` for `python experiments/run.py` (tests use conftest paths).
