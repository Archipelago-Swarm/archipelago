# Run 20261010T132342Z: T09 run report (worker A, partial)

- Start / end UTC: 2026-10-10T13:23Z / see latest supervisor checkpoint in LATEST.md
- Machines / leads / billing mode: machine A; local CPU only, no cloud spend
- Final integrated commit: none; branch agent/A/20261010T132342Z/T09 (supervisor owns commit/push)
- Demo URL or exact local command: `PYTHONPATH=packages/learning:packages/sim python experiments/run.py --seeds 12 --episodes 150 --out agents/handoffs/T09/evidence`
- Gate status G0-G4: not assessed by this worker

## Delivered behavior and validation

Modes rule, independent, information_only, p2p, central_online, ctde, plus an `idle` control, over connected/split/rejoin/node_failure. Paired diffs vs independent with bootstrap 95% CIs, replay hashes, manifest with rerun command. `python -m pytest tests/experiments -q`: 12 tests.

## Tasks: done / review / partial / blocked / paused

T09: **partial/blocked** (owner worker A, branch agent/A/20261010T132342Z/T09, handoff `agents/handoffs/T09/LATEST.md`).
Blocked on integrator decisions, none solvable inside `experiments/`:
1. Real CTDE actor/critic split (needs `packages/learning`). Until then ctde vs central_online is a training-availability comparison only.
2. Real node loss (needs env support). `node_failure` is a `Down` stub.
3. Compute-cap approval for sweeps larger than 12 seeds x 150 episodes.
4. Task card status/assignment/acceptance boxes (outside reserved paths).
Next step once unblocked: rerun the sweep with real CTDE and node loss at the approved cap.

## Research evidence and limitations

Evidence: `agents/handoffs/T09/evidence/{manifest,summary}.json`, `raw.jsonl`; narrative in `experiments/REPORT.md`. n=12 seeds, 150 episodes: PRELIMINARY.
Negative/inconclusive: no learner beats the `idle` control; the central_online split gain (+4.3) equals idle exactly and is an artifact; no central-vs-CTDE superiority claim is supported. `information_only` is a replay-copy approximation. Acceptance check "CTDE does not lose inference" holds partly by construction.

## Resource and usage accounting

Env steps, exchange bytes, wall seconds (manifest). Model usage/cost: unavailable. Cloud IDs: none. Sweep ~3.5-5 min local CPU.

## Next run

Resolve the four blockers above, then rerun and update the report. Human action: approve compute cap; decide who edits `packages/learning` and the env.
