# T09 experiment report (PRELIMINARY)

Rerun: `PYTHONPATH="packages/learning;packages/sim" python experiments/run.py --seeds 3 --episodes 20`
(writes raw.jsonl, summary.json, manifest.json with sha256 hashes to `experiments/out`).

- Sample size: n=3 experiment seeds, 20 training episodes, 6 test episodes each. Preliminary only.
- Budgets: every mode shares training env seeds, episode count and reward; train/val(100000-100003)/test(200000-200005) seeds are disjoint (asserted).
- Statistics: paired difference vs `independent`, bootstrap 95% CI over seeds. No superiority claim is made unless the CI excludes 0, and none is supported at this n.
- `information_only` never loads parameters (learner rejects every offer), so it matches `independent` by construction here; it is not evidence about information sharing.
- `node_failure`: node-1 stops training and exchanging at mid-training and stays still at test, in all modes.
- CTDE trains regardless of link; `central_online` trains only while the link is up. Central-superiority claims need a larger sweep that has not been run (compute cap not approved).
- Resource cost: env steps and wall seconds only.

## Committed evidence bundle (larger sweep)

`agents/handoffs/T09/evidence/{raw.jsonl,summary.json,manifest.json}`: 12 seeds x 150 episodes x 6 modes x 4 scenarios (~3.6 min, local CPU, no cloud spend; manifest has sha256 and rerun command). Still PRELIMINARY (n=12); no formal compute cap was approved, so it was kept small.
- Only `p2p` vs `independent` has a CI excluding 0 (connected +5.3, rejoin +4.5); `rule` beats all learners (+11 to +14). Negative/null: `central_online` is -5.6 in `split` (CI touches 0) and null elsewhere; `ctde` is null everywhere (+2.8, CI includes 0).
- `ctde` is identical in all link schedules (+2.837): it keeps decentralised inference and does not lose it when the link is down. `central_online` loses only the training episodes it misses.
- `information_only` is still a stub (== independent); `node_failure` is a simplification (node-1 stops training and stays still at test).
