# Last autonomous run: retrospective

Written 2026-10-10 (UTC) by the bootstrap agent, **before** any control-plane change. Scope: the A/B overnight run of 2026-10-10 (roughly 05:45Z-21:00Z) plus the interactive bootstrap that preceded it (00:21-05:30 local).

Directory note: the prompt names `.agents/`. The repository already had an established `agents/` tree referenced by `CLAUDE.md`, `AGENTS.md`, CI (`tools/check_foundation.py`) and the old drivers. Creating `.agents/` would make two sources of truth, so everything lives in `agents/` ([ADR-0006](../decisions/0006-keep-agents-directory.md)).

## Evidence base and its limits

Inspected: all 275 commits on `main` (72 merges), 44 remote branches, 6 PRs, 34 run reports in `agents/runs/`, all `agents/handoffs/*/LATEST.md`, `agents/issues/*`, the `agent-coordination` branch (`active.json`, 19 mailbox messages), `tools/agents/*.py` and their tests, both CI workflows, and the 100 most recent of 445 GitHub Actions runs.

**Not available** (stay `UNKNOWN`, do not infer): the machines' `.agent-runtime/` logs (stdout/stderr of workers, watcher logs, lock/PID files, `STOP` files); job-level CI logs; token/quota state; any record of how many times a human typed a prompt. The latter is estimated only from commit authorship and handoff text, and is labeled as such.

## Executive summary

In about 16 wall-clock hours, two machines produced 13 task cards (T01-T13), a working 2D simulator, transport, API, dashboard, learners, a 3D adapter proof, storage and a packaged deployment stack. That is real output. The *process* around it was inefficient and fragile:

- 34 run reports were written; **8 contain no task at all**, 28 task attempts ended `blocked` and only 9 reached `review`. Reported cost $22.56 (API-equivalent) over 112 coding rounds.
- The most common block reason (16 of 28) was **"Independent review unavailable or inconclusive"**: the verification step itself was unreliable, not the code.
- Work was repeated: T06 was attempted in 10 run slots (8 blocked) and ended with six superseded alternative branches recorded as "integrated" by `-s ours` merges that import no content. T12 was blocked 9 times and T09 5 times on the *same* unresolved integrator decisions.
- 116 of 275 commits are "overnight checkpoint N" commits and 16 are "Driver: next overnight plan"; 29 are "Merge commit ... into agent/..." sync merges. Roughly half of all history is orchestration traffic, not product change.
- CI had no concurrency control and no path filters. `Foundation checks` ran on **every push to every branch** (70 of the last 100 runs) while `ci` ran only 19 times.
- A task (T09) was recorded `done` on the board while its own report says "PRELIMINARY", `information_only` is a stub equal to `independent`, and CTDE is not a real CTDE.

The system optimised for activity (rounds, checkpoints, branches, reports) rather than verified progress, and then added infrastructure (mailbox, watchers, driver, watchdog) to patch the resulting coordination gaps.

## What worked (preserve)

| Mechanism | Evidence |
|---|---|
| Handoff Markdown per task, pushed with the work | Every task has `agents/handoffs/<T>/LATEST.md`; resumed rounds quote previous attempts (T06, T09, T12). Recovery from repo alone was demonstrably possible. |
| Fresh `claude -p` session per bounded slice | `night.py` design; no multi-hour conversations to lose. |
| Reserved-path check after each slice | Caught unreserved wheel files in T03 (run 054510Z) and out-of-scope edits. |
| Independent reviewer *findings* | The reviewer correctly caught missing browser smoke (T06), duck-typed PettingZoo (T03), non-CTDE CTDE (T09), diagnosis-after-fix (T13). Findings were right; the *transport of the verdict* was flaky. |
| Single command `scripts/check.sh` as the gate | Same entrypoint locally, in CI and in the container build. |
| Recording what was NOT verified | `agents/issues/docker-runtime-tests-20261010.md`, T10 "Known gaps". This honesty is why the failure analysis here is possible. |
| ADR/issue files with exact repro | Docker `--no-build` root cause was found by reading compose + CI, then confirmed by PR #5 CI (145 passed). |
| Parallel verifier fan-out on T10 | 4 workers + 4 independent verifiers found 3 real FAILs fixed in `204f899`. The pattern (worker/verifier split) is the right one. |
| OS file locks (`process_lock`) rather than lock files | Documented in driver-recovery.md; survives crashes. |

## What failed

### F1. Verification verdict channel unreliable
16 of 28 blocked outcomes: "Independent review unavailable or inconclusive". Seen in T04, T06, T09, T12. T12's handoff (line 381) says "The review verdict is 'unavailable', so there are no findings to fix", and the task re-ran identical tests for rounds. **Cause:** the verdict was a free-form model output parsed from a second `claude -p` call (`REVIEW_SCHEMA` in `night.py`), with no deterministic fallback; any parse failure or turn limit counts as no progress. After "two rounds without measurable progress" the task blocked even when the code was fine.

### F2. Blocked on decisions that no agent could make, repeatedly
T09: "this is the fourth run blocked on that decision" (CTDE actor/critic scope, compute cap). T12: blocked on `Pose.z` pinned to 0 (ADR-0002), takeoff/land contract commands, a CI job, task-card sync. Each rerun re-read context, re-ran the same tests and re-blocked. **Cause:** no `blocked_by` record that the scheduler could read; the planner (`driver.py`) re-dispatched blocked tasks until `MAX_ATTEMPTS = 6`.

### F3. Duplicate / divergent implementations
T06 produced at least six independent implementations (`agent/B/T06/carry1`, `carry2`, `carryover`, `20261010T061419Z/T06`, `...063026Z/T06`, `...132342Z/T06`), then `reconciled-20261010`. Main kept the reconciled one; the six others were merged with `-s ours` ("content NOT imported", commits 05706f0, f3e4cbd, 46bd801) purely so cleanup could delete them. **Cause:** a "carry" branch naming collision, no canonical owner/branch per task, and every new run starting from `main` rather than from the task's own last good commit.

### F4. Local environment differences consumed rounds
Windows CRLF broke `ruff format`, generated TypeScript, and evidence hashes (T02, T09, T12 handoffs); WSL `bash` shim was picked over Git Bash (T06); `PYTHONPATH` separator differences (T09); missing Docker on B (T08 blocked with 0 rounds) and in the authoring sandbox. **Cause:** no environment contract; workers discovered each quirk independently.

### F5. Worker blocked by permission classifier
"Worker permission, exit 0; inspect local log" ended 4 slices (T06, T09, T12, T13). T12 handoff line 93: `git mv` was denied, so it left a misnamed directory. **Cause:** unattended permission policy not matched to what task cards require; the failure shape (exit 0, no work) is indistinguishable from success without a log nobody committed.

### F6. Premature "done"
- T09 on BOARD as `done (7f32388)`; `experiments/REPORT.md` says PRELIMINARY, node failure is a `Down` stub, CTDE shares one `Learner`.
- T13 `done` while the diagnosis was never captured from a live API process (board says so) and the sim2d browser smoke is not part of `scripts/check.sh`.
- Acceptance boxes in T02-T09 and T12 cards are still unticked (INTEGRATION handoff, "Still open").
- T06 passed independent review, merged, then failed its own browser smoke on the first real run (issue file, 14:43Z).
**Cause:** "done" was a free-text board cell edited by hand; no executable acceptance, no verifier.

### F7. CI
- `Foundation checks` (docs-only validation) triggers on `push` for all branches and `pull_request`: 70+6 of last 100 runs, though it takes seconds. `ci` `bootstrap` runs the full suite incl. Docker; no `concurrency:`, no `paths:`, no path-aware split. 4 of the 6 `ci` PR runs in the sample failed.
- Docker runtime tests used `--no-build`; they errored on first CI (images missing) and were skipped/unskipped/fixed over four commits.
- `check.sh` mixes cheap lint with Docker tests, so any machine without a daemon fails the whole gate (INTEGRATION handoff: "Exit 0 was only reached earlier with a skip shim").
- Three leftover Claude worktree gitlinks (mode 160000) broke the checkout cleanup step.
- Dependabot "Graph Update" runs (4) triggered on lockfile churn.

### F8. History noise
116 checkpoint commits, 16 plan commits, 29 sync merges, 44 live branches (13 `agent/B/mail-*`). Reviewers had to read this to find signal.

## Human intervention points

Estimated from commit authors (Tien Vu 166, Jacob Lee 81, Claude 28 commits) and handoff text; exact prompt counts are UNKNOWN.

| # | Where | Kind |
|---|---|---|
| H1 | Initial T01/T02 interactive run, B's start of T04 | manual assignment (bootstrap exception) |
| H2 | PR #1-#4 merges | routine approval |
| H3 | Run launches (night.py, driver, watchdog) on each machine | restart/launch; `driver-recovery.md` exists because the loop exited |
| H4 | `Driver: next overnight plan` x16 | manual state movement between agents (automated later, still plan-by-regex) |
| H5 | T06 `-s ours` records, branch cleanup | integration repair |
| H6 | Windows fixes (CRLF, Git Bash, `.gitattributes`) | environment fix by human/integrator |
| H7 | T12 `git mv` denied; T09 compute cap; T12 Pose.z/ADR | ambiguity / permission resolution never delegated |
| H8 | Docker daemon install on B; T10 credentials (Vultr/TigerData) | resource a human must supply |
| H9 | PR #5/#6 integration, issue triage, "autonomous directive" | integration + inspection |
| H10 | Reading 34 run reports to learn that most were empty or blocked | status inspection |

## Coordination failures

- **Stale state:** `BOARD.md` regex-parsed by `driver.py` (`board()`, `load()`); every integration needed a human-style edit and the board lagged reality (T10 line refreshed manually).
- **Two ledgers:** `agent-coordination` branch `active.json` plus `BOARD.md` plus per-task cards plus handoffs, with no stated precedence.
- **Branch divergence:** `agent-coordination` is a divergent tree that "must never be merged"; `agent/B/mail-*` branches (8) point at old main commits; `agent/A/*/review-fixes` x4.
- **Unclear ownership:** shared files (`pyproject.toml`, `.gitattributes`, `scripts/check.sh`, `tests/web`) needed integrator action mid-task; workers blocked rather than request-and-continue.
- **Waiting unnecessarily:** B waits up to `B_WAIT_MIN = 90` minutes for A (driver.py); idle watcher polls every 180 s.
- **Lost handoffs:** a T09 "uncommitted work" note (handoff line 488) and the `T13/prefix_stream_diag.py` helper committed under `handoffs/`.

## Verification failures

See F6. Additionally: Docker-dependent tests were unverified for hours (T10 new tests "UNVERIFIED until CI runs them"); the reviewer could not rerun browser smoke (T13 line 136); T08 Grafana render and production TigerData never ran; expensive CI (full suite + container build) re-ran per intermediate push.

## Infrastructure inventory and classification

Reliability classes: RELIABLE, CONDITIONALLY_RELIABLE, UNRELIABLE, UNSUPPORTED. Action classes: KEEP, SIMPLIFY, REPLACE, REMOVE, UNKNOWN.

| Mechanism | Reliability | Action | Why |
|---|---|---|---|
| `tools/agents/mail_watch.py` (poll `agent-coordination` every 30 s; "its exit is the notification") | **UNSUPPORTED** in cloud/headless sessions; **UNRELIABLE** locally (background task lifetime tied to the session; dead on context exit; not referenced by any test or doc) | **REMOVE** (done in this bootstrap) | Substitutes for knowing dependency state. A committed ledger read at the start of each slice gives the same information with no process. |
| `agent-coordination` mailbox (`mailbox/to-A`, `to-B`, 19 messages, 8 `agent/B/mail-*` branches) | RELIABLE as data, but needs a watcher to be timely | **REPLACE** with `TASKS.yaml` + `blocked_by` + handoffs on the task branch | Messages were mostly "status", "re: decision", "push branch": all expressible as task state or an ADR. Replacement implemented; branch left in place (read-only history) until human-approved deletion. |
| `tools/agents/idle_watch.py` (infinite loop around `night.py`, `tasklist` PID check) | **UNRELIABLE** (Windows-only PID test, never exits except STOP, never run in its tracked form per its own handoff: "this tracked version ... not yet run") | **REMOVE** (done) | Idle polling to wait for assignments; with a ledger the controller says `next` or `nothing runnable`. |
| `tools/agents/watchdog.py` (restart driver on exit) | CONDITIONALLY_RELIABLE (needs an open terminal on an always-on, awake machine) | **SIMPLIFY**: keep, mark optional, scheduled for removal with driver (T20 in [TASKS.yaml](../TASKS.yaml)) | Treats a symptom (driver exits) that exists because the driver is a long loop. |
| `tools/agents/driver.py` (never-exiting planner, sleeps 60-300 s, auto-merges `review` branches behind gate, regex-parses `BOARD.md`, writes `Driver: next overnight plan` commits) | **CONDITIONALLY_RELIABLE** locally; **UNSUPPORTED** in cloud sessions | **REPLACE** (planned, T20) | Planning from a regex over a Markdown table is the root of F2/F3/F6. Auto-merge on a machine-local gate duplicates the integrator role. Not deleted now: `night.py` still depends on its published plan format. |
| `tools/agents/night.py` (fresh session per slice, path guard, check gate, read-only reviewer) | CONDITIONALLY_RELIABLE (local always-on machine; `claude -p` flags) | **SIMPLIFY** (T20): keep slice launcher and path guard; read `TASKS.yaml` instead of fixed JSON plan; make verifier verdict file-based | The slice model is sound. The review transport (F1) and plan format are not. |
| `tools/agents/cleanup_branches.py` | RELIABLE (preview default, lease deletion) | **KEEP** | Remote branch hygiene is still required; fewer branches will reduce its load. |
| `agents/runs/*.md` per-machine reports (34) | RELIABLE | **SIMPLIFY** | Machine-readable `run` summaries (schema added) replace prose; 8 reports were empty. |
| 15-minute/20-minute checkpoint commits ("overnight checkpoint N", 116 commits) | RELIABLE | **SIMPLIFY** | Keep the handoff file; squash/limit commits to milestones and failures. |
| Reviewer = second `claude -p` with JSON schema | **UNRELIABLE** as sole verdict | **REPLACE** with deterministic acceptance commands first, model review second ([PROTOCOL](../PROTOCOL.md)) | F1. |
| `scripts/check.sh` as the single gate | RELIABLE | **SIMPLIFY**: split into fast / integration / full | F7. |
| `Foundation checks` workflow | RELIABLE | **SIMPLIFY**: path-filter + concurrency, merge into one workflow | F7. |

Anything depending on a process outliving a Claude session (mail_watch, idle_watch, in-session loops, "background tasks whose exit is the notification") is unsupported by the runtime. No evidence of a mid-run hard block was recoverable here, because the watcher logs are on A/B; the *design* is unsupported regardless of whether it failed on this night. Rows for `mail_watch` and `idle_watch` therefore carry `UNKNOWN` observed-failure status and a design-level `UNSUPPORTED/UNRELIABLE` class.

## Root causes (symptoms separated)

| Symptom | Root cause | Structural fix (not a band-aid) |
|---|---|---|
| Mailbox, mail watcher, idle watcher, B waiting on A | No canonical machine-readable task state with dependencies, owner and blocker; coordination went through prose | `TASKS.yaml` ledger committed on the integration branch; controller prints runnable tasks |
| Tasks re-dispatched and re-blocked (T09 x5, T12 x9) | Blockers were prose in handoffs; planner could not see them | `blocked_by` + `retry_policy` + same-signature cutoff; `BLOCKED` is terminal until a named dependency clears |
| "Review unavailable" blocking good work | Single model-output verdict | Acceptance = executable commands; verifier writes a schema'd verdict file; absence = verifier infra failure, not task failure |
| Six T06 variants | Every run restarted from main; no canonical task branch | One branch per task, `last_good_commit` in ledger, resume-from-branch rule |
| False `done` | Hand-edited board cell | Only `controller.py complete` after recorded verifier PASS and integrator merge commit |
| CRLF/Git-Bash/PYTHONPATH churn | No environment contract | `.gitattributes` fixed already; PROTOCOL lists environment rules; Makefile targets are POSIX; one runtime per role |
| Excess CI | No concurrency, path filters or tiering | Tiered make targets, concurrency cancel, path filters |
| 116 checkpoint + 29 sync commits | Progress recorded by commit rather than by state file | Handoff update is required; commit only at milestones |

## Lessons

Distilled into [`agents/LESSONS.md`](../LESSONS.md) (L-001 ... L-012).

## Recommended rule changes (adopted in this bootstrap unless noted)

1. `agents/TASKS.yaml` is the single ledger; `BOARD.md` is a derived summary. (ADR-0003, adopted)
2. No process may be required to outlive a Claude session. Mark such mechanisms UNSUPPORTED. (ADR-0004, adopted; `mail_watch.py`, `idle_watch.py` removed)
3. Done = acceptance commands pass + verifier PASS + integrator merge commit. Workers stop at `REVIEW`. (PROTOCOL, adopted)
4. Retry budgets and same-signature cutoff produce `BLOCKED` with a report. (PROTOCOL + controller, adopted)
5. CI: concurrency cancel, path filters, tiered checks, no deploy on agent branches. (ADR-0005, adopted)
6. Reviewer role evaluates the process every wave. (PROTOCOL; first review is this document)
7. **Needs human decision / not done now:** deleting the `agent-coordination` branch and the `agent/B/mail-*` branches; deleting `driver.py`/`night.py`/`watchdog.py` (T20); the T09 CTDE scope and compute cap; `Pose.z` contract change (T18).

## Run summary for the previous night (using the new run schema)

```yaml
run:
  id: overnight-20261010
  started_at: "2026-10-10T05:45:10Z"
  completed_at: "2026-10-10T21:00:31Z"
tasks:
  completed: 9        # T01-T05, T07, T08(review), T12, T13 per board; T06/T09 reopened as review
  blocked: 28         # attempts that ended blocked (not distinct tasks)
  failed: 0
  retried: 112        # coding rounds total
verification:
  passes: 9           # runs reaching review
  failures: 28
integration:
  conflicts: UNKNOWN
  failed_merges: UNKNOWN
  superseded_branches_recorded: 6
ci:
  runs: 445           # total; 100 sampled
  cancelled: 0        # no concurrency control existed
  failures: ">=4 of 6 sampled ci PR runs"
  approximate_total_minutes: UNKNOWN
autonomy:
  human_interventions: ">=10 (see table)"
  agent_restarts: UNKNOWN
  unsupported_automation_events: UNKNOWN
regressions:
  discovered: 3       # T06 stopped-run stream; Docker --no-build; T10 verifier fails x3
  repaired: 3
```

Autonomy score (operational, not a KPI): verified tasks ~9, plus repaired regressions 3, minus >=10 human interventions, minus ~5 repeated identical blocks (T09/T12/T06), minus 6 abandoned T06 variants, minus an unquantified CI surplus. Net: the night produced output but needed more human inference than its volume suggests.

## Addendum: operator decision after the bootstrap

The operator asked that agents be able to start the scheduler and `night.py` themselves. The retrospective's conclusion stands (no mechanism may *depend* on a process outliving a session), so this was implemented as `agents/launch.py` (ADR-0007): a one-shot `tick` that any scheduler or routine can call, and a detached `start` loop that is classified CONDITIONALLY_RELIABLE and reports STALLED/DEAD. Starting a runner is allowed to agents; correctness of the claim is not left to timing because ledger writes serialize through Git.
