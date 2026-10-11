# T37 handoff: learnable variants and an honest comparison

State: REVIEW-ready on local branch `t37-variant-study` (not pushed, not merged; the integrator merges).

## What exists
- Sim (`packages/sim/archipelago_sim/env.py`): reward `rew-v1` (new cell 0.5, collision -2.0, revisit -0.25,
  targets sensed at reset earn nothing), per-node `visits` / `peer_visits`, `observe_memory()`, episode `counters`,
  `targets_after_spawn`, `coverage_gain`. `rew-v0` and the default are bit-identical to origin/main (golden hashes in tests).
- Harness (`experiments/protocol_harness.py`): obs ids `grid-flat-v2-visits` (57 floats) and
  `grid-flat-v2-visits-shared` (82), `make_env(obs, reward)`, `InfoBus(share_visits)`; v0 and v1-map unchanged.
- Study: `experiments/t37.py`, `experiments/t37_report.py`; pre-registration `experiments/prereg/T37.yaml`
  (commit 77074bb; amendment 1: stage B 500 -> 400 episodes, found by the seed-overlap guard before any result was read).
- Evidence: `experiments/out/T37/` (`summary.md`, `results.json`, `stageA.json`, `stageB.json`, `selection.json`,
  `test.json`, `curves.csv`, `curves.svg`, `models/*.npz`, `TEST_DONE`).
- Tests: `tests/simvariants/test_variants.py`; existing `tests/experiments` still pass.

## Result (details and CIs in summary.md)
Selected using only training seeds, VAL 100-104 and held-out worlds 5000-5019:
`grid-flat-v2-visits-shared | rew-v1 | eps 1.0->0.05 over 50% | lr 1e-3 | replay 50000 | double DQN`.
One-shot TEST 200-219, 10 seeds: reference return 34.9 vs idle -39.0 (+73.9, CI [+65.1, +81.0]), vs random +64.4,
vs untrained +215; coverage gain 0.72 vs idle 0.00; targets after spawn 6.19 vs 0.00.
Pre-registered "learning helps": TRUE. Versus the rule explorer: return -15.8 (CI [-24.7, -8.6], worse), coverage gain
+0.001 (CI [-0.04, +0.05]), targets -0.26 (CI [-0.56, +0.03]); "beats rule": FALSE.
The v0 learner (control) is far worse than idle on the reference return (-91 on selection worlds, 73 wall hits).

## Commands
`rm -rf experiments/out/T37; PYTHONPATH=packages/learning:packages/sim:experiments uv run python experiments/t37.py all`
(compute is roughly 12 minutes on 4 cores here). Stages are separable: `stageA | stageB | select | test | report`.
`test` refuses to run twice (TEST_DONE marker).
Validate: `uv run pytest tests/experiments tests/simvariants -q`, `uv run ruff check/format`, `uv run mypy`.

## Limits and what was not run
- Only scenario `connected`; no faults, no p2p model transfer, no Torch runtime, no `make check-fast/integration`.
- 2 drones, 16x16, 150 ticks, hidden 32; 11 registered stage-A cells, 4 seeds there (noisy cut).
- The shared id bundles peer stood-on flags with a peer-merged map frontier; not ablated separately.
- Before registering I ran a 10-episode smoke and the idle/rule/random baselines on the selection worlds; no config
  comparison was inspected, but those baseline numbers were visible to me.
- The learner may still be improving at 400 episodes (curves.csv).

## For T38
Spec in summary.md "Adoption note": 82-float layout, rew-v1 constants, hyperparameters. A new encoder id and sha256
(A6) are needed; `archipelago_learning.encoders` only knows the 28-value v1 geometry. `VLearner` in `t37.py` is the
NumPy reference for double DQN.
