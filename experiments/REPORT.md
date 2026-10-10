# T09 experiment report (PRELIMINARY)

Rerun: `PYTHONPATH="packages/learning;packages/sim" python experiments/run.py --seeds 3 --episodes 20`
(writes raw.jsonl, summary.json, manifest.json with sha256 hashes to `experiments/out`).

- Sample size: n=3 experiment seeds, 20 training episodes, 6 test episodes each. Preliminary only.
- Budgets: every mode shares training env seeds, episode count and reward; train/val(900-903)/test(950-955) seeds are disjoint (asserted).
- Statistics: paired difference vs `independent`, bootstrap 95% CI over seeds. No superiority claim is made unless the CI excludes 0, and none is supported at this n.
- `information_only` never loads parameters (learner rejects every offer), so it matches `independent` by construction here; it is not evidence about information sharing.
- `node_failure`: node-1 stops training and exchanging at mid-training and stays still at test, in all modes.
- CTDE trains regardless of link; `central_online` trains only while the link is up. Central-superiority claims need a larger sweep that has not been run (compute cap not approved).
- Resource cost: env steps and wall seconds only.
