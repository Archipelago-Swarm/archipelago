# T09 experiment report (PRELIMINARY)

Rerun the committed bundle (~3.5 min local CPU, no cloud spend):
`PYTHONPATH=packages/learning:packages/sim python experiments/run.py --seeds 12 --episodes 150 --out agents/handoffs/T09/evidence`
Output: `raw.jsonl` (returns + action-replay sha256 per test episode), `summary.json`, `manifest.json` (args, rerun command, sha256 of the two hashed files; wall time only in the manifest). Reruns are byte-identical for the hashed files.

## Setup

- Sample size: **n=12 experiment seeds**, 150 training episodes, 6 test episodes each. PRELIMINARY; no compute cap was approved, so the sweep was kept small.
- Budgets: every mode shares training env seeds, episode count and reward. Train / val (100000-100003) / test (200000-200005) seeds are disjoint (asserted).
- Statistics: paired difference vs `independent`, bootstrap 95% CI over seeds. A claim needs a CI excluding 0.
- `information_only`: copies raw replay rows between nodes every 5 episodes while the link is up; never loads parameters. `p2p` exchanges parameters (accepted only if validation improves).
- `node_failure`: from mid-training node 1 is replaced by a `Down` stub (stays put, no data, no learning, no exchange), also at test, in all modes. The drone remains in the sim world, so this is an approximation of node loss.
- `ctde` and `central_online` share one `Learner` (no separate actor/critic). `ctde` trains regardless of link and infers with decentralised copies; `central_online` trains only while the link is up. This is a training-availability comparison, not a full CTDE algorithm.
- Resource cost recorded: env steps, exchange bytes, wall seconds (manifest only). No energy accounting.

## Results (n=12, difference vs independent, 95% CI)

- `rule` beats every learner at this budget: +11.9 to +14.3, CI excludes 0 everywhere.
- `p2p`: connected +5.3 (2.0..8.9), rejoin +4.5 (0.6..8.4) exclude 0; split 0 by design; node_failure +0.9 (includes 0).
- `information_only`: rejoin +4.3 (0.3..8.9) barely excludes 0; connected +1.9, node_failure -1.1 include 0. Not a robust claim.
- `central_online` (negative/null): split -5.6 (-11.0..0.1), node_failure -0.9, rejoin +0.2, connected +2.8; all CIs include 0.
- `ctde` +2.8 (-2.0..8.0) in connected/split/rejoin: identical across link schedules, so it does not lose inference when the link is down. Null vs independent.

## Not supported / open

- No central-online vs CTDE superiority claim is supported at this n.
- No real CTDE actor/critic; node failure is a stub; compute cap approval is not on record.
