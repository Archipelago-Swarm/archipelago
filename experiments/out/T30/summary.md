# T30 live pilot: real processes, real optimizer updates, real peer exchange

Pre-registration `experiments/prereg/T30.yaml` at commit `d41d7d061682c8e6e765cbc7bf90ee6e08aa9f97` (committed before the run); code commit `4e504bc1d7df8dcb80cbf802042b4d5e0c7d72dc` (working tree DIRTY for experiments/packages/services). Reproduce: `uv run python experiments/t30_live.py all` (about 40 min wall on 4 cores; no Docker, no cloud).

Setup: per arm one coordinator and four node processes on localhost (`tests/e2e/procs.py` Cluster, configuration only changed in `experiments/t30_cluster.py`), world 16x16, 8 targets, 150 ticks, 4 drones in the corners, battery_scale 4, T37 ids (`grid-flat-v2-visits-shared`, `rew-v1`, `sched-t37-v1`), PyTorch 2.14.1+cu130 on every node. Episodes per arm: {'train': 150, 'validation': 9, 'test': 20} (train / validation / test). Fleet: halves {node-01,node-02} | {node-03,node-04} cut during ticks [40,90) of every episode, exchange window every 25 ticks. Isolated control: all links cut for ticks [0,150) of every episode and no node holds any peer address (prereg amendment 1). SIGKILL of node-03 at episode index 70, tick >= 60, in both arms.

**Budget deviation (decided before any result, see prereg `budget_note`):** 150 training episodes of 150 ticks per node, not T37's 400 episodes (that would take ~80 min per arm). The learner is therefore under-trained relative to T37, and one training run per arm exists (no training-seed replication).

## Verdict

- A (four nodes each do optimizer updates on their own policy/optimizer/replay): **SUPPORTED** (isolated arm: SUPPORTED)
- B (partition: local learning continues, nothing crosses the cut, exchange resumes with validation-gated decisions): **NOT SUPPORTED** (isolated control: SUPPORTED)
- C (SIGKILL, restart from checkpoint, sequence numbers kept, learning resumes): **NOT SUPPORTED** in fleet; isolated: **NOT SUPPORTED**
- D1 live-trained fleet beats idle on all three primary metrics (CI lower bound > 0): **SUPPORTED**
- D2 fleet beats the rule explorer on reference return: **NOT SUPPORTED** (CI verdict: worse)
- D3 fleet beats the isolated-nodes control on reference return (exchange helps): **SUPPORTED** (CI verdict: better)
- isolated control beats idle on all three primary metrics: **NOT SUPPORTED**

## D. Outcomes on the frozen test worlds 200-219

Mean per world (20 worlds; greedy frozen policies for fleet/isolated, scripted for idle/rule):

| metric | fleet | isolated | idle | rule |
|---|---|---|---|---|
| reference return (rew-v1 re-scored) | 17.763 | -24.896 | -39.000 | 28.757 |
| coverage gain after spawn | 0.722 | 0.770 | 0.000 | 0.796 |
| targets found after spawn (of 8) | 6.900 | 6.450 | 0.000 | 7.000 |
| wall collisions / episode | 2.900 | 15.100 | 0.000 | 0.000 |
| revisit rate | 0.161 | 0.405 | 1.000 | 0.103 |
| episode ticks | 24.300 | 72.750 | 150.000 | 44.900 |

Paired differences (first minus second), mean [95% bootstrap CI over worlds, 4000 resamples, seed 0]; worlds+/worlds- = number of worlds where the difference is positive/negative:

| metric | pair | mean diff [95% CI] | worlds+ / worlds- | CI verdict |
|---|---|---|---|---|
| reference return (rew-v1 re-scored) | fleet - idle | +56.763 [+38.926, +66.577] | 19 / 1 | better |
| reference return (rew-v1 re-scored) | fleet - rule | -10.994 [-28.797, -1.139] | 6 / 14 | worse |
| reference return (rew-v1 re-scored) | fleet - isolated | +42.659 [+14.864, +74.786] | 15 / 5 | better |
| reference return (rew-v1 re-scored) | isolated - idle | +14.104 [-23.665, +46.684] | 14 / 6 | inconclusive |
| reference return (rew-v1 re-scored) | isolated - rule | -53.653 [-90.929, -21.520] | 3 / 17 | worse |
| coverage gain after spawn | fleet - idle | +0.722 [+0.684, +0.759] | 20 / 0 | better |
| coverage gain after spawn | fleet - rule | -0.074 [-0.120, -0.024] | 5 / 14 | worse |
| coverage gain after spawn | fleet - isolated | -0.048 [-0.087, -0.008] | 5 / 15 | worse |
| coverage gain after spawn | isolated - idle | +0.770 [+0.737, +0.800] | 20 / 0 | better |
| coverage gain after spawn | isolated - rule | -0.026 [-0.062, +0.008] | 9 / 11 | inconclusive |
| targets found after spawn (of 8) | fleet - idle | +6.900 [+6.500, +7.300] | 20 / 0 | better |
| targets found after spawn (of 8) | fleet - rule | -0.100 [-0.300, +0.000] | 0 / 1 | inconclusive |
| targets found after spawn (of 8) | fleet - isolated | +0.450 [+0.200, +0.700] | 8 / 0 | better |
| targets found after spawn (of 8) | isolated - idle | +6.450 [+5.950, +6.900] | 20 / 0 | better |
| targets found after spawn (of 8) | isolated - rule | -0.550 [-0.950, -0.250] | 0 / 8 | worse |
| wall collisions / episode | fleet - idle | +2.900 [+0.400, +6.400] | 4 / 0 | better |
| wall collisions / episode | fleet - rule | +2.900 [+0.400, +6.400] | 4 / 0 | better |
| wall collisions / episode | fleet - isolated | -12.200 [-33.552, +3.151] | 3 / 6 | inconclusive |
| wall collisions / episode | isolated - idle | +15.100 [+0.700, +35.850] | 6 / 0 | better |
| wall collisions / episode | isolated - rule | +15.100 [+0.700, +35.850] | 6 / 0 | better |
| revisit rate | fleet - idle | -0.839 [-0.917, -0.740] | 0 / 20 | worse |
| revisit rate | fleet - rule | +0.059 [-0.019, +0.161] | 11 / 9 | inconclusive |
| revisit rate | fleet - isolated | -0.243 [-0.385, -0.102] | 4 / 13 | worse |
| revisit rate | isolated - idle | -0.595 [-0.747, -0.446] | 0 / 20 | worse |
| revisit rate | isolated - rule | +0.302 [+0.152, +0.453] | 13 / 7 | better |
| episode ticks | fleet - idle | -125.700 [-134.850, -110.800] | 0 / 19 | worse |
| episode ticks | fleet - rule | -20.600 [-35.851, -0.700] | 2 / 18 | worse |
| episode ticks | fleet - isolated | -48.450 [-75.501, -20.950] | 5 / 14 | worse |
| episode ticks | isolated - idle | -77.250 [-104.601, -49.647] | 0 / 12 | worse |
| episode ticks | isolated - rule | +27.850 [-4.350, +60.301] | 9 / 11 | inconclusive |

Uncertainty: the CI resamples the 20 test worlds only. There is one training run per arm, so training-run variance (which T37 showed to be large at this budget) is NOT in these intervals; a different training seed could move the fleet and the isolated arm by more than the CIs suggest. Metrics re-score the actions the live nodes chose (coordinator replay `raw/<arm>/replays/ep-NNNN`, final state hash checked) with the T37 reference return. The fault schedule of the arm also applies to its test episodes.

Sources: `experiments/out/T30/curves.csv` (per-episode metrics, test rows are the last 20 per arm), `experiments/out/T30/results.json:64` (all pairs).

### Learning curve checkpoints (validation seeds 100-102, greedy frozen, mean of 3 worlds; training-episode means are exploration-confounded)

| arm | after training episodes | ref return | coverage gain | targets after spawn |
|---|---|---|---|---|
| fleet | 50 | -59.15 | 0.61 | 5.33 |
| fleet | 100 | -4.90 | 0.79 | 6.33 |
| fleet | 150 | 24.29 | 0.70 | 6.67 |
| isolated | 50 | -70.88 | 0.61 | 3.33 |
| isolated | 100 | 21.77 | 0.65 | 6.67 |
| isolated | 150 | 23.75 | 0.66 | 6.67 |

## A. Independent learning on each node

| node | train steps | own replay | policy version | policy sha256 (first 12) | local_update events | boot id |
|---|---|---|---|---|---|---|
| node-01 | 7763 | 8587 | 7955 | 713206c26963 | 389 | 6537b775 |
| node-02 | 7816 | 8587 | 8092 | 89c9ed30c8c6 | 392 | a3989e78 |
| node-03 | 7801 | 8587 | 8018 | d001d764c7a9 | 388 | de9ef7d1 |
| node-04 | 7847 | 8587 | 8120 | d001d764c7a9 | 393 | bbf79c7c |

Distinct final policy hashes: fleet 3 of 4 (an accepted peer candidate replaces the receiver's parameters, so ties are expected there), isolated 4 of 4 (required). Over all 1 s status samples (all four nodes reachable): fleet {'n_samples': 863, 'share_with_4_distinct': 0.8667439165701043, 'min_distinct': 1, 'max_distinct': 4}, isolated {'n_samples': 1008, 'share_with_4_distinct': 1.0, 'min_distinct': 4, 'max_distinct': 4}. Fleet checks: every node train_steps > 0: True; every node own replay non-empty: True; local_update telemetry events on every node: True; backend is torch-cpu: True. Isolated checks: every node train_steps > 0: True; every node own replay non-empty: True; local_update telemetry events on every node: True; backend is torch-cpu: True; four distinct final policy hashes: True.
Pointers: `experiments/out/T30/results.json:485` (fleet), `experiments/out/T30/raw/fleet/node_status_final.json` (full node status incl. `train_steps`, `replay_size`, `policy_sha256`, `backend`), `experiments/out/T30/raw/fleet/telemetry.jsonl.gz` (all shipped records; `local_update` LearningEvents), per-node checkpoints pointers `experiments/out/T30/raw/fleet/node_local/node-01/ckpt_current.json`. Each node has its own checkpoint directory and telemetry spool (`raw/<arm>/node_local/<node>`).

## B. Partition window

**fleet** (NOT SUPPORTED):

- PASS: (i) train_steps rose inside the cut window in every sampled episode, every node
- PASS: (ii) no cross-cut offer decided inside the cut window
- PASS: (iii) no cross-cut visit summary applied inside the cut window
- PASS: (iv) offers_cut>0 and summaries_cut>0 on every node (receiver refusals are reported, amendment 2)
- PASS: (v) cross-cut offers decided after the cut ended (exchange resumed), with reasons
- FAIL: (v') open same-side peers kept exchanging inside the cut (positive control)
- PASS: cross-cut summaries do flow outside the window (positive control)
- decisions: 3279 total (958 accepted, 2321 rejected); cross-cut inside window: 0; cross-cut outside window: 1863; same-side inside window: 470; same-side outside window: 946; reasons: {'candidate': 1310, 'accepted': 958, 'window_limit': 1011}
- visit summaries applied (receiver tick vs window; node `summaries.rx_ticks`, only the current boot of node-03 is in memory): {'cross_applied_inside_cut': 0, 'cross_applied_outside_cut': 136, 'same_side_applied_inside_cut': 0, 'same_side_applied_outside_cut': 68}
- poll evidence of local learning inside the cut (episodes where train_steps grew / stayed flat between first and last sample in the window): {'node-01': {'episodes_with_growth_in_window': 57, 'episodes_flat_in_window': 0}, 'node-02': {'episodes_with_growth_in_window': 57, 'episodes_flat_in_window': 0}, 'node-03': {'episodes_with_growth_in_window': 57, 'episodes_flat_in_window': 0}, 'node-04': {'episodes_with_growth_in_window': 57, 'episodes_flat_in_window': 0}}

**isolated** (SUPPORTED):

- PASS: train_steps rose in every sampled episode, every node
- PASS: zero model decisions from any peer
- PASS: zero visit summaries applied from any peer
- PASS: offers_cut>0; nothing sent, nothing received
- decisions: 0 total (0 accepted, 0 rejected); cross-cut inside window: 0; cross-cut outside window: 0; same-side inside window: 0; same-side outside window: 0; reasons: {}
- visit summaries applied (receiver tick vs window; node `summaries.rx_ticks`, only the current boot of node-03 is in memory): {'cross_applied_inside_cut': 0, 'cross_applied_outside_cut': 0, 'same_side_applied_inside_cut': 0, 'same_side_applied_outside_cut': 0}
- poll evidence of local learning inside the cut (episodes where train_steps grew / stayed flat between first and last sample in the window): {'node-01': {'episodes_with_growth_in_window': 130, 'episodes_flat_in_window': 0}, 'node-02': {'episodes_with_growth_in_window': 130, 'episodes_flat_in_window': 0}, 'node-03': {'episodes_with_growth_in_window': 131, 'episodes_flat_in_window': 0}, 'node-04': {'episodes_with_growth_in_window': 131, 'episodes_flat_in_window': 0}}

Counters per node (fleet), `offers_cut`/`summaries_cut` are sends suppressed by the sender's schedule, `received_cut`/`summaries_received_cut` receives refused on a cut link:

| node | offers_sent | offers_cut | offers_received | received_cut | accepted | rejected | window_limit | summaries_sent | summaries_cut | summaries_received | summaries_received_cut | deadline misses |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| node-01 | 918 | 284 | 917 | 11 | 192 | 651 | 210 | 23158 | 5454 | 23160 | 0 | 0 |
| node-02 | 915 | 284 | 920 | 9 | 276 | 559 | 299 | 23154 | 5454 | 23160 | 0 | 0 |
| node-03 | 911 | 284 | 920 | 13 | 217 | 609 | 239 | 23160 | 5454 | 23159 | 0 | 0 |
| node-04 | 928 | 284 | 914 | 28 | 273 | 502 | 263 | 23162 | 5454 | 23158 | 3 | 0 |

Pointers: `experiments/out/T30/decisions.jsonl:2` (last cross-cut decision after a cut ended: exchange resumed), `experiments/out/T30/decisions.jsonl:3` (first accepted), `experiments/out/T30/decisions.jsonl:1` (first rejected, with reason), `experiments/out/T30/results.json:592` (fleet) and `experiments/out/T30/results.json:795` (isolated), `experiments/out/T30/results.json:607`, `experiments/out/T30/raw/fleet/samples.jsonl:5` (first 1 s status sample inside a cut), `experiments/out/T30/spool_excerpt.jsonl:1` (node-local spool record of the same decision).

## C. SIGKILL and restart

**fleet**: kill NOT executed in the registered run: the trigger (episode index 70 AND tick >= 60) never fired because episode 70 ended before tick 60 (episodes end once all targets are found). This is a defect of the registered trigger, found only after the run; see the supplementary run below.
**isolated**: kill NOT executed in the registered run: the trigger (episode index 70 AND tick >= 60) never fired because episode 70 ended before tick 60 (episodes end once all targets are found). This is a defect of the registered trigger, found only after the run; see the supplementary run below.
The state lost to the kill is the work since the last checkpoint generation (checkpoint every 200 feedback steps and at episode end, A17); train steps after restart are therefore at most the pre-kill value. While the node was down the coordinator applied `stay` for it, and marked it unavailable until the next episode reset.

## Supplementary run (NOT pre-registered): claims B-summaries and C on a short fleet run

Why: in the registered run the node keeps its visit-summary trace (`summaries.rx_ticks`) for only the last 2 episodes, which were test episodes ending before tick 40, so evidence (iii) and the positive control (v') above rest on almost no in-window ticks; and the SIGKILL trigger never fired (see C). The supplement is a separate 20-episode training-only fleet run (same cluster, ids, fault schedule, seeds 1000-1019; no test seeds, no outcome claims) that merges `rx_ticks` over every 1 s poll (`supplement/fleet/rx_merged.json`) and SIGKILLs node-03 at the first poll after episode 8 starts. It was added after seeing the registered results, and only because those two items had not been exercised; it is a deviation from the plan and is labelled as such.

- PASS B: (i) train_steps rose inside the cut window in every sampled episode, every node
- PASS B: (ii) no cross-cut offer decided inside the cut window
- PASS B: (iii) no cross-cut visit summary applied inside the cut window
- PASS B: (iv) offers_cut>0 and summaries_cut>0 on every node (receiver refusals are reported, amendment 2)
- PASS B: (v) cross-cut offers decided after the cut ended (exchange resumed), with reasons
- PASS B: (v') open same-side peers kept exchanging inside the cut (positive control)
- PASS B: cross-cut summaries do flow outside the window (positive control)
- summaries (merged trace): {'cross_applied_inside_cut': 0, 'cross_applied_outside_cut': 9817, 'same_side_applied_inside_cut': 2227, 'same_side_applied_outside_cut': 4912}
- decisions: 623 (cross-cut inside window: 0, cross-cut outside window: 351, reasons {'candidate': 235, 'accepted': 187, 'window_limit': 201})
- C: node-03 killed at episode 9 tick 1; before: boot dfa6b09e, train_steps 872, replay 980; after restart: boot 76375976, train_steps 871, replay 978; sequence ranges [{'boot_id': 'dfa6b09e', 'first': 0, 'last': 2005, 'n': 1028}, {'boot_id': '76375976', 'first': 3000, 'last': 4591, 'n': 842}]; max train_steps later 1569
- C checks: PASS new_boot_id; PASS restored_from_checkpoint; PASS train_steps_restored_positive_and_not_ahead; PASS replay_restored; PASS sequences_continue_above_pre_kill; PASS no_event_id_reused; PASS sequence_ceiling_not_lower; PASS learning_resumed
- Pointers: `experiments/out/T30/supplement/results.json:23`, `experiments/out/T30/supplement/fleet/kill.json:17`, `experiments/out/T30/supplement/fleet/kill.json:62`, `experiments/out/T30/supplement/decisions.jsonl`

## Unsupported claims and limits

- **Beating the rule explorer is not shown** (fleet-rule reference return -10.994 [-28.797, -1.139], verdict worse).
- The isolated control does not beat idle on all three primary metrics.
- Claim B (fleet) failed checks: ["(v') open same-side peers kept exchanging inside the cut (positive control)"].
- Claim C (fleet) failed or not executed: [].
- Claim C (isolated) failed or not executed: [].
- Not run: untrained same-architecture network and random policy (T37 criteria for 'learning helps' also use them); only idle, rule explorer and the isolated control are compared.
- One training run per arm (fixed seed): no between-training-run variance, so D-claims are about these two trained fleets only. Differences between fleet and isolated can be training-run noise.
- Training budget 150 episodes per node, below T37's 400; no hyperparameter was changed from the T37-selected recipe and nothing was tuned on test seeds.
- The fleet arm's cut is a halves partition (two groups of two keep exchanging), not total isolation; its test episodes are also run under the cut.
- World differs from T37: 4 drones (T37: 2), battery_scale 4 (T37: 1), fixed corner starts; the live world has no peer map-cell merge (T38 deviation 1), so results are not comparable one-to-one to T37 numbers.
- Telemetry evidence comes from a driver-side sink standing in for the API ingest; the API, the dashboard and TigerData were not part of this run. Docker/Compose were not run.
- Summary-trace evidence (`rx_ticks`) is held in node memory: the restarted node-03 only has post-restart episodes.
- Wall-clock effects: both arms ran concurrently on the same 4 cores; deadline misses are reported in the counters table, not hidden.

## Files

`results.json` (all numbers), `curves.csv`, `decisions.jsonl` (every telemetry decision of both arms with source, cut flags and reasons), `spool_excerpt.jsonl`, `raw/<arm>/` (`samples.jsonl` 1 s status polls, `telemetry.jsonl.gz`, `coordinator_events.jsonl.gz`, `run_status.json`, `kill.json`, `node_status_final.json`, `replays/`, `node_local/`, `logs/`).
