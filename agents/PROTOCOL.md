# Agent protocol

Detailed procedure. `CLAUDE.md` is the short contract; `agents/CONTRACT.md` remains the authority on scope, secrets, cost and git safety. Where this file and CONTRACT.md disagree on task states or completion, this file wins (ADR-0003).

Status legend used below: **[implemented]** enforced by `agents/controller.py` or CI; **[convention]** documented rule agents must follow, not machine-enforced; **[future]** not built; **[unsupported]** the runtime cannot provide it.

## 1. Single source of truth

| Question | Answer lives in |
|---|---|
| What work exists, its state, deps, blockers, owner | `agents/TASKS.yaml` (edit only through `agents/controller.py`) |
| Who may touch which paths | `agents/OWNERSHIP.yaml` and each task's `owned_paths` |
| Where a task stands in detail | `agents/handoffs/<ID>/LATEST.md` on the task branch |
| What was tried and learned about the process | `agents/LESSONS.md`, `agents/decisions/`, `agents/reports/` |
| Interfaces | `packages/contracts/` (executable) and `agents/architecture/interfaces.md` |

`agents/tasks/BOARD.md` and the cards `agents/tasks/T01-T13.md` are human-readable background (tasks T14 and later have no card; the ledger entry is the whole definition); they do not decide state. Chat history is never required.

## 2. Task lifecycle [implemented]

```
QUEUED -> CLAIMED -> ACTIVE -> REVIEW -> INTEGRATION -> COMPLETE
              \        |  \       |  \         |
               \       |   \      |   +--------+--> ACTIVE (verifier or integration failure)
                +------+----+-----+------------> BLOCKED -> QUEUED (unblock)
                       +------------------------> FAILED (terminal, abandoned on purpose)
```

- `QUEUED` runnable when every dependency is `COMPLETE`, `blocked_by` is empty and no in-flight task owns overlapping paths. `python agents/controller.py next`.
- `CLAIMED` the orchestrator assigned owner, machine and branch. The claim is a ledger commit on the integration branch; a second claimant's push is rejected as non-fast-forward, which is the only lock needed.
- `ACTIVE` a worker is implementing. A handoff file exists.
- `REVIEW` implementation done, local acceptance commands pass, `last_good_commit` recorded. Waiting for the verifier.
- `INTEGRATION` verifier PASS recorded for the same commit. Waiting for the integrator.
- `COMPLETE` integrator merged and ran `controller.py complete --commit <merge sha>`. Terminal.
- `BLOCKED` retry budget exhausted or an external need exists. Requires `BLOCKER.md`. `unblock` refuses while any `human:*` blocker is open unless `--resolved "<what was done>"` is given, and after 3 unblock cycles the next `unblock` moves the task to `FAILED`. `requeue` clears owner, machine and branch so the task can be claimed again. `FAILED` terminal.

Only `COMPLETE` satisfies another task's dependency.

## 3. Roles

Coding agents are Claude sessions. They are not the simulated drone nodes in the product.

| Role | Does | Must not |
|---|---|---|
| Orchestrator (machine A) | reads roadmap, LESSONS, ledger, OWNERSHIP; `next`, `claim`; dispatches verification, repair, integration; triggers process review | write feature code; claim overlapping paths |
| Worker | satisfies acceptance of one claimed task on its branch (section 4) | edit outside `owned_paths`; mark REVIEW without passing commands; touch another branch |
| Verifier (machine B) | independently runs acceptance commands and reviews the diff; writes `VERIFICATION.yaml` | modify implementation code |
| Integrator (machine A) | merges verified branches, resolves conflicts, runs `check-integration` on the merged head, calls `complete` or `integrate-fail` | integrate unverified work; let B also integrate |
| Reviewer (machine B) | process review (section 8); proposes KEEP/SIMPLIFY/REMOVE/REPLACE/NEW RULE | add infrastructure when deleting some would do |

Machine roles are in `OWNERSHIP.yaml`. The controller enforces [implemented]: the integrator role for `complete` and `integrate-fail`; `--by` equal to the task owner for `start`, `review`, `record-failure`, `block` (and for `requeue`/`unblock`, or a machine holding the integrator role); for `verify`, `--machine` holding the verifier role, a machine other than the one that ran the task, and a verdict verifier on that machine. Other role boundaries are [convention].

## 4. Worker loop [convention; steps 7, 12, 13 call the controller]

1. Read the task in `TASKS.yaml`, `LESSONS.md`, the contracts it lists, and the latest handoff on the task branch.
2. Fetch and check out the task branch (create it from `origin/main` only on first claim). Never start over from main on resume.
3. Inspect the current implementation. Write or update the handoff with plan and acceptance commands (`controller.py start <ID> --by <owner>`).
4. Implement the smallest useful change. Stay inside `owned_paths`; ask the integrator through the ledger (`blocked_by: T..`) for shared files.
5. Run narrow validation (the fast tier). On failure: diagnose, patch, retest.
6. Each failed attempt: `controller.py record-failure <ID> --by <owner> --kind ... --signature "<stable short string>"`. The same root cause three times (`same_failure_signature`, default 3, never below 3; matches CONTRACT.md), or a kind budget exhausted, moves the task to BLOCKED and you must write `BLOCKER.md`. Signatures are normalized (`file.py:12-30`, `#L4`, `line 9` lose their line numbers) so one root cause counts once. Defaults: test 5, build 3, integration 3, same signature 3.
7. When narrow validation passes, run broader tests, then `make check-integration` (or the commands in `acceptance.commands`).
8. Self-review the diff: no TODO/FIXME, debug prints, dead code, duplicate implementation, unhandled errors, test bypasses, hardcoded values, secrets, unnecessary dependencies, scope creep, missing tests, stubs presented as features. Tests passing does not imply done.
9. Update the handoff (section 6), commit, push the task branch.
10. `controller.py review <ID> --by <owner> --commit <sha>`. Stop. Do not mark anything COMPLETE or merged.

Do not stop after implementation while meaningful validation remains. Stop earlier only for BLOCKED, context exhaustion (write CHECKPOINT first) or the session budget.

## 5. Acceptance criteria [implemented schema; convention for content]

Each task has `acceptance.commands` (command, expected exit code, tier `fast|integration|full`, optional `needs: docker|network|credentials`) and `acceptance.assertions` (observable facts the verifier checks by test or inspection). Prefer commands over assertions. A command that needs something absent in the environment is reported `not run: needs docker` in the verdict and is never counted as a pass. For `needs: docker` commands, CI is an acceptable verifier environment.

## 6. Handoff and checkpoint [convention]

Handoff `agents/handoffs/<ID>/LATEST.md`, template `agents/templates/handoff.md`. Required content: status, owner/machine, branch, base commit, last good commit, objective, acceptance criteria and which pass, completed work, current failure (command and error), attempts made, decisions, files modified, dependencies, next actions, warnings. Update after milestones, before risky changes, before stopping, before context exhaustion, when blocked.

Long tasks also keep `agents/runtime/<ID>/CHECKPOINT.md` (committed on the task branch): objective, decisions, commit, files, tests passing/failing, attempts, blockers, next steps. Nothing else. A fresh session must be able to continue from the handoff plus checkpoint alone.

Blocker report `agents/handoffs/<ID>/BLOCKER.md`, sections (validated by the controller): `Failing command`, `Error`, `Hypotheses attempted`, `Files changed`, `Last known-good commit`, `Reproduction`, `Recommended next action`. Template: `agents/templates/blocker.md`. "Could not get it working" is not a report.

Failure artifacts go to `artifacts/failures/<ID>/` (seed, stdout, stderr, `reproduction.md`) and are referenced from `artifacts`. The directory is git-ignored; commit a small reproduction under the task handoff directory when the failure must survive. Flow: failure -> artifact -> repair attempt -> reproduction passes -> broader tier reruns.

## 7. Verification [implemented for verdict handling; convention for the review itself]

The verifier checks out `last_good_commit` in a clean worktree and:

1. Runs every `acceptance.commands` entry; records actual exit codes.
2. Checks every assertion by test or inspection.
3. Reviews contracts (`contracts` in the task), regressions, TODO/stub/fake implementations, error handling, scope against `owned_paths`, affected integration boundaries.
4. Writes `agents/handoffs/<ID>/VERIFICATION.yaml` (schema `agents/schemas/verification.schema.json`), then `controller.py verify <ID> --machine <verifier machine>`.

PASS moves to INTEGRATION. The controller judges the verdict against the **ledger**, not the verdict's own claims, and refuses PASS when: a ledger command is missing, the verdict has a command the ledger does not declare, an `actual_exit_code` differs from the ledger's `expected_exit_code`, a ledger assertion has no result or its result is not `met` (verdict key `assertions: [{description, result: met|unmet|not_checked}]`), the verifier is the task owner, or `verified_commit` (resolved with `git rev-parse` to a full sha; unresolvable is refused) differs from the task's `last_good_commit` (null is refused). FAIL returns to ACTIVE with required actions and counts toward the retry budget. **A missing or malformed verdict is a verifier-infrastructure failure: the task keeps its state and no budget is consumed** (L-004). Example FAIL:

```yaml
task: T14
status: FAIL
verified_commit: 3f9a2c1
verifier: B/verifier-1
checked_at: "2026-10-10T20:00:00Z"
commands: [{command: "uv run pytest tests/api -q", expected_exit_code: 0, actual_exit_code: 0}]
failures:
  - {type: contract_violation, file: services/api/src/archipelago_api/runs.py, kind: test_failure,
     description: Replay is still read from the in-memory list after restart.}
required_actions: [Serve replay from the persisted event store.]
```

## 8. Integration [convention; role gate implemented]

The integrator collects INTEGRATION tasks, merges each branch into the integration branch with a merge commit (no force, no history rewrite on shared branches), resolves conflicts, runs `make check-integration` on the merged head, checks contracts, then `controller.py complete`. `--commit` must resolve, be an ancestor of the integration tip (`origin/<ledger-branch>` if present, else HEAD), contain the verified commit, and be a merge commit or a later descendant (not the verified commit itself); otherwise `complete` refuses. A failure goes back with `integrate-fail`. Prefer one PR per integration wave, not per task. The integrator never accepts a task that is not in INTEGRATION.

## 9. Git and two machines [convention; ledger publishing implemented]

- Branch `agent/<ID>-<slug>`; one writer per branch; push at milestones, not on a timer. Record `last_good_commit` in the ledger through `review`.
- **Code and handoffs live on the task branch. Task state lives on the ledger branch (`main` by default) and is changed only with `python agents/controller.py --remote <command>`** (`--ledger-branch` to use another). `--remote` reads `origin/<branch>`, applies the change in a throwaway worktree, commits only `agents/TASKS.yaml` and pushes fast-forward. If the push is rejected it refetches and re-applies, so a lost claim race surfaces as "not runnable". This is the only lock. Any role may publish its own transitions; these are state-only commits and the one exception to "no commits straight to main". If the ledger branch is protected, a human must either allow these commits for the agents' identity or name a dedicated ledger branch (decision; not made).
- Without `--remote` the controller edits the local checkout only (single-machine use, tests).
- `validate` checks the ledger alone. `validate --files` also requires handoff/BLOCKER files, and is run from a task branch checkout (they do not exist on `main` until integration).
- B never integrates. B reads, verifies and reviews. Do not assume a shared filesystem; everything crosses machines as commits.
- Unpushed work is invisible. If push fails, say so in the handoff and keep the worktree.

## 10. Escalation [convention]

Agents decide and document: in-scope edits, tests, refactors, internal abstractions, retries, docs, ledger updates, simplifying workflow infrastructure. Humans decide: public contract changes (ADR first), deleting major subsystems or remote branches carrying unmerged work, destructive data changes, paid infrastructure, secrets/credentials, product direction, unrecoverable ambiguity. Escalation is a `blocked_by: human:<what>` entry plus a blocker report; the orchestrator then picks other work.

## 11. Validation tiers [implemented: Makefile + CI]

| Target | Content | When |
|---|---|---|
| `make check-fast` | foundation docs, ledger validate, ruff, controller tests, changed-area unit tests | constantly, every loop |
| `make check-integration` | everything in `scripts/check.sh` (types, drift, full pytest, web lint/test/build) | before REVIEW and after each merge |
| `make check-full` | integration plus Docker tests, container build | scheduled, release, before deploy |

CI runs fast on every push to a PR, integration on PRs, full on `main` and manual dispatch. Agent branches never deploy. In-progress runs for the same ref are cancelled (ADR-0005).

## 12. Process review (meta-loop) [implemented: metrics; convention: judgement]

Triggers: an integration wave completes; a CI failure that repeats; the same failure signature repeats; more than 3 BLOCKED tasks; a long autonomous run ends; before the next run.

`python agents/controller.py review-process` prints metrics and fired triggers; `report --run-id ID --write` writes `agents/runs/<ID>.yaml` (schema `run.schema.json`). The reviewer adds what the ledger cannot know (CI minutes, human interventions via `log-event`, duplicated work, idle time) and writes `agents/reports/REVIEW-<date>.md`. Each recurring process failure becomes an ADR (`agents/templates/decision.md`) with evidence, root cause, change, risks, rollback, status. Ordinary reversible workflow changes the orchestrator may adopt; major or destructive ones go to a human. Durable lessons go to `LESSONS.md` (concise). Prefer deleting mechanisms to adding them.

## 13. Reliability classes of automation

| Class | Meaning | Examples here |
|---|---|---|
| RELIABLE | works inside one session or as pure Git/file state | controller CLI, ledger, handoffs, CI, `launch.py tick` |
| CONDITIONALLY_RELIABLE | works only if a named machine or scheduler keeps something alive | `launch.py start` (detached loop) and legacy `night.py` on an awake machine |
| UNRELIABLE | has a known failure mode that is not detected | LLM reviewer JSON as sole verdict |
| UNSUPPORTED | the runtime cannot keep it alive | background watchers, polling daemons, "exit is the notification" tasks, processes expected to survive an ephemeral cloud container |

UNRELIABLE and UNSUPPORTED mechanisms are not part of the architecture.

### Starting runners and schedulers (agents may do this themselves)

`python agents/launch.py` is the one entry point; the controller itself never launches anything.

| Command | What it does | Class |
|---|---|---|
| `pick --machine M` | prints the role and task the loop would take next | RELIABLE |
| `tick --machine M` | one idempotent step: claim (orchestrator only), or run one bounded fresh `claude -p` session for the picked role, then exit. Holds an OS lock; an overlapping tick exits 3 "busy" | RELIABLE |
| `start --machine M` | preflight, then spawn a detached loop of ticks (`--hours`, `--max-ticks`, `--slice-minutes`). Refuses if one is already ALIVE/STALLED, a STOP file exists, the ledger is invalid, the tree is dirty, `claude` is missing, or there is nothing to do | CONDITIONALLY_RELIABLE |
| `start --runner night -- <night.py args>` | the same detach/log/status wrapper around legacy `night.py` (pid check only, no heartbeat) | CONDITIONALLY_RELIABLE, legacy |
| `status --machine M` | ALIVE / STALLED (pid alive, heartbeat stale) / DEAD (with the recorded stop reason) / NOT_STARTED. Never trusts a pid file alone | RELIABLE |
| `stop --machine M` | writes `.agent-runtime/STOP-M`; honored before the next session | RELIABLE |
| `schedule --machine M --every N` | prints cron, Windows Task Scheduler and Claude-routine recipes | RELIABLE (prints only) |

Work selection is deterministic (`pick_work`): resume own CLAIMED/ACTIVE task; integrator machine takes INTEGRATION; verifier machine takes REVIEW; only the orchestrator machine claims new work. The loop stops on: STOP file, deadline, no work, provider-limit text in session output (it does not wait through a limit; restart after the reset), an error, or **two sessions in a row without progress on the same item** (ledger state and remote branch head unchanged). Sessions use `--permission-mode auto --permission-prompts none` (present in `claude --help` 2.1.296; behavior unverified until the first live trial, T23), never use permission-bypass flags, and run **only inside a dedicated worktree** `.agent-runtime/worktrees/<machine>-<task>` (created or reused; integrators get `integrate/<task>`), never in the shared checkout. A tick fails (status `error`, no session) when the shared checkout or the worktree has modified or untracked files, or the worktree is on `main`/`master`. `--disallowedTools` denies force-push, `--force-with-lease`, pushes to main, `git checkout main`, `git merge`, `git branch -D`, `git clean` and `git reset --hard`; this is a best-effort prefix list, so keep branch protection on main. Unattended sessions therefore cannot merge: integration stops for a human or a PR.

Where the loop runs matters:
- **Persistent machine** (the A/B computers): an agent or person runs `launch.py start`. If the machine sleeps or reboots the loop is DEAD; `status` says so and the next `start` resumes from repository state.
- **Ephemeral cloud session**: the container is reclaimed after inactivity and takes a detached process with it. Do not `start` a loop there. Instead create a Claude routine (the `create_trigger`/`send_later` tools) whose prompt runs `python agents/launch.py tick --machine M` repeatedly until it prints idle, stop, limit or error. Routines are platform-managed and reversible (`delete_trigger`).

Authorization: an agent may start, stop and inspect runners and create or delete routines for this repository without asking, within the bounds above (one launcher per machine, default 8 h). Installing an OS-level recurring job (cron, Task Scheduler) changes the host persistently; do it only when the task or the operator said to, using the printed command. An agent that starts a runner records it in its handoff (machine, command, time, log path).

Not claimed: automatic wait-through of provider limits (the old `night.py` did this; the loop does not), automatic restart of a DEAD loop (the next `tick` or `start` does that), quota awareness.

## 14. What is not built [future]

Wait-through of provider limits, automatic restart of a dead loop, a live trial of the launcher (T23), automatic PR creation, automatic CI metrics collection, ledger merge tooling beyond Git, quota-aware scheduling.
