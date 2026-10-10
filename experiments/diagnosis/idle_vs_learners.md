# Why idle and the rule-based explorer beat the learners

Status: development pilot, PRELIMINARY. Source: `experiments/diagnosis/pilot.py` -> `pilot_results.json`
(41.6 s wall); every number below is printed by `experiments/diagnosis/summarize.py`.
Setup: scenario `connected`, 3 experiment seeds x 40 training episodes, evaluated greedily on the five
**validation (dev) seeds 100-104**. The frozen TEST seeds (200-219) were not used, so nothing here is
tuned on them. n is tiny; treat sizes of effects, not decimals, as the finding.

## Headline measurements (dev seeds, mean over 3 x 5 episodes)

| policy | return | ticks | targets found (of 8) | coverage | wall collisions | revisit rate |
|---|---|---|---|---|---|---|
| idle | 2.00 | 150 | 1.40 | 0.15 | 0.0 | 0.99 |
| rule (visit memory) | 101.70 | 110 | 7.20 | 0.91 | 0.0 (2.8 agent-agent) | 0.13 |
| independent DQN (v0 obs) | 5.17 | 150 | 2.93 | 0.30 | 73.6 | 0.96 |
| independent DQN (v1-map obs, opt-in) | -5.22 | 142 | 2.73 | 0.31 | 98.0 | 0.93 |
| info_only (v1-map obs, opt-in) | -1.40 | 150 | 2.67 | 0.39 | 134.1 | 0.94 |

Per-seed independent-v0 returns: 0.55, 10.05, 4.90. Rule is identical across seeds (it is a fixed function of
the episode seed), so rule-vs-learner differences carry only learner variance.

## Findings

1. **Return decomposition (mean per agent).** idle: target +3.5 (targets already within sensing range of the spawn
   point are paid on tick 1 for free), step -1.5, nothing else. rule: new-cell +85.5, target +18.0, step -1.1,
   collision -0.7. independent-v0: new-cell +17.7, target +7.3, step -1.5, **collision -18.4**. The learner
   earns some exploration reward but gives most of it back to wall collisions (73.6 per episode, 0.5 each).
   Idle beats a learner whenever collisions cost more than exploration earns; it is a floor, not a competitor.
   (Part of idle's return is a free-target artifact; report coverage gain and targets found after spawn too.)
2. **Observation: no memory, so the reward is not Markov in the observation.** The flat observation is the 5x5
   crop of the node's own buffer plus pose/size and battery (28 values). The crop radius equals the sensing
   radius, so every in-range cell is known: the only UNKNOWN (-1) crop cells are outside the map
   (5 of 25 at the audited reset). The crop therefore cannot say whether a neighbouring cell was already visited,
   yet the +1 new-cell reward is paid only for cells nobody has visited (the visited set is global and also
   includes the other drone's visits). The rule explorer uses exactly that missing signal (per-cell visit
   counts): its revisit rate is 0.13 versus 0.93-0.99 for every learner. Learners loop: the greedy policy is a
   deterministic function of a memoryless observation, so a repeated observation repeats the action forever
   (traces: independent-v0 seed 0 oscillates north/south then emits `stay` from tick 7 on; info_only-v1 holds
   `west` against the same wall from tick 8 on). Pose is normalised absolute position on a map that is
   re-drawn every episode, so it adds little generalisable information.
3. **Information sharing is inert under the current observation.** Because the crop never contains an unsensed
   cell, merging a peer's map into the local buffer cannot change any crop. Measured: info_only and independent
   produce byte-identical action hashes under `grid-flat-v0`
   (`test_shared_map_is_inert_under_v0_and_visible_under_v1_map`). The shared summary only becomes visible in
   an observation that exposes map knowledge, so the opt-in `grid-flat-v1-map` (4x4 block known-fractions) was
   added to the harness for study. It is **not** the default and is not used by the committed protocol. On the
   dev pilot it neither clearly helps nor hurts (info_only -1.40 vs independent -5.22, per-seed ranges overlap).
4. **Reward structure.** (new 1.0, target 5.0 split between agents, step -0.01, collision -0.5, invalid -0.1.)
   Per-step reward in replay averages 0.27-0.38; only 11-14 percent of replayed rewards exceed 0.5. Q-values are
   large (max 38-75) while the spread across the five actions at a state is only about 1.9-2.5, and the TD loss
   sits at 2-3 (RMS TD error about 1.4-1.7). The wall-collision penalty (0.5) is smaller than the noise in the
   value estimates, so the value ordering of "bump a wall" versus "step away" is not reliably learned in 40
   episodes (about 5.8k optimizer updates per learner).
5. **Exploration and training stability.** Constant epsilon 0.2 for all 40 episodes (no schedule), so early data
   is not broader and late data is 20 percent random, which also keeps injecting the collisions that the
   penalty is meant to remove. Loss windows are non-monotone (e.g. seed 1: 4.1 -> 2.5; seed 0 v1: 2.0 -> 3.4 ->
   2.9): no sign of convergence or of divergence to NaN, Adam lr 1e-2 on a 32-unit network, target sync every 50
   steps, replay capacity 5000 keeps only the last ~17 episodes of ~5.8k transitions. The greedy action
   histogram over replayed states is spread over 4-5 actions, so this is not simple action collapse; the
   collapse is behavioural (fixed points reached at test time).
6. **Test-protocol defects that also favoured the controls (fixed in this repair).** The T09 world (8x8, 2 targets,
   60 ticks) ended a median ~7 ticks in (targets inside the spawn sensing radius), so learners trained on tiny
   episodes, the `split`/`node_failure` schedules never fired, and the rule baseline kept visit memory across
   test episodes. `central_online` and `idle` matched exactly in split because the controller was unreachable.

## Conclusion

Idle and rule beat the learners because (a) the learners' observation lacks the one signal that the dominant
reward term depends on (visited cells), producing loops and wall-bumping fixed points, (b) the collision
penalty is below the value-estimate noise at this training budget, and (c) idle is an inflated floor in a
reward that pays for targets near the spawn. This is an observation/reward-design and budget issue, not
evidence that transfer cannot help. With the memoryless observation, information_only is provably equal to
independent and p2p can only differ through model transfer.

## Proposals (not applied to the committed protocol)

All changes are versioned ids; protocol results stay on `grid-flat-v0` / `rew-v0` until a pre-registered run.

| proposal | change | expected effect | owner |
|---|---|---|---|
| obs `grid-flat-v1-map` | already opt-in in `experiments/harness.py`: append coarse known-fraction map | makes shared map visible, gives a visited-area signal; may reduce loops | experiments (T32) |
| obs `grid-flat-v2-visits` | add visit counts (or a last-k position memory) of the 4 neighbours | removes the non-Markov new-cell reward, aims to cut the revisit rate from about 0.9 toward the rule explorer 0.13 | sim/contracts owners |
| reward `rew-v1` | collision -0.5 -> -2.0 or reward scale 1/5 plus Huber loss; do not pay targets sensed at reset | raises collision signal over TD noise; removes idle's free targets | sim + learning (T26) |
| learner schedule | epsilon 1.0 -> 0.05 linear over the first 50 percent of episodes, lr 1e-3, replay >= 50k, double DQN | fewer random collisions at the end, steadier loss | learning (T26/T30) |

Evaluation without tuning on test seeds: (1) pre-register the config hash and the grid of variants; (2) pick
the variant using only training seeds and validation seeds 100-104, with >= 10 experiment seeds and the same
budget table as `experiments/REPORT.md` (transitions, updates, bytes); (3) freeze the choice, then run once on
TEST 200-219 against the rule, idle and independent controls and report the paired CI vs both idle and
independent; (4) report negative results, the revisit rate and the wall-collision rate, and the sham/random
update controls from evaluation.md. A change only counts as an improvement if it helps `independent` first
(so that info_only/p2p effects are measured on a learner that is not at the floor).
