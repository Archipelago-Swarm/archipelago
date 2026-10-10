# Operational lessons

Durable rules learned from real runs. Read before every task. Add a lesson only when a failure recurred or cost real time; give the evidence pointer. Do not log chronology here (use `agents/reports/`).

## L-001 Task state is a committed file, not a message
Do not build mailboxes, branch messaging or watchers to learn what another task is doing. Read `agents/TASKS.yaml` (dependencies, `blocked_by`, owner). Evidence: 19 mailbox messages, `mail_watch.py`; retrospective F2/F8.

## L-002 Nothing may depend on a process outliving the session
Persistent watchers, "background task whose exit is the notification", in-session loops and sleeping daemons are UNSUPPORTED. A mechanism that needs one must say so in PROTOCOL.md and name the human or scheduler that starts it. Evidence: `idle_watch.py` (Windows-only PID test, never run in tracked form).

## L-003 Implementation is not completion
A worker ends at `REVIEW`, never `COMPLETE`. Completion needs acceptance commands passing, a verifier PASS on the same commit and an integrator merge commit. Evidence: T09 "done" with stubs; T06 failing its own smoke after merge.

## L-004 A verifier with no verdict has not failed the task
Missing or invalid `VERIFICATION.yaml` is verifier-infrastructure failure: retry the verifier, do not count it against the worker and do not block the task. Evidence: 16 of 28 blocks were "review unavailable".

## L-005 A blocker must be machine-readable and name who can clear it
`blocked_by` lists task ids or `human:`/`env:` entries. The orchestrator does not re-dispatch a task whose `blocked_by` is non-empty. Evidence: T09 blocked four runs on the same decision, T12 nine.

## L-006 Decide reversible things; escalate only irreversible or public ones
If an agent cannot proceed because a reversible choice is unmade, make it, record it in the handoff/ADR and continue. Escalate only public contract changes, secrets, paid infrastructure, destructive actions. Evidence: T09 compute cap, T12 file move.

## L-007 One branch per task, resume from it
`agent/<TASK-ID>-<slug>`. A new session fetches that branch and `last_good_commit`; it never restarts from main and never creates a second "carry" variant. Evidence: six T06 variants merged with `-s ours`.

## L-008 Do not claim what the gate did not run
Record exact commands and what was not run (Docker, real DB, browser, credentials). A claim without a command in the handoff is an assumption. Evidence: `agents/issues/docker-runtime-tests-20261010.md`.

## L-009 Batch CI; cheap checks locally, expensive in CI once
Run `make check-fast` constantly, `make check-integration` before REVIEW, `make check-full` only for release or scheduled runs. Intermediate commits on agent branches must not trigger the full suite or any deploy. Evidence: 445 CI runs, no concurrency control.

## L-010 Fix environment drift once, in the repo
Line endings (`.gitattributes`), shells (use `bash`, POSIX paths), Docker availability (tiered checks) are repo facts, not per-worker discoveries. Evidence: CRLF failures in T02, T09, T12; WSL bash vs Git Bash.

## L-011 Three identical failures means the plan or the rule is wrong
Same failure signature twice -> BLOCKED with a blocker report. Ask whether the rule, the task size or the dependency is wrong before another attempt. Evidence: T12, T09 repeated rounds.

## L-012 Self-review the diff before asking for verification
No TODO/FIXME, debug prints, test bypasses, stubs presented as features, unrelated edits, secrets. Evidence: T09 stub baselines, T12 misnamed directory.
