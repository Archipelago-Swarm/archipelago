# T37 variant study: does learning help once the problem is learnable?

Pre-registration: `experiments/prereg/T37.yaml`, original commit `77074bb7180525e59f4ffff8c9b922d7626a8eb6`, latest (amendment 1) `b0c4c2ef7f1aebd3fd0422f5d327dcda642bea19`, file sha256 `5eaf9e1f4b1b0eb0`. Code at `d245ba3a8c`. Reproduce: `PYTHONPATH=packages/learning:packages/sim:experiments uv run python experiments/t37.py all` (about 25 minutes on 4 cores, seeded, deterministic).

World: 16x16, 2 drones, 8 targets, 150 ticks, scenario connected. Metrics: reference return (rew-v1 components re-scored for every policy, so reward variants share one yardstick; it charges revisits, so idle is strongly negative by construction), coverage gain and targets found after spawn (reward-free). Selection used only training seeds (>=1000), validation seeds 100-104 and held-out worlds 5000-5019. TEST 200-219 was used once, after selection.

## Verdict (frozen TEST seeds 200-219, one shot)

- learning helps (vs idle on all three metrics, vs untrained net and vs random policy on return, hierarchical 95% CI lower bound > 0): **True**
- beats the rule explorer (pre-registered criterion): **False**

## Selected configuration

`grid-flat-v2-visits-shared|rew-v1|eps1-0.05@0.5|lr0.001|rb50000|ddqn`

- observation id `grid-flat-v2-visits-shared`, float32[82] (layout below)
- reward id `rew-v1`
- epsilon schedule: epsilon 1 -> 0.05 linearly over the first 50% of training episodes, then constant (per episode, evaluated at the episode start)
- Adam lr 0.001, gamma 0.95, batch 32, hidden 32, target sync every 50 optimizer steps, one optimizer step per recorded transition, MSE TD loss, no gradient clipping
- replay capacity 50000 transitions per node (uniform sampling, ring buffer)
- double DQN: target y = r + gamma*(1-done)*Q_target(s2, argmax_a Q_online(s2,a))
- done = environment termination only (time-limit truncation still bootstraps)
- 400 training episodes per node, world seed 1000 + seed*400 + i

## Stage A (successive halving round 1): 4 seeds x 200 episodes, 25 selection worlds

| rank | config | mean ref return | kept |
|---|---|---|---|
| 1 | `grid-flat-v2-visits-shared|rew-v1|eps1-0.05@0.5|lr0.003|rb50000|ddqn` | 26.59 | yes |
| 2 | `grid-flat-v2-visits-shared|rew-v1|eps1-0.05@0.5|lr0.001|rb50000|ddqn` | 26.52 | yes |
| 3 | `grid-flat-v2-visits|rew-v1|eps1-0.05@0.5|lr0.001|rb5000|ddqn` | 16.00 | yes |
| 4 | `grid-flat-v2-visits|rew-v1|eps0.2|lr0.001|rb50000|ddqn` | 2.08 | yes |
| 5 | `grid-flat-v2-visits|rew-v1|eps1-0.05@0.5|lr0.003|rb50000|ddqn` | -2.26 |  |
| 6 | `grid-flat-v2-visits|rew-v1|eps1-0.05@0.5|lr0.001|rb50000|ddqn` | -3.46 |  |
| 7 | `grid-flat-v2-visits|rew-v1|eps1-0.1@0.3|lr0.001|rb50000|ddqn` | -12.47 |  |
| 8 | `grid-flat-v2-visits|rew-v1|eps1-0.05@0.5|lr0.001|rb50000|dqn` | -12.49 |  |
| 9 | `grid-flat-v2-visits|rew-v1|eps1-0.05@0.5|lr0.01|rb50000|ddqn` | -12.69 |  |
| 10 | `grid-flat-v0|rew-v1|eps1-0.05@0.5|lr0.001|rb50000|ddqn` | -15.60 |  |
| 11 | `grid-flat-v2-visits|rew-v0|eps1-0.05@0.5|lr0.001|rb50000|ddqn` | -41.16 |  |

## Stage B: finalists + control, 10 seeds x 400 episodes (means over seeds)

| config | ref ret VAL | ref ret SEL25 | cov gain VAL | targets VAL | wall coll VAL | revisit VAL |
|---|---|---|---|---|---|---|
| `grid-flat-v2-visits-shared|rew-v1|eps1-0.05@0.5|lr0.003|rb50000|ddqn` | 23.12 | 23.48 | 0.675 | 5.70 | 12.7 | 0.433 |
| `grid-flat-v2-visits-shared|rew-v1|eps1-0.05@0.5|lr0.001|rb50000|ddqn` **(selected)** | 34.72 | 33.29 | 0.711 | 5.92 | 7.3 | 0.409 |
| `grid-flat-v2-visits|rew-v1|eps1-0.05@0.5|lr0.001|rb5000|ddqn` | 7.21 | 17.24 | 0.722 | 5.86 | 21.0 | 0.291 |
| `grid-flat-v2-visits|rew-v1|eps0.2|lr0.001|rb50000|ddqn` | 14.78 | 9.08 | 0.677 | 5.92 | 7.5 | 0.299 |
| `grid-flat-v0|rew-v0|eps0.2|lr0.01|rb5000|dqn` (control) | -110.85 | -91.20 | 0.284 | 1.92 | 92.4 | 0.919 |
| baseline idle (SEL25) | - | -39.00 | 0.000 | 0.00 | - | - |
| baseline rule (SEL25) | - | 49.36 | 0.726 | 6.08 | - | - |
| baseline random (SEL25) | - | -38.45 | 0.471 | 3.36 | - | - |

Selected config vs baselines, paired (learner minus baseline), 95% CI:

**val_100_104**

| metric | baseline | mean diff | hier. CI | seed-only CI |
|---|---|---|---|---|
| reference return (rew-v1 re-scored) | idle | +73.719 | [+56.29, +86.27] | [+61.11, +83.20] |
| reference return (rew-v1 re-scored) | rule | -14.360 | [-31.08, -0.82] | [-26.97, -4.88] |
| reference return (rew-v1 re-scored) | random | +72.519 | [+53.25, +90.56] | [+59.91, +82.00] |
| coverage gain after spawn | idle | +0.711 | [+0.62, +0.78] | [+0.67, +0.75] |
| coverage gain after spawn | rule | -0.050 | [-0.16, +0.04] | [-0.09, -0.02] |
| coverage gain after spawn | random | +0.216 | [+0.16, +0.27] | [+0.18, +0.25] |
| targets found after spawn (of 8) | idle | +5.920 | [+5.04, +6.68] | [+5.44, +6.30] |
| targets found after spawn (of 8) | rule | +0.120 | [-1.04, +1.58] | [-0.36, +0.50] |
| targets found after spawn (of 8) | random | +2.320 | [+0.92, +4.16] | [+1.84, +2.70] |

**selection_25**

| metric | baseline | mean diff | hier. CI | seed-only CI |
|---|---|---|---|---|
| reference return (rew-v1 re-scored) | idle | +72.286 | [+62.47, +80.56] | [+66.76, +76.84] |
| reference return (rew-v1 re-scored) | rule | -16.074 | [-26.53, -7.79] | [-21.60, -11.52] |
| reference return (rew-v1 re-scored) | random | +71.737 | [+58.17, +84.04] | [+66.21, +76.29] |
| coverage gain after spawn | idle | +0.678 | [+0.63, +0.72] | [+0.67, +0.69] |
| coverage gain after spawn | rule | -0.048 | [-0.09, -0.01] | [-0.06, -0.04] |
| coverage gain after spawn | random | +0.207 | [+0.16, +0.25] | [+0.20, +0.22] |
| targets found after spawn (of 8) | idle | +5.948 | [+5.47, +6.41] | [+5.80, +6.08] |
| targets found after spawn (of 8) | rule | -0.132 | [-0.51, +0.26] | [-0.28, -0.00] |
| targets found after spawn (of 8) | random | +2.588 | [+1.80, +3.37] | [+2.44, +2.72] |

## One-shot TEST result (seeds 200-219, 10 experiment seeds, selected config only)

| metric | learner | baseline | baseline mean | mean diff | hier. 95% CI | seed-only CI | seeds with diff>0 |
|---|---|---|---|---|---|---|---|
| reference return (rew-v1 re-scored) | 34.874 | idle | -39.000 | +73.874 | [+65.14, +80.97] | [+69.42, +77.78] | 10/10 |
| reference return (rew-v1 re-scored) | 34.874 | rule | 50.666 | -15.792 | [-24.68, -8.63] | [-20.25, -11.89] | 0/10 |
| reference return (rew-v1 re-scored) | 34.874 | random | -29.485 | +64.359 | [+51.37, +76.65] | [+59.90, +68.26] | 10/10 |
| reference return (rew-v1 re-scored) | 34.874 | untrained | -180.132 | +215.006 | [+197.62, +231.23] | [+210.55, +218.91] | 10/10 |
| coverage gain after spawn | 0.721 | idle | 0.000 | +0.721 | [+0.69, +0.75] | [+0.71, +0.73] | 10/10 |
| coverage gain after spawn | 0.721 | rule | 0.720 | +0.001 | [-0.04, +0.05] | [-0.01, +0.02] | 6/10 |
| coverage gain after spawn | 0.721 | random | 0.486 | +0.235 | [+0.18, +0.29] | [+0.22, +0.25] | 10/10 |
| coverage gain after spawn | 0.721 | untrained | 0.081 | +0.640 | [+0.60, +0.68] | [+0.62, +0.65] | 10/10 |
| targets found after spawn (of 8) | 6.190 | idle | 0.000 | +6.190 | [+5.76, +6.62] | [+6.03, +6.32] | 10/10 |
| targets found after spawn (of 8) | 6.190 | rule | 6.450 | -0.260 | [-0.56, +0.03] | [-0.42, -0.13] | 1/10 |
| targets found after spawn (of 8) | 6.190 | random | 3.900 | +2.290 | [+1.65, +2.97] | [+2.13, +2.42] | 10/10 |
| targets found after spawn (of 8) | 6.190 | untrained | 0.745 | +5.445 | [+4.97, +5.91] | [+5.29, +5.58] | 10/10 |
| wall collisions / episode | 5.440 | idle | 0.000 | +5.440 | [+1.94, +10.73] | [+3.50, +7.49] | 10/10 |
| wall collisions / episode | 5.440 | rule | 0.000 | +5.440 | [+1.94, +10.73] | [+3.50, +7.49] | 10/10 |
| wall collisions / episode | 5.440 | random | 36.750 | -31.310 | [-38.39, -23.50] | [-33.25, -29.26] | 0/10 |
| wall collisions / episode | 5.440 | untrained | 139.765 | -134.325 | [-149.68, -118.06] | [-136.27, -132.28] | 0/10 |
| revisit rate | 0.396 | idle | 1.000 | -0.604 | [-0.68, -0.53] | [-0.64, -0.57] | 0/10 |
| revisit rate | 0.396 | rule | 0.145 | +0.251 | [+0.16, +0.33] | [+0.21, +0.28] | 10/10 |
| revisit rate | 0.396 | random | 0.759 | -0.363 | [-0.45, -0.28] | [-0.40, -0.33] | 0/10 |
| revisit rate | 0.396 | untrained | 0.978 | -0.582 | [-0.66, -0.51] | [-0.62, -0.55] | 0/10 |

Decision record: `{"learning_helps_vs_idle_all_three_metrics": true, "beats_untrained_same_architecture": true, "beats_random_policy_on_return": true, "LEARNING_HELPS": true, "beats_rule_on_return": false, "BEATS_RULE": false, "criteria": {"learning_helps": "TRUE iff, on the frozen TEST worlds for the selected config, the hierarchical CI lower bound of (learner - idle) is > 0 on ALL THREE primary metrics AND (learner - untrained) > 0 on ref_return AND (learner - random) > 0 on ref_return. Otherwise the claim is NOT supported.\n", "beats_rule": "TRUE iff learning_helps AND (learner - rule) CI lower bound > 0 on ref_return AND the upper bound of (learner - rule) is >= 0 on all three metrics. Otherwise \"does not beat rule\"; a CI containing zero is reported as inconclusive, a CI entirely below zero as the learner being worse.\n"}}`

## Adoption note for T38 (PyTorch runtime must reproduce exactly)

- observation id `grid-flat-v2-visits-shared`, float32[82] (layout below)
- reward id `rew-v1`
- epsilon schedule: epsilon 1 -> 0.05 linearly over the first 50% of training episodes, then constant (per episode, evaluated at the episode start)
- Adam lr 0.001, gamma 0.95, batch 32, hidden 32, target sync every 50 optimizer steps, one optimizer step per recorded transition, MSE TD loss, no gradient clipping
- replay capacity 50000 transitions per node (uniform sampling, ring buffer)
- double DQN: target y = r + gamma*(1-done)*Q_target(s2, argmax_a Q_online(s2,a))
- done = environment termination only (time-limit truncation still bootstraps)
- 400 training episodes per node, world seed 1000 + seed*400 + i

Observation layouts (all float32; crop is 5x5 = sense radius 2, row-major, dy outer, dx inner,
values -1 unknown / 0 free / 1 wall from the node's own buffer):

| index | content | scaling |
|---|---|---|
| 0-24 | crop | raw -1/0/1 |
| 25, 26 | pose x, y | x/size, y/size (size 16) |
| 27 | battery | clipped to [0, 1] |
| 28-52 | `grid-flat-v2-visits`: own stand-on count of each crop cell (same order as crop; spawn cell counts 1; staying counts) | min(count, 4)/4 |
| 53-56 | frontier north, east, south, west: fraction of the 5 cells just outside the crop (row y-3, column x+3, row y+3, column x-3, offsets -2..2) that are inside the map and not in the node's buffer | 0..1 in steps of 0.2 |
| 57-81 | `grid-flat-v2-visits-shared` only: 1 if a peer reported standing on that crop cell through the information message, else 0 | 0/1 |

`grid-flat-v2-visits` = indices 0-56 (57 values); `grid-flat-v2-visits-shared` = 0-81 (82 values).
Frontier cells count as known if they were sensed by this node or merged from a peer's information
message (map cells), so the frontier already reflects shared map knowledge when the InfoBus runs.
The information message (non-model): per tick per directed pair, the cells the sender knows and has
not yet sent (3 bytes), new markers (2 bytes), header 4 bytes and, for `-shared`, newly stood-on
cells (2 bytes each). Implementation: `experiments/protocol_harness.py` (`InfoBus`, `flat`) and
`packages/sim/archipelago_sim/env.py` (`GridWorld.observe_memory`, `Drone.visits/peer_visits`).
`rew-v1` constants: new cell +0.5 per newly sensed free cell, target +5.0 split over living nodes and
only for targets NOT already sensed at reset, step -0.01, wall/agent collision -2.0 each, invalid
action -0.1, revisit -0.25 whenever a node ends a tick on a cell it already stood on (includes
staying and bumping a wall).

Cross-backend check: encode the same `GridWorld` state with `harness.flat` and the Torch encoder and compare element-wise; train the NumPy `VLearner` (experiments/t37.py) and the Torch learner from the same seed on a fixed replay and compare Q-values. Encoder id for the node header: `grid-flat-v2-visits-shared`; the existing `grid-flat-v1-s{size}-r{radius}` encoder (28 values) does not carry visit counts, so a new geometry-bearing id and sha256 are required (A6).

## Limits

- Only scenario `connected`; partition/node-failure/telemetry faults and p2p model transfer were not run. 2 drones, 16x16 worlds, 150 ticks, hidden 32 NumPy MLP; not the Torch runtime.
- The reference return was fixed by us and penalises revisits; read it together with the reward-free coverage gain and targets-after-spawn.
- Stage A used 4 seeds, so the top-4 cut is noisy; the one-factor-at-a-time grid does not test interactions beyond the two combined cells.
- The shared id changes two things relative to the local id: peer stood-on flags (indices 57-81) and, because the InfoBus also merges peer map cells into the buffer, a frontier feature that reflects peer knowledge. No ablation separates the two; Stage A only shows shared > local (26.5 vs -3.5 mean reference return, 4 seeds).
- The selected learner still trails the rule explorer (return CI excludes 0 on the negative side, coverage gain equal, targets after spawn inconclusive) and bumps walls ~5 times per episode (rule: 0). Revisit rate 0.40 vs rule 0.15.
- Hyperparameters other than the 11 registered cells (hidden size, gamma, batch, target sync, longer training) were not explored; the learner may still be improving at 400 episodes (see curves.csv).
- Prereg amendment 1 (stage B 500 -> 400 episodes) is recorded in the YAML.
