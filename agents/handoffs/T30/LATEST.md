# Handoff: T30 / live pilot and evidence

- State: review (NOT pushed, NOT merged; local branch `t30-live-pilot` on `origin/main` e844355). Ledger/controller not touched (no push allowed in this assignment).
- Owned paths used: `experiments/**`, `tests/experiments/**`, `agents/handoffs/T30/**`. No product code changed.
- Torch: `uv sync --frozen --group torch` worked (torch 2.14.1+cu130, CPU used on every node).

## Reproduce
`uv run python experiments/t30_live.py all` (about 18 min wall here: two arms in parallel, 150 training + 9 validation + 20 test episodes each). Supplement: `uv run python experiments/t30_live.py arm fleet --supplement` (3 min). `... analyze` rebuilds the report from `experiments/out/T30/raw`. Tests: `uv run pytest tests/experiments/test_t30.py`.

Pre-registration `experiments/prereg/T30.yaml` (commit e08654f; amendments 1-2 in 4046ac0 / d41d7d0, both after a smoke run and before the registered run). Results: `experiments/out/T30/summary.md` (evidence table with file:line pointers), `results.json`, `curves.csv`, `decisions.jsonl`, `spool_excerpt.jsonl`, `raw/`, `supplement/`.

## Results (frozen test seeds 200-219, paired bootstrap over worlds, ONE training run per arm)
- fleet - idle: ref return +56.8 [+38.9, +66.6]; coverage +0.72, targets +6.9 (all CIs > 0). Learning helps vs idle.
- fleet - rule: ref return -11.0 [-28.8, -1.1]. Does NOT beat the rule explorer (worse on return and coverage; targets inconclusive).
- fleet - isolated: ref return +42.7 [+14.9, +74.8]; targets +0.45 [+0.2, +0.7]; coverage -0.05 (worse). Caution: validation-seed curves end level (24.3 vs 23.8), the isolated test return is -24.9 with many wall collisions, and there is a single training run each, so this is not evidence that exchange helps in general.
- isolated - idle: inconclusive on return.
- Claim A supported. B supported (registered run: all checks pass except positive control (v'), whose trace is nearly empty, see below; supplement: all pass). C supported only in the supplement (the registered kill never fired).

## Defects and deviations (all reported in summary.md)
1. The registered SIGKILL trigger (episode 70 AND tick >= 60) never fired: episode 70 ended early (all targets found). Remedy: a supplement run (not pre-registered, training-only, no test seeds) that also merges `summaries.rx_ticks`. The kill there happened at tick 1 of episode 9.
2. A node keeps `rx_ticks` for only the last 2 episodes, so in the registered run evidence (iii)/(v') rests on the final test episodes only; the supplement merges polls.
3. Budget: 150 episodes (T37: 400); 4 drones, battery_scale 4, corner starts.
4. Receivers refused some cut-link envelopes (received_cut 9-28 per node): tick skew at window edges; none applied (amendment 2).
5. Not run: untrained net, random policy, multiple training seeds, Docker, API/dashboard.

## Product finding (not fixed; design question for the integrator)
A fault window cannot cover the whole episode: the coordinator refuses `end_tick > max_ticks` (A13) and the final episode-end exchange window runs at tick == max_ticks, outside every expressible window, so a full-episode "partition" still lets the final window exchange models. The isolated control therefore also removes all peer addresses (PEER_URLS empty). Suggest allowing end_tick = max_ticks + 1 or treating the final window as tick max_ticks - 1.
