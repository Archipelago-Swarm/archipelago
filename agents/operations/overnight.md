# Two-computer overnight runbook

This is the required operating design. T02 must implement and validate the external supervisor and ledger helpers before unattended use. Neither this file nor the initialization prompt starts background jobs.

For the first executable version, see [night-runner.md](night-runner.md). It runs one worker per machine from a fixed published plan and pushes review branches and reports. The two-worker-per-machine and dynamic ledger behavior below remain the target design until implemented and tested.

## Top-down organization

| Role | Computer | Responsibility |
|---|---|---|
| Overall lead / integrator | A (your computer) | Dispatch, dependency order, shared-file reservations, CI review, merges, final report |
| Simulation/learning workers | A, up to two slots | T03, T05, T07, T09, T12 as ready |
| Platform/product lead | B (friend's computer) | Receive assignments, manage local slots, checkpoint/recover workers |
| Platform/product workers | B, up to two slots | T04, T06, T08, T10, T11 as ready |

T01 belongs to A; T02 follows on A. During bootstrap, B may start T04 from A's pushed, locally validated T01 review commit while A completes CI/merge; B must record that SHA and keep its branch unmerged until T01 lands. Leads can occupy a worker slot when coding. Review also occupies a slot. Start with one worker per machine if RAM, cooling or available model quota is uncertain. Increase only after a measured trial. No nested spawning. Build computers and deployed Vultr runtime need not be the same machines.

## Before the first unattended night

1. Both humans clone the repository, authenticate Git push and their own Claude account, confirm the same default branch, and agree A/B roles. Keep both computers awake and networked; use Docker Desktop with a working Linux engine/WSL2 where appropriate. Standardize Linux containers even when host shells differ.
2. Copy `run-config.example.json` to an ignored `.agent-runtime/run-config.json` on each computer; share only a sanitized copy in the run's Markdown record. Set one RUN_ID, UTC start/end (eight hours apart), slots, resource limits and billing mode. Identity/time/local resource fields are required before unattended work. API dollar budgets are required in API mode; cloud budgets are required before cloud spending, but their absence does not block local work. `null` means unset, never unlimited.
3. Select subscription or API billing deliberately. Disable unapproved paid fallback. Verify which account actually funds each worker; sharing an account can share quota. Do not copy authentication tokens between machines.
4. Agree repository merge authority and enable GitHub branch protection/required CI checks if available. Use separate human Git identities. Workers push only task branches; cloud deployment credentials belong only to the approved deployment lane/environment.
5. Create or identify the approved Vultr project/instance and TigerData service. Record region, capped spend, allowed actions, DNS/HTTPS plan and secret locations. Credentials can be supplied later: local simulation and CI should proceed while cloud tasks are blocked.
6. Run T01 interactively. Run T02 recovery tests, then a 20-minute supervised trial with one worker per computer. Verify both can fetch the other's checkpoint and resume an intentionally interrupted task.
7. Start the external supervisors only after the trial passes. Read the morning handoff before beginning another run.

## Durable assignment ledger

Use a dedicated `agent-coordination` branch, initially based on main, containing `agents/coordination/<run-id>/ledger.json` and per-task assignment Markdown. It is control data, not an application branch. Never merge its whole divergent tree into main. Final summaries are copied deliberately through an ordinary docs PR.

Only A's dispatcher process writes this branch. It uses an OS-level local lock so two copies cannot run on A; each Git update is a commit against the freshly fetched head and a normal fast-forward push. A rejected push must trigger a fetch/reconciliation, never force. Git issues/comments may provide convenient visibility, but are not atomic claims and are not required for the protocol.

Ledger fields per task: task_id, owner_machine, worker_id, branch, base_sha, generation, state, assigned_at_utc, last_seen_checkpoint_sha, reserved_paths, dependency_commits and next_check_at_utc. Add run_id, dispatcher_id and a monotonically increasing dispatcher_generation globally. A worker may start only after its assignment is visible on the remote branch and matches both generations. Machine B cannot self-assign A's work.

Workers publish status through their task branch: a unique checkpoint Markdown plus a current handoff. The non-LLM supervisor records a local process heartbeat every minute; publishes a small status/handoff update to the task branch at least every ten minutes, serialized with worker Git writes. Never run supervisor Git mutations while the worker is committing. Poll remote coordination every 60 seconds; back off on remote failures. Progress does not require an LLM call every minute.

If the coordinator goes offline, currently assigned workers can complete their bounded slice and push a checkpoint; no new assignments or merges occur. No automatic coordinator takeover in the first version. To move leadership to B, the humans stop A's supervisor and active integration, verify remote state, then record the new dispatcher generation. Old generation results may be recovered but cannot automatically pass the merge gate.

Stale heartbeat is a suspicion, not proof that a worker is dead. Never immediately reassign on a timer. Mark `suspected_stale`; inspect remote commits and contact/stop the old process through its supervisor. Only after an acknowledged stop, confirmed process exit, or explicit human recovery decision may A increment the task generation and reassign. Preserve old branches. A delayed old worker that returns must checkpoint and stop when its generation differs. Integration rejects stale-generation PRs until reconciled.

This conservative single-writer design favors consistency over maximum throughput during a machine outage. A database-backed lease service can follow later; adding another database for the initial coding agents is unnecessary.

## Worktree and Git lifecycle

Each worker starts from a merged dependency commit in its own worktree. Example after assignment, from the repository root:

```sh
git fetch origin
git worktree add .worktrees/A-T03 -b agent/A/T03/world origin/main
```

Record the actual branch/path in the task. Branch names are examples, not commands to overwrite an existing branch. On resumption fetch the recorded remote task branch and inspect it, then create/reuse a worktree for that branch. Do not start again from main and lose the prior worker's work.

Commit code and its handoff together where possible. The handoff records the previous stable SHA; after the checkpoint commit exists, the supervisor/ledger records its exact SHA externally, avoiding a self-referential commit hash inside its own commit. Small WIP commits are preferable to an unpushed overnight working tree. On local network failure, keep the worktree and patch, mark UNSYNCED and stop reassignment until it is recovered.

PR checks: task/generation/paths match; no unapproved schema drift; tests/evidence present; acceptance fulfilled; current main integration passes; no unresolved conflicts. Only A merges. A rejects a shared-file collision before both branches build further on it. Tasks touching lockfiles, contracts and migrations reserve those paths explicitly; domain workers request additions through the integrator.

## External supervisor specification (T02)

Use a small Python process with persisted JSON state and an OS-local lock. It invokes installed Claude Code in bounded noninteractive sessions or a supported SDK, rather than keeping one model conversation alive all night. Check `claude --version` and supported flags; pin the tested version in the run record. Version 2.1.289 was observed on computer A during repository initialization; B must verify its own installation.

One bounded invocation can use this shape after the assigned worktree and approved permissions are ready:

```sh
claude -p "Read CLAUDE.md and agents/START_HERE.md. Resume your recorded assignment; complete one bounded slice and push its handoff." --output-format json --max-turns 30
```

The supervisor supplies task/worker identity, a task-specific prompt and a reviewed permission policy. The example alone is not an unattended launcher. Use the installed version's supported unattended permission mode and a minimal allowlist, verified during the trial. Treat denied actions as blocked work. Never solve unattended prompts with `--dangerously-skip-permissions`. Review hooks/MCP settings before startup; do not fetch arbitrary plugins while running unattended.

State machine:

```text
PREFLIGHT -> READ_ASSIGNMENT -> RUN_SLICE -> CHECKPOINT -> VERIFY -> REPORT
REPORT -> READ_ASSIGNMENT                if ready work, budget and time remain
RUN_SLICE -> WAIT_LIMIT                  on a confirmed provider limit
RUN_SLICE -> RECOVER                     on unexpected exit/no result
any -> DRAIN -> STOPPED                  on deadline, budget, stop file or ownership loss
```

Required persistence: run ID, machine/worker, task generation, worktree/branch, PID/process start identity, last checkpoint SHA, session ID if provided, attempts, cumulative usage/cost, last error category, next eligible time and stop reason. Store private raw logs outside Git; publish a redacted Markdown summary. A completion string is advisory: verify Git state, tests and task criteria independently.

Wall-clock bounds: target 20-30-minute work slices, 15-minute model checkpoints, supervisor status every minute. At 30 minutes ask a responsive session to checkpoint; if it does not, capture Git status/diff and logs before terminating only its recorded child process tree. Do not assume exit hooks or an interrupted model can write a final handoff. Atomically write supervisor state via temp file + rename. Persist before launching each child and after its exit.

T02 tests with a fake Claude child (no paid calls): successful slice; crash mid-edit; missing result; malformed result; context/turn limit; known/unknown rate limit; shutdown during a test; denied permission; duplicate supervisor; two machines requesting one task; stale worker returning; rejected push; offline network; budget/deadline stop; restart from last checkpoint. Default all tests to dry-run; no cloud provisioning.

## Rate limits and five-hour windows

Use provider-reported usage/reset information when available through supported surfaces. Session windows and weekly limits both matter. Parallel agents consume the same account's allowance faster; a five-hour session limit is not a promise of five hours of work. Do not infer remaining quota from local token counts alone.

If reliable quota shows 80% used, stop assigning new slices; at 90%, drain/checkpoint active workers. These are configurable project thresholds, not Anthropic guarantees. Reserve capacity for handoff but maintain supervisor snapshots because a hard limit can arrive without warning.

On a confirmed limit, checkpoint without demanding further model calls, publish `paused`/reason/reset evidence, and release local slots. Wait outside the model until the reported reset plus a small jitter, bounded by the run deadline. If no reliable reset is available, use bounded backoff (15, 30, then 60 minutes), at most three probe attempts; then require operator attention. Authentication, billing and permission errors are not transient rate limits.

On wake, confirm remaining wall time/budget, Git connectivity, active assignment generation, dependencies, and checkpoint. One successful small resumed session may restore dispatch; do not launch all workers simultaneously before verifying recovery. Weekly exhaustion or a reset beyond the deadline ends this run in a paused handoff.

API mode uses an operator-set dollar ceiling plus bounded turns and wall time; tool cost metadata is measured consumption, not a perfect pre-call hard cap. Set provider-side limits and a reserve for one in-flight response. Never automatically switch from subscription to API or between people's credentials. Waiting counts toward the eight-hour window. Further runs require an explicit new run window.

## Compute and cloud limits

Default local reservations: two workers max per machine, one integration build at a time, one training experiment per machine, one GPU job globally if a GPU is approved. Initial experiment cap four drone nodes, two Torch CPU threads per node; measure before increasing. Set actual RAM/CPU headroom from the machines' specs during preflight. Do not run benchmark training while saturating the host with unrelated parallel builds.

Vultr inventory must track resource ID, region, purpose, owner, created time, expected spend, maximum spend and retention decision. Tag resources by project/run. Deploy only within the approved budget and authorized instance. Snapshot retained experiment artifacts before stopping/removing anything. Never delete resources just because the run deadline arrives; record a cleanup recommendation for the owner.

## Morning handoff

Publish `agents/runs/<run-id>.md`: merged commit and demo entrypoint; implemented/pending gates; task branch/PR map; experiment results and limitations; cloud inventory/cost status; paused/blocked reasons; reset time evidence; exact next commands. Archive no worktrees until all edits are pushed and retention is agreed.
