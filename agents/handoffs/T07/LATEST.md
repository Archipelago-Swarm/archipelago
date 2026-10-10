# Handoff: T07 / 20261010T062257Z (worker A)

- State: review (changes in working tree; supervisor owns commit/push, so nothing is committed by the worker)
- Branch: agent/A/20261010T062257Z/T07
- Reserved paths: packages/learning/, packages/node/learner/, tests/learning/
- Milestone: [20261010T062803Z-A](MILESTONE-20261010T062803Z-A.md)

## Done and verified (round 3)

- Round-2 review issues addressed:
  - Grid sim hookup: `packages/learning/archipelago_learning/rollout.py` trains/evaluates `Learner` on `GridParallelEnv`.
  - Transfer experiment: `transfer_experiment(seed)` compares treated vs control. The control is an identical student with no offer. The offer is gated on validation seeds and both arms are scored on disjoint test seeds, so a regression would show as delta < 0. Run over 3 seeds.
  - Mixing: a test now shows an accepted mix equals `(1-a)*own + a*peer` and its step is bounded by `a*|peer-own|`.
  - Node wrapper: `packages/node/learner/archipelago_learner` provides `LearnerNode`. It broadcasts via T05 `Network`/`Envelope` and offers delivered payloads. It converts learner events into contract `LearningEvent` records (`flush`).
  - Partition test: `Network(links=set())` cuts all links, islands keep training, then `set_links` heals; accepted/rejected/none events validate against the contract.
  - `ruff format/check` clean on the reserved paths. The dqn/peer formatting changes are included.
- Command (repo root): `uv run --offline pytest tests -q -s` -> 77 passed (11 in tests/learning).
- Grid transfer result (seeds 0-2, test-seed mean return): delta = +2.88, +7.47, +7.17. The offer was accepted every time. This is a small, short-trained experiment, not a claim of general benefit.

## Limits / unfinished

- Source node/hash/version cannot go into `LearningEvent` fields, because contracts are frozen. They are carried in `reason` for accepted offers. The full dict stays in `learner.events`.
- The grid experiment is short (8x8 map, 2 agents, 40 teacher episodes) and uses one shared policy for both agent slots in training. Per-node-experience peer learning on the grid is only demonstrated in the partition test, not as a benefit measurement.
- Peer offers are not rate limited. mypy was not run (not configured for these paths).
- The task card `agents/tasks/T07*.md` still says waiting/unclaimed. It is outside my reserved paths, so the integrator or supervisor must update it.

## Next steps

1. Supervisor: commit and push, then rerun the independent review.
2. Optionally add a decentralized grid experiment where each node trains on its own experience and exchanges candidates.

## Supervisor checkpoint 2026-10-10T06:28:55Z

- Run: 20261010T062257Z
- Machine: A
- Task/branch: T07 / agent/A/20261010T062257Z/T07
- Base: 149f1e48ba35ff4afef178d5245f51eaf50fc4bd
- Round: 3
- State: review
- External check exit: 0
- Independent review: {"pass": true, "issues": ["Non-blocking: the round-3 work is uncommitted and unpushed in the working tree, so the supervisor must commit and push it (the contract requires a pushed handoff). The task card T07.md still says waiting/unclaimed, and the integrator must update it.", "Non-blocking: the grid transfer experiment only shows a benefit with one shared policy. Per-node decentralized exchange on the grid is demonstrated only in the partition test, not measured. The assertion permits regression and the handoff reports this honestly.", "Non-blocking: source, hash and version are not contract fields. They are carried in the `reason` string of accepted LearningEvent records, and the full dict stays in learner.events.", "Non-blocking: the restart test covers Learner.save/load only, not a LearnerNode-level restart."]}
- Next issue: none
- Resume: fetch this branch, inspect latest commit and continue the task card.
