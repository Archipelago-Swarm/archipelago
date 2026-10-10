# Handoff: T09 / 2026-10-10 (run 20261010T072103Z, worker A)

- State: in_progress (first slice; local, not committed by worker)
- Branch: agent/A/20261010T072103Z/T09, base 426574f
- Reserved paths: experiments/, tests/experiments/, agents/handoffs/T09/

## Completed (local)
- `experiments/run.py`: modes rule, independent, information_only, p2p, central_online, ctde x scenarios
  connected/split/rejoin/node_failure. Emits raw.jsonl (returns + action-replay sha256 per test episode),
  summary.json (paired diff vs independent, bootstrap 95% CI over seeds, win counts), manifest.json
  (args, rerun command, file hashes, env steps, wall seconds).
- Matched budget: same training env seeds and episode count for every mode; train seeds asserted disjoint
  from val (900-903) and test (950-955).
- CTDE trains regardless of link (decentralised inference copies), so it is not penalised for offline
  training; central_online only trains while the link is up (documented in code).
- `tests/experiments/test_run.py`: seed overlap detection, deterministic replay hashes, ctde link-invariance,
  central_online differs under split, bundle written.

## Validation
- `.venv/Scripts/python -m pytest tests/experiments -q` -> 3 passed; ruff check/format clean.
- Smoke sweep: `PYTHONPATH="packages/learning;packages/sim" .venv/Scripts/python experiments/run.py --seeds 3 --episodes 20`
  (output in experiments/out, not for commit). n=3 seeds, 20 episodes: PRELIMINARY; most CIs include 0;
  rule baseline far above learners at this budget (+14 to +20, CI excludes 0); no superiority claim supported.

## Known limits / not done
- information_only == independent here (no observation sharing implemented), diff exactly 0.
- node_failure = node-1 stops training (paused) and exchanges; it is still scored at test.
- Resource costs are env steps + wall time only. Training budget is tiny; larger sweep not run.
- Trained-compute cap approval not checked; experiments/out should not be committed (no .gitignore change made).
- Central-superiority claims need a larger sweep before any claim.

## Next steps
1. Run larger sweep (>=10 seeds, more episodes) within approved cap; add run-report from agents/templates.
2. Implement real information sharing for information_only.

## Supervisor checkpoint 2026-10-10T07:24:01Z

- Run: 20261010T072103Z
- Machine: A
- Task/branch: T09 / agent/A/20261010T072103Z/T09
- Base: 426574f48159dbca55859f4e7ab63077d9fdf8a5
- Round: 1
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["Nothing is committed or pushed. experiments/, tests/experiments/ and agents/handoffs/T09/ are all untracked, and the handoff says 'not committed by worker'. The contract requires a pushed handoff.", "The information_only mode is not implemented. It is identical to independent (diff exactly 0), so the 'information-only' comparison in slice 1 has no real evidence and works as a stub.", "The handoff says the first slice is still in_progress and the sweep is only a smoke run (3 seeds, 20 episodes). Slice 3, the sweeps within approved compute caps, is not done. The compute-cap approval was never checked.", "Slice 2 is only tiny-budget evidence. It compares central_online and CTDE at 20 episodes, and the handoff says central-superiority claims need a larger sweep. Whether CTDE keeps its inference advantage is only covered by a link-invariance unit test, not by an experiment at a meaningful budget.", "The exported resource costs are env steps and wall time only. There is no run report from the template, and the experiments/out bundle is meant to stay uncommitted. So the acceptance check 'rerun command, hashes and all outcomes retained' has no committed evidence bundle.", "node_failure is simplified: node-1 only pauses training and exchange, and is still scored at test. This is not a real node failure.", "The report check ('names preliminary sample sizes, avoids unsupported claims') has no report document. It rests on a handoff note, not a deliverable.", "The external check showed 112 passed, but the 3 experiments tests are the only evidence for T09. They don't test the budget-matching, train/val/test seed-disjoint or paired-CI-summary acceptance checks beyond the basics."]}
- Next issue: Nothing is committed or pushed. experiments/, tests/experiments/ and agents/handoffs/T09/ are all untracked, and the handoff says 'not committed by worker'. The contract requires a pushed handoff.; The information_only mode is not implemented. It is identical to independent (diff exactly 0), so the 'information-only' comparison in slice 1 has no real evidence and works as a stub.; The handoff says the first slice is still in_progress and the sweep is only a smoke run (3 seeds, 20 episodes). Slice 3, the sweeps within approved compute caps, is not done. The compute-cap approval was never checked.; Slice 2 is only tiny-budget evidence. It compares central_online and CTDE at 20 episodes, and the handoff says central-superiority claims need a larger sweep. Whether CTDE keeps its inference advantage is only covered by a link-invariance unit test, not by an experiment at a meaningful budget.; The exported resource costs are env steps and wall time only. There is no run report from the template, and the experiments/out bundle is meant to stay uncommitted. So the acceptance check 'rerun command, hashes and all outcomes retained' has no committed evidence bundle.; node_failure is simplified: node-1 only pauses training and exchange, and is still scored at test. This is not a real node failure.; The report check ('names preliminary sample sizes, avoids unsupported claims') has no report document. It rests on a handoff note, not a deliverable.; The external check showed 112 passed, but the 3 experiments tests are the only evidence for T09. They don't test the budget-matching, train/val/test seed-disjoint or paired-CI-summary acceptance checks beyond the basics.
- Resume: fetch this branch, inspect latest commit and continue the task card.
