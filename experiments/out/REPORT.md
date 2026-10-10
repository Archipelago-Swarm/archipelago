# Experiment report (generated, protocol exp-protocol-v1)

Generated from `raw.jsonl`/`summary.json`/`manifest.json`; do not edit by hand. Commit `6aab2b861f2d9cab19401cab5240251507deed4e` (worktree dirty: True), backend `numpy`, config hash `3c7ea2689aff773a`, reward `rew-v0` hash `9ca6ac3871d2fe6e`, observation `grid-flat-v0`.
Experiment seeds: **n=3** (PRELIMINARY, n<10); 20 training episodes per cell; 20 frozen test seeds (200..219); validation seeds [100, 101, 102, 103, 104]. Train world seeds 1000 + seed*episodes + episode are disjoint from both (asserted). Reproduce: `python3 experiments/run.py --seeds 3 --episodes 20 --mode all --out experiments/out --report` with PYTHONPATH=`packages/learning:packages/sim:experiments`.

## Modes

| mode | label |
|---|---|
| rule | required: rule-based explorer (visit memory, no learning) |
| idle | required: idle control (all drones stay) |
| independent | required: independent DQN |
| info_only | required: independent DQN + map/status sharing (no model transfer) |
| p2p | required: info_only + validated peer model candidates |
| replay_sharing | secondary: independent DQN + raw replay-row sharing (not in evaluation.md) |
| central_online | secondary: ONE shared learner stands in for a controller; not a validated central-controller comparison |
| ctde | secondary: per-node actors + joint-critic reward shaping; an approximation, not a validated CTDE algorithm |

Secondary modes are not validated comparisons; see the labels. Rule/idle do not train.

## Scenario `connected`: test results (mean ± sd over experiment seeds)

| mode | return | coverage | targets found | collisions/agent-step | ticks |
|---|---|---|---|---|---|
| rule | 99.08 ± 0.00 | 0.89 ± 0.00 | 7.70 ± 0.00 | 0.003 | 99.7 |
| idle | 1.63 ± 0.00 | 0.17 ± 0.00 | 1.25 ± 0.00 | 0.000 | 150.0 |
| independent | 8.12 ± 1.10 | 0.33 ± 0.02 | 2.53 ± 0.21 | 0.203 | 150.0 |
| info_only | 8.12 ± 1.10 | 0.33 ± 0.02 | 2.53 ± 0.21 | 0.203 | 150.0 |
| p2p | 11.85 ± 5.46 | 0.34 ± 0.03 | 2.80 ± 0.28 | 0.183 | 150.0 |
| replay_sharing | 10.75 ± 6.75 | 0.33 ± 0.02 | 2.53 ± 0.28 | 0.172 | 150.0 |
| central_online | -2.90 ± 6.97 | 0.33 ± 0.01 | 2.72 ± 0.13 | 0.352 | 150.0 |
| ctde | 3.71 ± 4.10 | 0.30 ± 0.03 | 2.48 ± 0.19 | 0.213 | 150.0 |

Paired difference vs `independent` (bootstrap 95% CI over seeds; a claim needs a CI excluding 0):

| mode | n | mean diff | 95% CI | wins |
|---|---|---|---|---|
| central_online | 3 | -11.012 | (-20.012, -4.512) | 0 |
| ctde | 3 | -4.408 | (-9.375, +0.575) | 1 |
| idle | 3 | -6.492 | (-7.762, -5.787) | 0 |
| info_only | 3 | +0.000 | (+0.000, +0.000) | 0 |
| p2p | 3 | +3.729 | (+0.837, +8.750) | 3 |
| replay_sharing | 3 | +2.633 | (-6.250, +8.462) | 2 |
| rule | 3 | +90.962 | (+89.691, +91.666) | 3 |

Paired difference vs `idle` (bootstrap 95% CI over seeds; a claim needs a CI excluding 0):

| mode | n | mean diff | 95% CI | wins |
|---|---|---|---|---|
| central_online | 3 | -4.521 | (-12.250, +1.275) | 1 |
| ctde | 3 | +2.083 | (-1.613, +6.500) | 2 |
| independent | 3 | +6.492 | (+5.787, +7.762) | 3 |
| info_only | 3 | +6.492 | (+5.787, +7.762) | 3 |
| p2p | 3 | +10.221 | (+6.762, +16.512) | 3 |
| replay_sharing | 3 | +9.125 | (+1.512, +14.387) | 3 |
| rule | 3 | +97.453 | (+97.453, +97.453) | 3 |

## Scenario `node_failure`: test results (mean ± sd over experiment seeds)

| mode | return | coverage | targets found | collisions/agent-step | ticks |
|---|---|---|---|---|---|
| rule | 91.49 ± 0.00 | 0.83 ± 0.00 | 7.05 ± 0.00 | 0.000 | 127.0 |
| idle | 2.28 ± 0.00 | 0.17 ± 0.00 | 1.25 ± 0.00 | 0.000 | 150.0 |
| independent | 14.33 ± 5.32 | 0.32 ± 0.04 | 2.52 ± 0.35 | 0.193 | 150.0 |
| info_only | 14.33 ± 5.32 | 0.32 ± 0.04 | 2.52 ± 0.35 | 0.193 | 150.0 |
| p2p | 18.72 ± 6.48 | 0.32 ± 0.03 | 2.63 ± 0.18 | 0.115 | 150.0 |
| replay_sharing | 19.53 ± 2.25 | 0.32 ± 0.02 | 2.45 ± 0.18 | 0.065 | 150.0 |
| central_online | 12.29 ± 2.65 | 0.33 ± 0.03 | 2.72 ± 0.31 | 0.285 | 150.0 |
| ctde | 2.85 ± 9.60 | 0.28 ± 0.02 | 2.33 ± 0.48 | 0.359 | 150.0 |

Paired difference vs `independent` (bootstrap 95% CI over seeds; a claim needs a CI excluding 0):

| mode | n | mean diff | 95% CI | wins |
|---|---|---|---|---|
| central_online | 3 | -2.046 | (-7.287, +2.088) | 1 |
| ctde | 3 | -11.479 | (-28.537, -0.938) | 0 |
| idle | 3 | -12.058 | (-18.087, -8.000) | 0 |
| info_only | 3 | +0.000 | (+0.000, +0.000) | 0 |
| p2p | 3 | +4.392 | (+0.962, +10.113) | 3 |
| replay_sharing | 3 | +5.196 | (-2.400, +9.750) | 2 |
| rule | 3 | +77.157 | (+71.128, +81.215) | 3 |

Paired difference vs `idle` (bootstrap 95% CI over seeds; a claim needs a CI excluding 0):

| mode | n | mean diff | 95% CI | wins |
|---|---|---|---|---|
| central_online | 3 | +10.012 | (+7.062, +12.175) | 3 |
| ctde | 3 | +0.579 | (-10.450, +7.062) | 2 |
| independent | 3 | +12.058 | (+8.000, +18.087) | 3 |
| info_only | 3 | +12.058 | (+8.000, +18.087) | 3 |
| p2p | 3 | +16.450 | (+8.962, +20.200) | 3 |
| replay_sharing | 3 | +17.254 | (+15.687, +19.837) | 3 |
| rule | 3 | +89.215 | (+89.215, +89.215) | 3 |

## Scenario `partition_reconnect`: test results (mean ± sd over experiment seeds)

| mode | return | coverage | targets found | collisions/agent-step | ticks |
|---|---|---|---|---|---|
| rule | 99.08 ± 0.00 | 0.89 ± 0.00 | 7.70 ± 0.00 | 0.003 | 99.7 |
| idle | 1.63 ± 0.00 | 0.17 ± 0.00 | 1.25 ± 0.00 | 0.000 | 150.0 |
| independent | 8.12 ± 1.10 | 0.33 ± 0.02 | 2.53 ± 0.21 | 0.203 | 150.0 |
| info_only | 8.12 ± 1.10 | 0.33 ± 0.02 | 2.53 ± 0.21 | 0.203 | 150.0 |
| p2p | 5.11 ± 10.60 | 0.33 ± 0.02 | 2.60 ± 0.18 | 0.249 | 150.0 |
| replay_sharing | 12.32 ± 6.02 | 0.32 ± 0.01 | 2.50 ± 0.13 | 0.130 | 150.0 |
| central_online | 15.87 ± 4.13 | 0.39 ± 0.01 | 2.97 ± 0.36 | 0.199 | 150.0 |
| ctde | 3.71 ± 4.10 | 0.30 ± 0.03 | 2.48 ± 0.19 | 0.213 | 150.0 |

Paired difference vs `independent` (bootstrap 95% CI over seeds; a claim needs a CI excluding 0):

| mode | n | mean diff | 95% CI | wins |
|---|---|---|---|---|
| central_online | 3 | +7.758 | (+3.837, +9.825) | 3 |
| ctde | 3 | -4.408 | (-9.375, +0.575) | 1 |
| idle | 3 | -6.492 | (-7.762, -5.787) | 0 |
| info_only | 3 | +0.000 | (+0.000, +0.000) | 0 |
| p2p | 3 | -3.008 | (-15.537, +7.475) | 1 |
| replay_sharing | 3 | +4.208 | (-3.925, +9.162) | 2 |
| rule | 3 | +90.962 | (+89.691, +91.666) | 3 |

Paired difference vs `idle` (bootstrap 95% CI over seeds; a claim needs a CI excluding 0):

| mode | n | mean diff | 95% CI | wins |
|---|---|---|---|---|
| central_online | 3 | +14.250 | (+9.625, +17.587) | 3 |
| ctde | 3 | +2.083 | (-1.613, +6.500) | 2 |
| independent | 3 | +6.492 | (+5.787, +7.762) | 3 |
| info_only | 3 | +6.492 | (+5.787, +7.762) | 3 |
| p2p | 3 | +3.483 | (-7.775, +13.262) | 2 |
| replay_sharing | 3 | +10.700 | (+3.837, +15.087) | 3 |
| rule | 3 | +97.453 | (+97.453, +97.453) | 3 |

## Scenario `telemetry_outage`: test results (mean ± sd over experiment seeds)

| mode | return | coverage | targets found | collisions/agent-step | ticks |
|---|---|---|---|---|---|
| rule | 99.08 ± 0.00 | 0.89 ± 0.00 | 7.70 ± 0.00 | 0.003 | 99.7 |
| idle | 1.63 ± 0.00 | 0.17 ± 0.00 | 1.25 ± 0.00 | 0.000 | 150.0 |
| independent | 8.12 ± 1.10 | 0.33 ± 0.02 | 2.53 ± 0.21 | 0.203 | 150.0 |
| info_only | 8.12 ± 1.10 | 0.33 ± 0.02 | 2.53 ± 0.21 | 0.203 | 150.0 |
| p2p | 11.85 ± 5.46 | 0.34 ± 0.03 | 2.80 ± 0.28 | 0.183 | 150.0 |
| replay_sharing | 10.75 ± 6.75 | 0.33 ± 0.02 | 2.53 ± 0.28 | 0.172 | 150.0 |
| central_online | -2.90 ± 6.97 | 0.33 ± 0.01 | 2.72 ± 0.13 | 0.352 | 150.0 |
| ctde | 3.71 ± 4.10 | 0.30 ± 0.03 | 2.48 ± 0.19 | 0.213 | 150.0 |

Paired difference vs `independent` (bootstrap 95% CI over seeds; a claim needs a CI excluding 0):

| mode | n | mean diff | 95% CI | wins |
|---|---|---|---|---|
| central_online | 3 | -11.012 | (-20.012, -4.512) | 0 |
| ctde | 3 | -4.408 | (-9.375, +0.575) | 1 |
| idle | 3 | -6.492 | (-7.762, -5.787) | 0 |
| info_only | 3 | +0.000 | (+0.000, +0.000) | 0 |
| p2p | 3 | +3.729 | (+0.837, +8.750) | 3 |
| replay_sharing | 3 | +2.633 | (-6.250, +8.462) | 2 |
| rule | 3 | +90.962 | (+89.691, +91.666) | 3 |

Paired difference vs `idle` (bootstrap 95% CI over seeds; a claim needs a CI excluding 0):

| mode | n | mean diff | 95% CI | wins |
|---|---|---|---|---|
| central_online | 3 | -4.521 | (-12.250, +1.275) | 1 |
| ctde | 3 | +2.083 | (-1.613, +6.500) | 2 |
| independent | 3 | +6.492 | (+5.787, +7.762) | 3 |
| info_only | 3 | +6.492 | (+5.787, +7.762) | 3 |
| p2p | 3 | +10.221 | (+6.762, +16.512) | 3 |
| replay_sharing | 3 | +9.125 | (+1.512, +14.387) | 3 |
| rule | 3 | +97.453 | (+97.453, +97.453) | 3 |

## Training budgets (mean per cell over seeds and scenarios)

| mode | train episodes | env steps | transitions | optimizer updates | update samples | info bytes | model bytes | replay bytes | blocked agent-steps |
|---|---|---|---|---|---|---|---|---|---|
| rule | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| idle | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| independent | 20 | 2943 | 5564 | 5502 | 176053 | 0 | 0 | 0 | 0 |
| info_only | 20 | 2943 | 5564 | 5502 | 176053 | 29940 | 0 | 0 | 0 |
| p2p | 20 | 2960 | 5596 | 5534 | 177083 | 30252 | 36964 | 0 | 0 |
| replay_sharing | 20 | 2978 | 5632 | 5570 | 178224 | 0 | 0 | 1228734 | 0 |
| central_online | 20 | 2925 | 5375 | 5344 | 170997 | 0 | 0 | 0 | 150 |
| ctde | 20 | 3000 | 5675 | 8582 | 274624 | 0 | 0 | 0 | 0 |

Equal episode counts are not equal budgets: node_failure loses the dead node's transitions, central_online loses transitions while its control link is cut, and rule/idle train nothing. Compare modes only with these columns in view.

## Per-scenario transitions (mean per cell)

| mode | connected | node_failure | partition_reconnect | telemetry_outage |
|---|---|---|---|---|
| rule | 0 | 0 | 0 | 0 |
| idle | 0 | 0 | 0 | 0 |
| independent | 5883 | 4605 | 5883 | 5883 |
| info_only | 5883 | 4605 | 5883 | 5883 |
| p2p | 5872 | 4700 | 5939 | 5872 |
| replay_sharing | 5981 | 4681 | 5882 | 5981 |
| central_online | 5821 | 4571 | 5287 | 5821 |
| ctde | 6000 | 4700 | 6000 | 6000 |

## Candidate validation overhead (p2p)

78 candidate decisions, 39 accepted, 39 rejected; 780 validation episodes (117000 env ticks), 443562 candidate bytes, 17.6 wall seconds (timing.jsonl, nondeterministic). Per-decision records are in raw.jsonl `decisions`.

## Fault ticks reached in test episodes (fraction of test episodes)

| scenario | mode | reached |
|---|---|---|
| node_failure | rule | kill=1.00 |
| node_failure | idle | kill=1.00 |
| node_failure | independent | kill=1.00 |
| node_failure | info_only | kill=1.00 |
| node_failure | p2p | kill=1.00 |
| node_failure | replay_sharing | kill=1.00 |
| node_failure | central_online | kill=1.00 |
| node_failure | ctde | kill=1.00 |
| partition_reconnect | rule | cut=1.00, rejoin=1.00 |
| partition_reconnect | idle | cut=1.00, rejoin=1.00 |
| partition_reconnect | independent | cut=1.00, rejoin=1.00 |
| partition_reconnect | info_only | cut=1.00, rejoin=1.00 |
| partition_reconnect | p2p | cut=1.00, rejoin=1.00 |
| partition_reconnect | replay_sharing | cut=1.00, rejoin=1.00 |
| partition_reconnect | central_online | cut=1.00, rejoin=1.00 |
| partition_reconnect | ctde | cut=1.00, rejoin=1.00 |
| telemetry_outage | rule | outage_end=1.00, outage_start=1.00 |
| telemetry_outage | idle | outage_end=1.00, outage_start=1.00 |
| telemetry_outage | independent | outage_end=1.00, outage_start=1.00 |
| telemetry_outage | info_only | outage_end=1.00, outage_start=1.00 |
| telemetry_outage | p2p | outage_end=1.00, outage_start=1.00 |
| telemetry_outage | replay_sharing | outage_end=1.00, outage_start=1.00 |
| telemetry_outage | central_online | outage_end=1.00, outage_start=1.00 |
| telemetry_outage | ctde | outage_end=1.00, outage_start=1.00 |

Minimum battery at episode end across all test episodes: 0.400 (never exhausted before the horizon).
