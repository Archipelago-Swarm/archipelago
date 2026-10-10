# Run the two-computer overnight loop

> **Legacy status (ADR-0003/0004):** describes the pre-ledger runner. Reliability: CONDITIONALLY_RELIABLE (needs an awake machine and an open terminal). Planning from `BOARD.md`, the `agent-coordination` branch and the mailbox is superseded by `agents/TASKS.yaml`; replacement is task T20. Do not extend it.

For the continuing A/B driver with automatic process restart and report retry,
use [driver recovery](driver-recovery.md). The commands below describe a
single bounded `night.py` run.

This is the executable T02 runner, built around [Loop Engineering](https://blakecrosley.com/guides/loop-engineering): a fresh coding session per bounded slice; task state in Git; machine checks and a fresh read-only reviewer outside the coding session; a deadline, round cap, and per-machine task ownership. It runs one coding worker at a time **on each computer**, so A and B work in parallel. The task plan is fixed for a run. It never merges branches or deploys to Vultr.

## Required before launching

- T01 and T02 must be merged into `main`, with CI green. Clone or pull that main on both machines. Do not start from a task worktree or a dirty main checkout.
- Both machines need Git push access, a configured Git `user.name` and `user.email`, Claude Code authentication, Python 3.12+, `uv`, Node/npm, and Git Bash. B needs Docker before T08; without it the runner records T08 as blocked and continues no further B tasks.
- Each person chooses `subscription` or `api` based on their own account. Claude Pro and Max both use `--billing subscription`; API mode is only for separately configured Claude Console API access and requires a user-chosen dollar cap. The flag controls the runner's limits; it does not switch Claude Code credentials. Subscription mode has wall-time, turn, and round caps but cannot promise a precise quota budget.
- Keep the computers awake, online, and plugged in. Leave the terminal processes open. `.agent-runtime/` is ignored and contains local logs, state, and worktrees. Do not delete it during a run.

## Start without repeated prompts

From a clean repository root on **A**:

```powershell
python tools/agents/night.py --machine A --billing subscription --hours 8
```

After A prints the run ID, from a clean repository root on **B** using B's Claude Pro account:

```powershell
python tools/agents/night.py --machine B --billing subscription
```

If a machine intentionally uses separate API access, replace its billing flag with `--billing api` and add `--budget-usd` followed by its chosen positive cap. A publishes the shared run ID, base commit, deadline and fixed assignments on `agent-coordination`; B reads them. No `/agent`, `/goal`, `/loop`, manual RUN_ID copying, or permission bypass flag is needed. Each slice starts a fresh `claude -p` session with automatic permission review and no interactive prompts.

Initial assignments are in `night-plan.json`: A takes T03 and T05; B takes T04, T06 and T08. T04 starts from B's existing `agent/B/T04/run-api` branch and merges the run's main commit into a new night branch, preserving work already pushed there. B must finish or stop its interactive T04 session and push its latest handoff before the night run begins; two writers must never share that branch. The plan excludes T07 and later tasks because they depend on branches that need integration. Change assignments only before A publishes a new run, and keep paths disjoint. The supervisor currently does not implement dynamic reassignment, two simultaneous workers per computer, or automatic merge. It keeps coding while the independent tasks are available and stops when they are reviewable, blocked, out of rounds, out of budget, or at the deadline. A short early finish is a valid result; it does not invent new work to consume the full eight hours.

The short supervised trial uses real task branches. Before starting a fresh eight-hour run, review and merge any trial branches worth retaining, or deliberately carry their reviewed head commits into the next run's source branches. A new run otherwise starts its tasks from main (except the configured T04 source) and will not silently import unfinished trial work. Keep the trial's `.agent-runtime/` state and logs until its branches are accounted for.

## What the runner checks

Before each task: fixed machine owner, plan/base SHA, clean main, unique branch/worktree, required executables, deadline and local lock. In each worktree it installs locked Python/npm dependencies. After a Claude slice it rejects edits outside the task's reserved paths, runs `scripts/check.sh`, and if that passes asks a fresh read-only Claude session to evaluate the task card and implementation. It commits and pushes a Markdown handoff even if checks fail. A reviewer pass marks `review`, which means ready for an integrator, **not** merged or done.

Worker stdout and stderr remain in ignored local logs; only redacted status and exact branch/SHA are pushed. A published plan is immutable for that run. A cannot publish a second plan while the first is active; B cannot claim A's tasks. A stale or rejected Git push marks work UNSYNCED and preserves its worktree instead of assigning it elsewhere.

Usage/rate errors cause waits outside the model. The runner uses a reported UTC reset when present, otherwise waits 15, 30, then 60 minutes between probes, capped at ten probes or the run deadline; it persists the next eligible time across supervisor restarts. Authentication, billing and permission errors block the task. The default limit is four coding rounds per task, 25 minutes per round, an eight-hour shared window and a separate ten-turn reviewer. A stop file at `.agent-runtime/STOP` prevents new slices; an already-running slice finishes or times out. If the runner itself exits, rerun the same command on that computer: it reads the published plan and local state. Inspect stale lock files and live child processes before restarting after a hard OS kill.

## Morning review

Read `.agent-runtime/reports/<run-id>-A.md` and `-B.md` locally, or the same reports on the pushed `agent/A/<run-id>/report` and `agent/B/<run-id>/report` branches. Each task also has a pushed `agent/<machine>/<run-id>/<task-id>` branch with `agents/handoffs/<task-id>/LATEST.md`. The integrator reviews checks and diffs against current main, opens/merges suitable PRs, then updates the task board. Keep blocked branches and local logs for recovery.

After integration, A archives report Markdown on `main` and prunes only redundant generated refs according to [branch-cleanup.md](branch-cleanup.md). The cleanup command defaults to a preview; unfinished work and the active assignment remain available for recovery.

The separate design run configuration (`run-config.example.json`) describes future resource limits; the current executable launcher takes its essential limits through CLI flags and the fixed plan. Do not assume editing that example changes a live run.
