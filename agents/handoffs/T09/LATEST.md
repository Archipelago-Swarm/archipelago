# Handoff: T09 / 2026-10-10 (run 20261010T072103Z, worker A)

- State: blocked (needs integrator decisions; see RUN-REPORT.md) (first slice; local, not committed by worker)
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
- information_only == independent by construction (learner rejects all offers; rejected_exchanges counted in raw.jsonl). No observation sharing exists in packages/learning (outside reserved paths).
- node_failure now also makes node-1 stay put at test (all modes). Still a simplification of real node loss.
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

## Worker update (round 2)
- Added rejected_exchanges/train_env_steps per cell, node-1-down at test, experiments/REPORT.md, 2 tests (matched budget/paired CI, node_failure). 5 tests pass, ruff clean.
- Not done: larger sweep (compute cap unapproved), committed evidence bundle. Worker did not commit/push; supervisor owns that.

## Supervisor checkpoint 2026-10-10T07:25:46Z

- Run: 20261010T072103Z
- Machine: A
- Task/branch: T09 / agent/A/20261010T072103Z/T09
- Base: 426574f48159dbca55859f4e7ab63077d9fdf8a5
- Round: 2
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["information_only is still identical to independent by construction (the learner rejects all offers). Slice 1's information-only comparison has no real implementation, so this is a stubbed mode.", "Slice 3 is not done. No sweep beyond the 3-seed, 20-episode smoke run exists. The handoff says the compute cap is unapproved and unchecked.", "The central_online vs CTDE comparison (slice 2) is backed only by tiny-budget runs and a link-invariance unit test. There is no meaningful-budget evidence for the check that CTDE does not falsely lose inference.", "No evidence bundle is retained. experiments/out is deliberately uncommitted, so the rerun command, hashes and outcomes exist only locally. REPORT.md is untracked and no run report from the template exists.", "The latest handoff is a local, unpushed edit, and the work is still uncommitted (the handoff says the supervisor owns commit and push). The contract requires a pushed handoff.", "node_failure is still a simplification: node 1 is merely stationary at test, and the handoff concedes this is not a real node loss.", "Resource costs are only env steps and wall time. The tests added (5 total) cover only basic seed-disjoint, matched-budget and paired-CI behaviour."]}
- Next issue: information_only is still identical to independent by construction (the learner rejects all offers). Slice 1's information-only comparison has no real implementation, so this is a stubbed mode.; Slice 3 is not done. No sweep beyond the 3-seed, 20-episode smoke run exists. The handoff says the compute cap is unapproved and unchecked.; The central_online vs CTDE comparison (slice 2) is backed only by tiny-budget runs and a link-invariance unit test. There is no meaningful-budget evidence for the check that CTDE does not falsely lose inference.; No evidence bundle is retained. experiments/out is deliberately uncommitted, so the rerun command, hashes and outcomes exist only locally. REPORT.md is untracked and no run report from the template exists.; The latest handoff is a local, unpushed edit, and the work is still uncommitted (the handoff says the supervisor owns commit and push). The contract requires a pushed handoff.; node_failure is still a simplification: node 1 is merely stationary at test, and the handoff concedes this is not a real node loss.; Resource costs are only env steps and wall time. The tests added (5 total) cover only basic seed-disjoint, matched-budget and paired-CI behaviour.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Worker update (round 3)
- Summary rows now carry `stub: true` for information_only; raw rows carry `exchange_bytes` (resource cost). 6 tests pass, ruff clean.
- Not done (blocked/out of scope): real information sharing needs packages/learning (outside reserved paths); sweeps beyond smoke need approved compute cap; evidence bundle/commit/push belong to supervisor.

## Supervisor checkpoint 2026-10-10T07:26:56Z

- Run: 20261010T072103Z
- Machine: A
- Task/branch: T09 / agent/A/20261010T072103Z/T09
- Base: 426574f48159dbca55859f4e7ab63077d9fdf8a5
- Round: 3
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["information_only is a stub: the learner rejects every offer, so it equals independent by construction. Slice 1's information-only comparison has no real implementation. It is only flagged stub=true.", "Slice 3 is not done. Only a 3-seed, 20-episode smoke sweep exists, and the compute cap was never checked. Slice 2's central-vs-CTDE comparison has no meaningful-budget evidence.", "The 'CTDE does not falsely lose inference' check rests on a 4-episode link-invariance unit test. The code does give CTDE decentralised inference copies. There is no experiment-scale evidence.", "node_failure is a simplification: node-1 pauses training and stays still at test in every mode. It is not a real node failure.", "Resource costs are env steps, exchange bytes and wall time only. No run report from the template exists.", "The handoff's own round-3 notes still list the committed evidence bundle and the larger sweep as undone. The check output does not show that the handoff and report are pushed. The state is still in_progress.", "The 'all outcomes retained' check depends on experiments/out, which is not committed (the handoff says it should not be). The committed manifest also records a rerun command without the PYTHONPATH setup the REPORT.md gives."]}
- Next issue: information_only is a stub: the learner rejects every offer, so it equals independent by construction. Slice 1's information-only comparison has no real implementation. It is only flagged stub=true.; Slice 3 is not done. Only a 3-seed, 20-episode smoke sweep exists, and the compute cap was never checked. Slice 2's central-vs-CTDE comparison has no meaningful-budget evidence.; The 'CTDE does not falsely lose inference' check rests on a 4-episode link-invariance unit test. The code does give CTDE decentralised inference copies. There is no experiment-scale evidence.; node_failure is a simplification: node-1 pauses training and stays still at test in every mode. It is not a real node failure.; Resource costs are env steps, exchange bytes and wall time only. No run report from the template exists.; The handoff's own round-3 notes still list the committed evidence bundle and the larger sweep as undone. The check output does not show that the handoff and report are pushed. The state is still in_progress.; The 'all outcomes retained' check depends on experiments/out, which is not committed (the handoff says it should not be). The committed manifest also records a rerun command without the PYTHONPATH setup the REPORT.md gives.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Worker update (round 4)
- Ran 12 seeds x 150 episodes sweep (all modes/scenarios, ~3.6 min local); committed bundle at `agents/handoffs/T09/evidence/` (raw.jsonl, summary.json, manifest.json w/ sha256). Summary appended to `experiments/REPORT.md`.
- Moved VAL/TEST seeds to 100000+/200000+ so larger sweeps stay disjoint; manifest rerun command now includes PYTHONPATH. 6 tests pass.
- Findings: p2p > independent (CI excludes 0) in connected/rejoin; rule far above all learners; ctde identical across link schedules (keeps inference); central_online null/negative; no central-superiority claim.
- Not done: information_only still a stub (needs packages/learning, out of paths); node_failure still simplified; no formal compute-cap approval found; template run-report belongs to supervisor/integrator.

## Supervisor checkpoint 2026-10-10T07:31:58Z

- Run: 20261010T072103Z
- Machine: A
- Task/branch: T09 / agent/A/20261010T072103Z/T09
- Base: 426574f48159dbca55859f4e7ab63077d9fdf8a5
- Round: 4
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["information_only is still a stub: it is identical to independent because the learner rejects every offer. It is only flagged stub=true. Slice 1's information-only comparison has no real implementation or evidence.", "The work is not committed or pushed. git status shows run.py, REPORT.md, the tests and the handoff as modified, and the evidence/ bundle as untracked. The contract requires a pushed handoff and implementation, so it is not ready for PR review.", "node_failure is a simplification. Node 1 pauses training and stays still at test in every mode. It is not a real node loss, so the node-failure sweep in slice 3 is only partly met.", "No approval of the compute cap was found, so the 'sweeps within approved compute caps' requirement is unverified.", "The evidence bundle covers 12 seeds x 150 episodes. It is a small sample and its findings are preliminary. That is acceptable only if the report states it, and it can't support any central-superiority claim.", "No run report from the template exists.", "Tests are thin for the acceptance checks. They cover seed disjointness, matched budget and a link-invariance check for CTDE, but not the retained hashes in the manifest. They don't check the CTDE-versus-central comparison at a meaningful budget either.", "The handoff's own state is still in_progress. It lists undone items, and the task card has no completion evidence."]}
- Next issue: information_only is still a stub: it is identical to independent because the learner rejects every offer. It is only flagged stub=true. Slice 1's information-only comparison has no real implementation or evidence.; The work is not committed or pushed. git status shows run.py, REPORT.md, the tests and the handoff as modified, and the evidence/ bundle as untracked. The contract requires a pushed handoff and implementation, so it is not ready for PR review.; node_failure is a simplification. Node 1 pauses training and stays still at test in every mode. It is not a real node loss, so the node-failure sweep in slice 3 is only partly met.; No approval of the compute cap was found, so the 'sweeps within approved compute caps' requirement is unverified.; The evidence bundle covers 12 seeds x 150 episodes. It is a small sample and its findings are preliminary. That is acceptable only if the report states it, and it can't support any central-superiority claim.; No run report from the template exists.; Tests are thin for the acceptance checks. They cover seed disjointness, matched budget and a link-invariance check for CTDE, but not the retained hashes in the manifest. They don't check the CTDE-versus-central comparison at a meaningful budget either.; The handoff's own state is still in_progress. It lists undone items, and the task card has no completion evidence.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Worker update (round 5)
- Added test that committed evidence/ files match manifest sha256. No other changes.
- Still not done: information_only real implementation (needs packages/learning, outside reserved paths); real node_failure; compute-cap approval; template run report (supervisor/integrator).
- Found the manifest's summary.json sha256 was stale (file differed from recorded hash). Reran the full sweep locally: raw/summary differ from committed only in wall_s/out/rerun fields (wall time is inside the hashed files, so rerun hashes are not byte-identical; compare replay_hashes/returns instead). Updated manifest's summary.json hash to the committed file's actual sha256. raw.jsonl hash was already correct.

## Supervisor checkpoint 2026-10-10T13:06:16Z

- Run: 20261010T130137Z
- Machine: A
- Task/branch: T09 / agent/A/20261010T130137Z/T09
- Base: 110279e3754d67377172ecbd9619fc3ef364ea61
- Round: 1
- State: in_progress
- External check exit: 1
- Independent review: not run
- Next issue: External checks failed (exit 1); inspect local check log
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Worker update (run 20261010T130137Z)
- Fixed external-check failure: ruff import-order (E401/I001) and format in tests/experiments/test_run.py. ruff check/format clean; 7 tests pass.
- Not done: larger sweep (compute cap unapproved), real information_only sharing.

## Supervisor checkpoint 2026-10-10T13:07:50Z

- Run: 20261010T130137Z
- Machine: A
- Task/branch: T09 / agent/A/20261010T130137Z/T09
- Base: 110279e3754d67377172ecbd9619fc3ef364ea61
- Round: 2
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["The information_only mode is still a stub. experiments/run.py:147 flags it `stub`, and the learner rejects every offer, so it equals independent by construction. Slice 1's information-only comparison has no real implementation or evidence. The handoff says the real version needs packages/learning, which is outside the allowed paths, so this is unresolved.", "node_failure is a simplification. Node 1 pauses training and exchange and stays still at test in every mode, which is not a real node loss. Slice 3's node-failure sweep is only partly met.", "No compute-cap approval is on record. The handoff says none was found, so 'sweeps within approved compute caps' is unverified.", "The evidence bundle (12 seeds x 150 episodes) is small and preliminary. It cannot support central-vs-CTDE conclusions. CTDE's inference parity at experiment scale rests on a link-invariance result and a unit test.", "The CTDE-parity and paired-CI acceptance checks have only light test coverage. I did not find a test that exercises them at a meaningful budget.", "The evidence-hash test returns early if manifest.json is missing, so it cannot fail when the bundle is absent.", "The manifest's summary.json hash was stale and was hand-edited to the committed file's actual sha256. Reruns are not byte-identical because wall-time fields sit inside the hashed files. The 'rerun command, hashes' check is therefore only weakly met.", "Two files are still modified and uncommitted: agents/handoffs/T09/LATEST.md and tests/experiments/test_run.py. The latest handoff is not pushed, which the contract requires.", "The handoff state is still in_progress, with no run report from the template. The task card still lists unchecked acceptance boxes and a stale 'waiting' status. The worker's own handoff lists real information sharing, real node failure and compute-cap approval as undone."]}
- Next issue: The information_only mode is still a stub. experiments/run.py:147 flags it `stub`, and the learner rejects every offer, so it equals independent by construction. Slice 1's information-only comparison has no real implementation or evidence. The handoff says the real version needs packages/learning, which is outside the allowed paths, so this is unresolved.; node_failure is a simplification. Node 1 pauses training and exchange and stays still at test in every mode, which is not a real node loss. Slice 3's node-failure sweep is only partly met.; No compute-cap approval is on record. The handoff says none was found, so 'sweeps within approved compute caps' is unverified.; The evidence bundle (12 seeds x 150 episodes) is small and preliminary. It cannot support central-vs-CTDE conclusions. CTDE's inference parity at experiment scale rests on a link-invariance result and a unit test.; The CTDE-parity and paired-CI acceptance checks have only light test coverage. I did not find a test that exercises them at a meaningful budget.; The evidence-hash test returns early if manifest.json is missing, so it cannot fail when the bundle is absent.; The manifest's summary.json hash was stale and was hand-edited to the committed file's actual sha256. Reruns are not byte-identical because wall-time fields sit inside the hashed files. The 'rerun command, hashes' check is therefore only weakly met.; Two files are still modified and uncommitted: agents/handoffs/T09/LATEST.md and tests/experiments/test_run.py. The latest handoff is not pushed, which the contract requires.; The handoff state is still in_progress, with no run report from the template. The task card still lists unchecked acceptance boxes and a stale 'waiting' status. The worker's own handoff lists real information sharing, real node failure and compute-cap approval as undone.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Worker update (run 20261010T130137Z)
- Reproducibility: per-cell `wall_s` removed from `raw.jsonl`/`summary.json`; total timing now only in `manifest.json`. New test reruns into the same dir and asserts the two hashed files are byte-identical.
- Committed bundle migrated post-hoc (not re-run): `wall_s` stripped from raw/summary, sha256 recomputed in manifest (no longer hand-edited to match a stale hash). Returns and replay hashes untouched.
- `test_committed_evidence_hashes_match` now fails if the bundle is missing. 8 tests pass, ruff clean.
- Still NOT done: real information_only (needs `packages/learning`, out of reserved paths; still equals independent, flagged `stub`); real node loss (node 1 only paused/stationary); compute-cap approval (none on record, no new sweep run); sweep is 12 seeds x 150 episodes, preliminary, no central-vs-CTDE claim supported. State remains in_progress; no run report written; supervisor owns commit/push.

## Supervisor checkpoint 2026-10-10T13:09:36Z

- Run: 20261010T130137Z
- Machine: A
- Task/branch: T09 / agent/A/20261010T130137Z/T09
- Base: 110279e3754d67377172ecbd9619fc3ef364ea61
- Round: 3
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["information_only is still a stub. It equals independent by construction (experiments/run.py:147 flags stub). Slice 1's information-only comparison has no real implementation. The worker says the real version needs packages/learning, which is outside the allowed paths, so this is unresolved.", "node_failure is a simplification. Node 1 is only paused and held stationary at test. That is not a real node loss, so slice 3's node-failure sweep is only partly met.", "No compute-cap approval is on record, so 'sweeps within approved compute caps' is unverified.", "The evidence is a 12-seed, 150-episode preliminary sweep. It cannot support central-online versus CTDE conclusions. CTDE inference parity at experiment scale rests on a link-invariance unit test, not on a meaningful-budget experiment.", "The work is not pushed. agents/handoffs/T09/LATEST.md, the evidence files (manifest, raw.jsonl, summary.json), experiments/run.py and tests/experiments/test_run.py are all modified and uncommitted. The contract requires a pushed handoff.", "The committed evidence was edited after the fact. wall_s was stripped and the hashes were recomputed without re-running the sweep. The bundle was not produced by the current code, so the 'rerun command, hashes' check is weakened.", "The handoff state is still in_progress. There is no run report from the template. The task card still has all acceptance boxes unchecked, and the worker's own handoff lists real information sharing, real node failure and compute-cap approval as undone."]}
- Next issue: information_only is still a stub. It equals independent by construction (experiments/run.py:147 flags stub). Slice 1's information-only comparison has no real implementation. The worker says the real version needs packages/learning, which is outside the allowed paths, so this is unresolved.; node_failure is a simplification. Node 1 is only paused and held stationary at test. That is not a real node loss, so slice 3's node-failure sweep is only partly met.; No compute-cap approval is on record, so 'sweeps within approved compute caps' is unverified.; The evidence is a 12-seed, 150-episode preliminary sweep. It cannot support central-online versus CTDE conclusions. CTDE inference parity at experiment scale rests on a link-invariance unit test, not on a meaningful-budget experiment.; The work is not pushed. agents/handoffs/T09/LATEST.md, the evidence files (manifest, raw.jsonl, summary.json), experiments/run.py and tests/experiments/test_run.py are all modified and uncommitted. The contract requires a pushed handoff.; The committed evidence was edited after the fact. wall_s was stripped and the hashes were recomputed without re-running the sweep. The bundle was not produced by the current code, so the 'rerun command, hashes' check is weakened.; The handoff state is still in_progress. There is no run report from the template. The task card still has all acceptance boxes unchecked, and the worker's own handoff lists real information sharing, real node failure and compute-cap approval as undone.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Worker update (run 20261010T130137Z, round 4)
- State: in_progress (worker cannot mark done; nothing committed/pushed by worker).
- `information_only` is now real: `share_obs` copies each node's new raw transitions into its peer's replay at link-up exchanges (every 5 episodes); no parameters are loaded; bytes counted. `stub` flag removed. Uses only the public `Learner.observe/replay`, so no `packages/learning` change was needed (the earlier "needs packages/learning" claim was wrong).
- `node_failure` is closer to real loss: from episode `episodes//2` node 1 is replaced by `Down` (stays put, stores no data, no learning, no exchanges) during training and at test, for every mode. The sim still keeps the drone in the world (no env-level removal; that is outside reserved paths).
- Evidence regenerated by the current code (no post-hoc edits; wall_s only in manifest, unhashed): `PYTHONPATH=packages/learning:packages/sim python experiments/run.py --seeds 12 --episodes 150 --out agents/handoffs/T09/evidence` (~3.5 min local CPU, no cloud).
- Tests: `tests/experiments` 9 passed; ruff clean.
- Results (n=12, PRELIMINARY): information_only vs independent: connected +1.9 (CI includes 0), rejoin +4.3 (CI 0.3..8.9, barely excludes 0, not a robust claim), split 0 (no link, identical by design), node_failure -1.1 (CI includes 0). Rule baseline still +12 over learners at this budget. No central-online vs CTDE conclusion supported.
- Still open: no compute-cap approval on record (needs human/integrator); CTDE parity at a meaningful budget not tested; work uncommitted; task-card boxes unchecked (integrator's).
- Re-verified (same run, round 4): sweep re-run from current `experiments/run.py` over `agents/handoffs/T09/evidence`; `tests/experiments` 9 passed, ruff clean. Evidence hashes in manifest.json match the files. Nothing committed or pushed by the worker; supervisor owns the checkpoint/push.

## Supervisor checkpoint 2026-10-10T13:18:07Z

- Run: 20261010T130137Z
- Machine: A
- Task/branch: T09 / agent/A/20261010T130137Z/T09
- Base: 110279e3754d67377172ecbd9619fc3ef364ea61
- Round: 5
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["Nothing from this round is committed or pushed. experiments/run.py, tests/experiments/test_run.py, LATEST.md and the whole evidence bundle (manifest.json, raw.jsonl, summary.json) are modified and uncommitted. The contract requires a pushed handoff and implementation. The committed bundle does not match the regenerated one.", "No compute-cap approval is on record. The handoff admits this, so the 'sweeps within approved compute caps' part of slice 3 is unverified. The 12-seed x 150-episode sweep is small and preliminary.", "The CTDE check has no experiment-scale evidence. In experiments/run.py, ctde and central_online use the same single shared Learner. They differ only in that central_online skips training episodes when the link is down. In the connected scenario the two modes are identical by construction. There is no real CTDE implementation, such as per-agent actors with a central critic. The handoff concedes that CTDE parity was not tested at a meaningful budget. The slice 2 comparison is therefore mostly a stub, and the 'CTDE does not falsely lose inference' check rests only on a link-invariance unit test.", "node_failure is still a simplification. Node 1 is swapped for a Down stub that stays put, and the drone remains in the world. The sim has no real removal. Slice 3's node-failure sweep is only partly met, and the handoff says so.", "There is no report or run report from the template. The task card still has Status: waiting and all acceptance boxes unchecked. The handoff state is in_progress and lists open items. The check 'Report names preliminary sample sizes and avoids unsupported claims' relies on handoff prose and the manifest note, not on a reviewed deliverable.", "Resource costs cover only env steps, exchange bytes and wall time. Wall time appears only in the unhashed manifest. No compute or energy accounting is recorded.", "The information_only mode is new this round and has only the shallow tests. I found no evidence that these tests check the budget-matching or the replay-copy accounting, for example that no parameters leak and that the byte counts are correct."]}
- Next issue: Nothing from this round is committed or pushed. experiments/run.py, tests/experiments/test_run.py, LATEST.md and the whole evidence bundle (manifest.json, raw.jsonl, summary.json) are modified and uncommitted. The contract requires a pushed handoff and implementation. The committed bundle does not match the regenerated one.; No compute-cap approval is on record. The handoff admits this, so the 'sweeps within approved compute caps' part of slice 3 is unverified. The 12-seed x 150-episode sweep is small and preliminary.; The CTDE check has no experiment-scale evidence. In experiments/run.py, ctde and central_online use the same single shared Learner. They differ only in that central_online skips training episodes when the link is down. In the connected scenario the two modes are identical by construction. There is no real CTDE implementation, such as per-agent actors with a central critic. The handoff concedes that CTDE parity was not tested at a meaningful budget. The slice 2 comparison is therefore mostly a stub, and the 'CTDE does not falsely lose inference' check rests only on a link-invariance unit test.; node_failure is still a simplification. Node 1 is swapped for a Down stub that stays put, and the drone remains in the world. The sim has no real removal. Slice 3's node-failure sweep is only partly met, and the handoff says so.; There is no report or run report from the template. The task card still has Status: waiting and all acceptance boxes unchecked. The handoff state is in_progress and lists open items. The check 'Report names preliminary sample sizes and avoids unsupported claims' relies on handoff prose and the manifest note, not on a reviewed deliverable.; Resource costs cover only env steps, exchange bytes and wall time. Wall time appears only in the unhashed manifest. No compute or energy accounting is recorded.; The information_only mode is new this round and has only the shallow tests. I found no evidence that these tests check the budget-matching or the replay-copy accounting, for example that no parameters leak and that the byte counts are correct.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Update (run 20261010T130137Z, worker A)
- Added `test_share_obs_copies_only_replay_rows_and_bytes_match`: share_obs copies exactly k replay rows, leaves receiver parameters unchanged, and information_only exchange_bytes is a whole multiple of the per-row float32 size. `pytest tests/experiments` -> 10 passed.
- Still open (unchanged, stated plainly): no compute-cap approval on record, so slice 3 sweeps are unapproved/preliminary; ctde and central_online share one Learner (no real CTDE actor/critic), so central-superiority/CTDE claims are unsupported; node_failure is a stub (Down node stays in the world); no written report; no compute/energy accounting beyond env steps, bytes, wall time (manifest only). Task card unchanged (not a worker action).
- Nothing committed/pushed by this worker; supervisor owns checkpoint.

## Supervisor checkpoint 2026-10-10T13:18:36Z

- Run: 20261010T130137Z
- Machine: A
- Task/branch: T09 / agent/A/20261010T130137Z/T09
- Base: 110279e3754d67377172ecbd9619fc3ef364ea61
- Round: 6
- State: in_progress
- External check exit: 1
- Independent review: not run
- Next issue: External checks failed (exit 1); inspect local check log
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Update (run 20261010T130137Z, round 6 fix, worker A)
- External check failure cause: `ruff format --check` flagged `tests/experiments/test_run.py`. Ran `ruff format`; ruff check clean, `pytest tests/experiments` -> 10 passed. No logic changes.
- Open items unchanged from the previous update. Nothing committed/pushed by worker.

## Supervisor checkpoint 2026-10-10T13:19:50Z

- Run: 20261010T130137Z
- Machine: A
- Task/branch: T09 / agent/A/20261010T130137Z/T09
- Base: 110279e3754d67377172ecbd9619fc3ef364ea61
- Round: 7
- State: in_progress
- External check exit: 0
- Independent review: not run
- Next issue: Independent review unavailable or inconclusive
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Supervisor checkpoint 2026-10-10T13:20:53Z

- Run: 20261010T130137Z
- Machine: A
- Task/branch: T09 / agent/A/20261010T130137Z/T09
- Base: 110279e3754d67377172ecbd9619fc3ef364ea61
- Round: 8
- State: blocked
- External check exit: 0
- Independent review: not run
- Next issue: Independent review unavailable or inconclusive
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Worker update (run 20261010T132342Z, worker A)
- Only change: rewrote `experiments/REPORT.md`, which was stale (called information_only a stub, old rerun command). It now matches the committed 12x150 evidence/summary.json: rerun command, n, per-mode CIs, negative/null results, and open limits. No code, test or evidence change.
- Open (unchanged): compute-cap approval; ctde/central_online share one Learner (no real actor/critic); node_failure is a Down stub; no template run report. Nothing committed/pushed.

## Supervisor checkpoint 2026-10-10T13:25:04Z

- Run: 20261010T132342Z
- Machine: A
- Task/branch: T09 / agent/A/20261010T132342Z/T09
- Base: 2368137d1885098c5b1012ed08e2a31484b4f8aa
- Round: 1
- State: in_progress
- External check exit: 1
- Independent review: not run
- Next issue: External checks failed (exit 1); inspect local check log
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Worker update (run 20261010T132342Z, check-fix)
- External check failure: `test_committed_evidence_hashes_match` failed. Cause: `write_text` wrote CRLF on Windows, so manifest hashes were over CRLF bytes while git stores LF. `experiments/run.py` now writes bundle files with `write_bytes` (LF). Reran `PYTHONPATH="packages/learning;packages/sim" python experiments/run.py --seeds 12 --episodes 150 --out agents/handoffs/T09/evidence`; raw.jsonl/summary.json content unchanged, manifest.json hashes now match LF files. `tests/experiments` 10 passed, ruff clean on reserved paths.
- Note: full-repo `ruff check .` has errors in tools/ (outside reserved paths, not touched).
- Open items unchanged. Nothing committed/pushed by worker.

## Supervisor checkpoint 2026-10-10T13:38:24Z

- Run: 20261010T132342Z
- Machine: A
- Task/branch: T09 / agent/A/20261010T132342Z/T09
- Base: 2368137d1885098c5b1012ed08e2a31484b4f8aa
- Round: 2
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["Slice 2 (central-online and CTDE) is not implemented as a comparison. `ctde` and `central_online` share one `Learner` with no actor/critic split. The only difference is whether training is gated by the link. The check 'CTDE does not falsely lose inference' therefore holds by construction. Its only evidence is a link-invariance test and identical numbers across schedules.", "`node_failure` is a `Down` stub. The drone stays in the sim world, so it is not a real node loss. The failure-sweep evidence is weak, and the report and handoff both say so.", "Slice 3 has no approved compute cap on record. The 12-seed, 150-episode sweep is labelled preliminary. Resource costs are env steps, bytes and wall time only, with no compute or energy accounting.", "The change is not committed or pushed. `run.py`, `LATEST.md` and the evidence files (`manifest.json`, `raw.jsonl`) are modified in the working tree. The handoff says 'Nothing committed/pushed'. The contract requires a pushed handoff. The evidence hashes were regenerated after the checkpoint commit, and git warns about CRLF/LF conversion on `raw.jsonl`. So the committed bundle may not match the hashes in the working tree.", "The task card is unchanged: Status waiting, all acceptance boxes unchecked, and no assignment recorded. The handoff has no template-based run report. `REPORT.md` exists, but it admits the CTDE and node-failure limits and that the sweep is unapproved.", "No independent reviewer has previously passed this task. Prior rounds failed, and the latest checkpoints record 'not run' or 'inconclusive'. The handoff state is in_progress or blocked, not ready for review."]}
- Next issue: Slice 2 (central-online and CTDE) is not implemented as a comparison. `ctde` and `central_online` share one `Learner` with no actor/critic split. The only difference is whether training is gated by the link. The check 'CTDE does not falsely lose inference' therefore holds by construction. Its only evidence is a link-invariance test and identical numbers across schedules.; `node_failure` is a `Down` stub. The drone stays in the sim world, so it is not a real node loss. The failure-sweep evidence is weak, and the report and handoff both say so.; Slice 3 has no approved compute cap on record. The 12-seed, 150-episode sweep is labelled preliminary. Resource costs are env steps, bytes and wall time only, with no compute or energy accounting.; The change is not committed or pushed. `run.py`, `LATEST.md` and the evidence files (`manifest.json`, `raw.jsonl`) are modified in the working tree. The handoff says 'Nothing committed/pushed'. The contract requires a pushed handoff. The evidence hashes were regenerated after the checkpoint commit, and git warns about CRLF/LF conversion on `raw.jsonl`. So the committed bundle may not match the hashes in the working tree.; The task card is unchanged: Status waiting, all acceptance boxes unchecked, and no assignment recorded. The handoff has no template-based run report. `REPORT.md` exists, but it admits the CTDE and node-failure limits and that the sweep is unapproved.; No independent reviewer has previously passed this task. Prior rounds failed, and the latest checkpoints record 'not run' or 'inconclusive'. The handoff state is in_progress or blocked, not ready for review.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Worker update (run 20261010T132342Z, round 3)
- `central_online` inference now needs the link at test time (`no_ctl` in `run.py`); `ctde` stays decentralised, so the two now differ at inference as well as in training. New test `test_central_online_inference_needs_link_but_ctde_does_not`; 11 tests pass, ruff clean.
- Reran `python experiments/run.py --seeds 12 --episodes 150 --out agents/handoffs/T09/evidence` (about 5 min local CPU). Only `central_online`/split changed: +4.3 (0.9..7.9), because idling beats the split-trained `independent` learner. REPORT.md updated; the hash test passes.
- Still open: no actor/critic split; node_failure is still a `Down` stub; compute cap unapproved; no template run report; task card untouched (not in reserved paths). Not committed/pushed by worker.

## Supervisor checkpoint 2026-10-10T13:45:35Z

- Run: 20261010T132342Z
- Machine: A
- Task/branch: T09 / agent/A/20261010T132342Z/T09
- Base: 2368137d1885098c5b1012ed08e2a31484b4f8aa
- Round: 3
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["Slice 2 is not a real central-online vs CTDE comparison. ctde and central_online share one Learner with no actor/critic split. They differ only in whether training is gated by the link. The CTDE check 'does not falsely lose inference' therefore holds by construction. The REPORT says this is 'not a full CTDE algorithm'.", "node_failure is a Down stub. The drone stays in the sim world and just stands still. This is not a real node loss, so the failure-sweep evidence is weak, and the REPORT admits it.", "central_online/split shows +4.3 over independent. The REPORT calls this an artifact: with no controller reachable every drone idles, and idling beats the independent learner. The central_online mode is also edited in run.py after earlier evidence, so the central-vs-CTDE evidence is weak.", "Slice 3 has no approved compute cap on record. Only a 12-seed, 150-episode sweep exists. It is labelled preliminary and its resource costs are env steps, bytes and wall time only.", "Work is not committed or pushed. run.py, test_run.py, REPORT.md, LATEST.md and the evidence files (manifest.json, raw.jsonl, summary.json) are all modified in the working tree. The handoff itself says 'Not committed/pushed by worker'. The committed evidence hashes may not match the regenerated bundle. The contract requires a pushed handoff.", "The task card agents/tasks/T09 is untouched: status 'waiting', no assignment recorded, and all five acceptance boxes unchecked. No template-based run report exists.", "Acceptance evidence is thin. Seed-disjointness and matched budgets are asserted in code and tests, and rerun hashes are checked by one test. But the CTDE-inference check rests on a link-invariance test, and the report's avoidance of unsupported claims rests on prose. Prior independent reviews all failed, and the handoff state is still in_progress."]}
- Next issue: Slice 2 is not a real central-online vs CTDE comparison. ctde and central_online share one Learner with no actor/critic split. They differ only in whether training is gated by the link. The CTDE check 'does not falsely lose inference' therefore holds by construction. The REPORT says this is 'not a full CTDE algorithm'.; node_failure is a Down stub. The drone stays in the sim world and just stands still. This is not a real node loss, so the failure-sweep evidence is weak, and the REPORT admits it.; central_online/split shows +4.3 over independent. The REPORT calls this an artifact: with no controller reachable every drone idles, and idling beats the independent learner. The central_online mode is also edited in run.py after earlier evidence, so the central-vs-CTDE evidence is weak.; Slice 3 has no approved compute cap on record. Only a 12-seed, 150-episode sweep exists. It is labelled preliminary and its resource costs are env steps, bytes and wall time only.; Work is not committed or pushed. run.py, test_run.py, REPORT.md, LATEST.md and the evidence files (manifest.json, raw.jsonl, summary.json) are all modified in the working tree. The handoff itself says 'Not committed/pushed by worker'. The committed evidence hashes may not match the regenerated bundle. The contract requires a pushed handoff.; The task card agents/tasks/T09 is untouched: status 'waiting', no assignment recorded, and all five acceptance boxes unchecked. No template-based run report exists.; Acceptance evidence is thin. Seed-disjointness and matched budgets are asserted in code and tests, and rerun hashes are checked by one test. But the CTDE-inference check rests on a link-invariance test, and the report's avoidance of unsupported claims rests on prose. Prior independent reviews all failed, and the handoff state is still in_progress.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Worker update (run 20261010T132342Z, round 4)
- Added `idle` control mode (run.py) and test `test_idle_control_matches_central_online_without_controller`. Regenerated evidence bundle (12 seeds, 150 episodes): idle = +4.3 vs independent in connected/split/rejoin, identical to central_online/split, which evidences the artifact. REPORT.md updated.
- Not fixable inside reserved paths: real CTDE actor/critic (packages/learning), real node loss in the env, task card status/assignment, compute-cap approval, commit/push (supervisor). Needs integrator decision.

## Supervisor checkpoint 2026-10-10T13:52:23Z

- Run: 20261010T132342Z
- Machine: A
- Task/branch: T09 / agent/A/20261010T132342Z/T09
- Base: 2368137d1885098c5b1012ed08e2a31484b4f8aa
- Round: 4
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["Slice 2 is not a real central-online vs CTDE comparison. ctde and central_online share one Learner with no actor/critic split, so the check 'CTDE does not falsely lose inference' holds by construction. The report admits this is 'not a full CTDE algorithm'.", "node_failure is a Down stub. The drone stays in the sim world and stands still. This is not a real node loss, so the node-failure sweep is weak evidence (the report admits it).", "Slice 3 has no approved compute cap on record. Only a preliminary 12-seed, 150-episode sweep exists. Resource costs are env steps, bytes and wall time only.", "The central_online/split gain of +4.3 is an artifact. An idle control equals it exactly, and learners do not beat doing nothing. No superiority claim is supported, so the evidence for central vs CTDE is negative or inconclusive.", "Nothing from the latest rounds is committed or pushed. run.py, test_run.py, REPORT.md, LATEST.md and the evidence files (manifest.json, raw.jsonl, summary.json) are modified in the working tree. The contract requires a pushed handoff, and the committed bundle hashes may not match the regenerated bundle.", "The task card agents/tasks/T09 is untouched: status waiting, no assignment recorded, acceptance boxes unchecked. No template-based run report exists.", "The handoff state is still in_progress and says items need an integrator decision (actor/critic split, real node loss, compute-cap approval). The task is not ready for human PR review."]}
- Next issue: Slice 2 is not a real central-online vs CTDE comparison. ctde and central_online share one Learner with no actor/critic split, so the check 'CTDE does not falsely lose inference' holds by construction. The report admits this is 'not a full CTDE algorithm'.; node_failure is a Down stub. The drone stays in the sim world and stands still. This is not a real node loss, so the node-failure sweep is weak evidence (the report admits it).; Slice 3 has no approved compute cap on record. Only a preliminary 12-seed, 150-episode sweep exists. Resource costs are env steps, bytes and wall time only.; The central_online/split gain of +4.3 is an artifact. An idle control equals it exactly, and learners do not beat doing nothing. No superiority claim is supported, so the evidence for central vs CTDE is negative or inconclusive.; Nothing from the latest rounds is committed or pushed. run.py, test_run.py, REPORT.md, LATEST.md and the evidence files (manifest.json, raw.jsonl, summary.json) are modified in the working tree. The contract requires a pushed handoff, and the committed bundle hashes may not match the regenerated bundle.; The task card agents/tasks/T09 is untouched: status waiting, no assignment recorded, acceptance boxes unchecked. No template-based run report exists.; The handoff state is still in_progress and says items need an integrator decision (actor/critic split, real node loss, compute-cap approval). The task is not ready for human PR review.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Supervisor checkpoint 2026-10-10T13:53:23Z

- Run: 20261010T132342Z
- Machine: A
- Task/branch: T09 / agent/A/20261010T132342Z/T09
- Base: 2368137d1885098c5b1012ed08e2a31484b4f8aa
- Round: 5
- State: in_progress
- External check exit: 0
- Independent review: not run
- Next issue: Independent review unavailable or inconclusive
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Worker update (run 20261010T132342Z, round 5)
- Verified only: `pytest tests/experiments -q` -> 12 passed. No code changes this round; independent review was unavailable, so no new feedback to act on.
- Remaining gaps all need work outside reserved paths or integrator decisions: real CTDE actor/critic and real information sharing (packages/learning), real node loss (env), compute-cap approval for a larger sweep, commit/push.
- Note: manifest `rerun` uses `:` as PYTHONPATH separator (POSIX); on Windows use `;`.

## Supervisor checkpoint 2026-10-10T13:54:26Z

- Run: 20261010T132342Z
- Machine: A
- Task/branch: T09 / agent/A/20261010T132342Z/T09
- Base: 2368137d1885098c5b1012ed08e2a31484b4f8aa
- Round: 6
- State: blocked
- External check exit: 0
- Independent review: not run
- Next issue: Independent review unavailable or inconclusive
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Worker update (run 20261010T140025Z)
- Fixed `test_committed_evidence_hashes_match`: failed on this Windows checkout because `*.jsonl` has no eol=lf in `.gitattributes` (autocrlf gave CRLF bytes). Test now normalises CRLF to LF before hashing; evidence unchanged.
- Open (unchanged): real CTDE actor/critic, real node loss, compute-cap approval, template run report. Not committed/pushed.

## Supervisor checkpoint 2026-10-10T14:02:36Z

- Run: 20261010T140025Z
- Machine: A
- Task/branch: T09 / agent/A/20261010T140025Z/T09
- Base: 0ad50f5c5e6d368bcc1ffe4dc7ee324d973af05c
- Round: 1
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["The handoff says T09 is blocked or partial and needs integrator decisions. Those are a real CTDE actor/critic, real node loss and a compute-cap approval. The task is not ready for human PR review.", "The CTDE acceptance check ('CTDE does not falsely lose inference merely because central training is offline') holds only by construction. ctde and central_online share one Learner with no actor/critic split. The report says this is 'not a full CTDE algorithm', so slice 2 has no real central-online vs CTDE evidence.", "node_failure is a `Down` stub. The drone stays in the sim world and stands still, and no real node loss is simulated. The node-failure sweep is therefore weak evidence for slice 3.", "No compute cap is on record. Only a 12-seed, 150-episode sweep exists, and resource costs are env steps, bytes and wall time only. Slice 3 (sweeps within the 30 CPU-minute / 2 GB cap, with actual usage recorded) is not met.", "The evidence is mostly negative or inconclusive. No learner beats the `idle` control. The central_online split gain of +4.3 is an artifact that equals idle exactly, and no central vs CTDE claim is supported. This is honestly reported, but it means the task's outcome (a comparison of learning and resilience) is not delivered.", "The latest work is uncommitted. `agents/handoffs/T09/LATEST.md` and `tests/experiments/test_run.py` are modified in the working tree, and the handoff says 'Not committed/pushed'. The contract requires a pushed handoff.", "The test change in `test_committed_evidence_hashes_match` normalises CRLF to LF before hashing. This is a reasonable Windows fix, but the evidence bundle depends on eol handling. `.gitattributes` has no `eol=lf` for `*.jsonl`, so the committed bundle's hash check is fragile across checkouts.", "The task card `agents/tasks/T09.md` is untouched: status is 'waiting', no assignment is recorded, and the acceptance boxes are unchecked. `RUN-REPORT.md` is marked partial/blocked.", "The manifest `rerun` command uses `:` as the PYTHONPATH separator, which is POSIX-only and fails on Windows."]}
- Next issue: The handoff says T09 is blocked or partial and needs integrator decisions. Those are a real CTDE actor/critic, real node loss and a compute-cap approval. The task is not ready for human PR review.; The CTDE acceptance check ('CTDE does not falsely lose inference merely because central training is offline') holds only by construction. ctde and central_online share one Learner with no actor/critic split. The report says this is 'not a full CTDE algorithm', so slice 2 has no real central-online vs CTDE evidence.; node_failure is a `Down` stub. The drone stays in the sim world and stands still, and no real node loss is simulated. The node-failure sweep is therefore weak evidence for slice 3.; No compute cap is on record. Only a 12-seed, 150-episode sweep exists, and resource costs are env steps, bytes and wall time only. Slice 3 (sweeps within the 30 CPU-minute / 2 GB cap, with actual usage recorded) is not met.; The evidence is mostly negative or inconclusive. No learner beats the `idle` control. The central_online split gain of +4.3 is an artifact that equals idle exactly, and no central vs CTDE claim is supported. This is honestly reported, but it means the task's outcome (a comparison of learning and resilience) is not delivered.; The latest work is uncommitted. `agents/handoffs/T09/LATEST.md` and `tests/experiments/test_run.py` are modified in the working tree, and the handoff says 'Not committed/pushed'. The contract requires a pushed handoff.; The test change in `test_committed_evidence_hashes_match` normalises CRLF to LF before hashing. This is a reasonable Windows fix, but the evidence bundle depends on eol handling. `.gitattributes` has no `eol=lf` for `*.jsonl`, so the committed bundle's hash check is fragile across checkouts.; The task card `agents/tasks/T09.md` is untouched: status is 'waiting', no assignment is recorded, and the acceptance boxes are unchecked. `RUN-REPORT.md` is marked partial/blocked.; The manifest `rerun` command uses `:` as the PYTHONPATH separator, which is POSIX-only and fails on Windows.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Worker update (run 20261010T140025Z, round 2)
- `experiments/run.py`: manifest `rerun` now uses `os.pathsep` and `sys.executable` (was POSIX-only `:`); manifest records `cpu_s` and `evidence_bytes` and asserts the 30 CPU-min / 2 GB per-sweep cap. Committed evidence not regenerated (hashes unchanged). 12 tests pass, ruff clean.
- Still open, needs integrator: real CTDE actor/critic (packages/learning has a single DQN Learner), real node loss (sim has no agent removal; `Down` stub), compute-cap approval, `*.jsonl eol=lf` in .gitattributes (outside reserved paths; test normalises CRLF meanwhile), task card status. Not committed/pushed (supervisor owns).

## Supervisor checkpoint 2026-10-10T14:04:09Z

- Run: 20261010T140025Z
- Machine: A
- Task/branch: T09 / agent/A/20261010T140025Z/T09
- Base: 0ad50f5c5e6d368bcc1ffe4dc7ee324d973af05c
- Round: 2
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["information_only is still a stub that equals independent (the learner rejects all offers), so the information-only comparison in slice 1 has no real implementation.", "CTDE is not a real CTDE algorithm. ctde and central_online share one DQN Learner with no actor/critic split. The check 'CTDE does not falsely lose inference' holds only by construction, so slice 2 has no real central-online vs CTDE evidence. REPORT.md says as much.", "node_failure uses a `Down` stub. The drone stays in the sim world and stands still, so the node-failure sweep is weak evidence for slice 3.", "No local compute cap is on record, and the only sweep is 12 seeds with 150 episodes. The new CPU and bytes assertion in run.py is not exercised by committed evidence, because the evidence bundle was not regenerated.", "Latest work is uncommitted and unpushed. experiments/run.py and agents/handoffs/T09/LATEST.md are modified in the working tree (git status), and the handoff says 'Not committed/pushed'. The contract requires a pushed handoff.", "The manifest `rerun` command still hardcodes POSIX shell syntax (`PYTHONPATH=... python`) even though it now uses os.pathsep, so it will not run in PowerShell or cmd. The code comment admits this.", "The task card agents/tasks/T09.md is stale: status 'waiting', no assignment recorded, acceptance boxes unchecked. The handoff states the task is blocked and needs integrator decisions (real CTDE, real node loss, compute-cap approval, eol=lf for jsonl). The evidence is mostly negative or inconclusive, so the task outcome (a learning vs resilience comparison) is not delivered and it is not ready for human PR review."]}
- Next issue: information_only is still a stub that equals independent (the learner rejects all offers), so the information-only comparison in slice 1 has no real implementation.; CTDE is not a real CTDE algorithm. ctde and central_online share one DQN Learner with no actor/critic split. The check 'CTDE does not falsely lose inference' holds only by construction, so slice 2 has no real central-online vs CTDE evidence. REPORT.md says as much.; node_failure uses a `Down` stub. The drone stays in the sim world and stands still, so the node-failure sweep is weak evidence for slice 3.; No local compute cap is on record, and the only sweep is 12 seeds with 150 episodes. The new CPU and bytes assertion in run.py is not exercised by committed evidence, because the evidence bundle was not regenerated.; Latest work is uncommitted and unpushed. experiments/run.py and agents/handoffs/T09/LATEST.md are modified in the working tree (git status), and the handoff says 'Not committed/pushed'. The contract requires a pushed handoff.; The manifest `rerun` command still hardcodes POSIX shell syntax (`PYTHONPATH=... python`) even though it now uses os.pathsep, so it will not run in PowerShell or cmd. The code comment admits this.; The task card agents/tasks/T09.md is stale: status 'waiting', no assignment recorded, acceptance boxes unchecked. The handoff states the task is blocked and needs integrator decisions (real CTDE, real node loss, compute-cap approval, eol=lf for jsonl). The evidence is mostly negative or inconclusive, so the task outcome (a learning vs resilience comparison) is not delivered and it is not ready for human PR review.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Worker A update (run 20261010T140025Z)

- Changed `experiments/run.py`: manifest/summary `rerun` is now `{env, argv}` instead of a POSIX shell string, so it is shell-neutral. `pytest tests/experiments` -> 12 passed.
- Correction to review: `information_only` is not a stub in the current tree. `share_obs` copies raw transitions between nodes and counts bytes. It is separate from `independent`.
- Not done (needs integrator decisions / out of reserved paths): real CTDE actor/critic (needs `packages/learning`), real node loss in the sim, compute-cap approval, task card status update, regenerating the evidence bundle (the `rerun` field changes the summary hash). Not committed or pushed by the worker.

## Supervisor checkpoint 2026-10-10T14:05:03Z

- Run: 20261010T140025Z
- Machine: A
- Task/branch: T09 / agent/A/20261010T140025Z/T09
- Base: 0ad50f5c5e6d368bcc1ffe4dc7ee324d973af05c
- Round: 3
- State: blocked
- External check exit: not run
- Independent review: not run
- Next issue: Worker permission, exit 0; inspect local log
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Worker A update (run 20261010T140742Z)
- No code change. Verified `pytest tests/experiments tests/learning` -> 27 passed on this branch (clean tree at start).
- `packages/learning` is now in the reserved paths, so a real CTDE actor/critic is possible, but it is a design-sized change (joint-obs critic plus per-node actors in numpy). It was not started and needs an explicit decision on its scope.
- Still open: real CTDE, real node loss (sim is outside reserved paths), compute-cap approval, task card status, `*.jsonl eol=lf`, regenerating evidence (rerun field changed the summary hash). Not committed or pushed by the worker.

## Supervisor checkpoint 2026-10-10T14:09:19Z

- Run: 20261010T140742Z
- Machine: A
- Task/branch: T09 / agent/A/20261010T140742Z/T09
- Base: 5d1e103e7021fd2f0d23c157eb9f0b9dda8f5e0f
- Round: 1
- State: in_progress
- External check exit: 0
- Independent review: not run
- Next issue: Independent review unavailable or inconclusive
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Worker A update (run 20261010T140742Z, round 2)
- Regenerated `agents/handoffs/T09/evidence/` (12 seeds x 150 episodes, ~3.7 min wall, local CPU) so the manifest/summary hashes match the shell-neutral `rerun` field. Command: `PYTHONPATH="packages/learning;packages/sim" .venv/Scripts/python experiments/run.py --seeds 12 --episodes 150 --out agents/handoffs/T09/evidence` (use `:` as separator on POSIX).
- Results unchanged: PRELIMINARY n=12; rule beats independent (+14.3, CI excludes 0); no learner beats `idle`; no central/CTDE superiority claim supported.
- Still open: real CTDE, real node loss, cap approval, task card, eol=lf. Not committed or pushed.

## Supervisor checkpoint 2026-10-10T14:14:19Z

- Run: 20261010T140742Z
- Machine: A
- Task/branch: T09 / agent/A/20261010T140742Z/T09
- Base: 5d1e103e7021fd2f0d23c157eb9f0b9dda8f5e0f
- Round: 2
- State: blocked
- External check exit: 0
- Independent review: not run
- Next issue: Independent review unavailable or inconclusive
- Resume: fetch this branch, inspect latest commit and continue the task card.
