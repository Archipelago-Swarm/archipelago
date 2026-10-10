# Mandatory contract for all coding agents

## Scope and authority

Build the roadmap in dependency order. Human instructions take precedence. The roadmap defines intent; executable schemas define interfaces; task cards define local acceptance. Resolve conflicts through the integrator and a short ADR instead of inventing a new architecture in a worker branch.

Keep plans, progress and handoffs under `agents/`. Root `CLAUDE.md` and `AGENTS.md` point here. All timestamps in coordination records are UTC; human schedules may additionally show America/New_York. Documents are persistent memory, not proof that their described features exist.

## Before work

Bootstrap exception: before T02 creates the remote ledger, A records its T01/T02 ownership in the task card and handoff and runs those tasks interactively. After T01, A may give explicit, nonoverlapping manual assignments to B in pushed task cards. No unattended dispatch or automatic reassignment is permitted until T02 migrates these assignments into the tested ledger. This exception avoids requiring the supervisor to exist before it can be built.

1. Fetch remote state and inspect dirty/unpushed work. Never discard it.
2. Read your assignment on `agent-coordination`, task card and latest handoff on its recorded branch.
3. Verify owner, assignment generation, dependencies merged, and no overlapping shared-file reservation.
4. Use your own branch/worktree: `agent/<machine>/<task>/<short-description>`.
5. Create a handoff checkpoint with plan, acceptance checks and next steps before implementation.

Computer A is the single dispatcher/integrator. Computer B leads its own workers but accepts A's recorded assignments. Maximum two active coding workers per machine initially, counting any reviewer that invokes a model; no recursive fan-out. Coordinators cannot silently exceed the slot budget by coding in parallel too.

## During work

- Work only inside assigned paths. Shared schemas, lockfiles, CI, root manifests, migrations and deployment changes require explicit serialized ownership.
- Implement bounded increments. Run meaningful behavioral tests appropriate to the change; do not add tests that merely repeat constants from the implementation.
- Update Markdown after each meaningful milestone, at least every 15 minutes, and before expensive training/tests, context rollover or stopping. Push a checkpoint at most every 20 minutes while network is available.
- Preserve exact commands, working directory, seed/config, branch, base and checkpoint SHA, artifacts, failures and next executable steps. Do not rely on chat history.
- Never claim completed based on a model's statement alone. Completion requires acceptance evidence, review and merge. Local completion is `review`, not `done`.
- Keep secrets, tokens, credentials, raw personal data, local chat logs and large binary artifacts out of Git and handoffs.

## States

`ready -> assigned -> in_progress -> review -> done`; dependencies yield `waiting`; failures yield `blocked`; planned interruption or usage limits yield `paused`. Only the integrator marks `done` after merge. Every state except untouched `ready/waiting` has a remote Markdown record. Use the handoff template even for partial or failed tasks.

At shutdown, record `last_good_commit` and `resume_from`, tests passed/failed/not run, known defects, architectural decisions, attempted fixes, remaining work and a prioritized next action. If unable to push, mark `UNSYNCED` locally and tell the supervisor; another computer cannot recover unpublished edits. The supervisor must preserve a local patch/status snapshot if the model stops abruptly; a model-generated final handoff cannot be guaranteed after a hard kill.

## Git and integration

Do not share a working directory between writers. Do not commit straight to `main`, force-push shared branches, overwrite another worker, reset dirty trees or delete worktrees with unpublished work. The initial empty-repository bootstrap is the one main-branch initialization exception.

Fetch before starting a task. For an active task branch, merge current main when needed; avoid history rewriting during handoff. Push small task commits; incomplete work is allowed on a clearly labeled WIP branch with a handoff. Open a PR with task ID, behavior, validation, evidence and unresolved risks. Only the integrator merges, after reviewing the diff and checks against current main. Interface changes are integrated before dependent changes. Use a merge strategy that preserves recovery commits where practical.

No auto-merge until T02 and CI gates are validated and the operators explicitly enable it in the run config. Default unattended output is pushed branches/PRs ready for review. If merge authority is enabled, ordinary in-scope changes may merge after all gates; cloud spending, destructive migrations, secrets/access changes and dependency-provider changes remain operator decisions.

## Stop conditions and resources

Stop starting model calls at the run deadline, configured budget cap, lost ownership, unresolved permissions or unavailable authentication. Complete/preserve the current checkpoint. Respect provider-reported reset times and retry instructions. Never bypass usage limits or silently switch to paid API billing. A five-hour window is not five hours of continuous usable model time.

Three unsuccessful attempts at the same root cause -> `blocked` with evidence; choose independent work. Two cycles with no measurable progress -> reassess task size/dependency rather than looping blindly. Workers may neither increase their budget nor expand the roadmap to keep themselves busy.

Build the simulator for synthetic missions. Keep real vehicle integration outside this initial scope. Use Vultr for deployed compute and TigerData for durable database needs. Any new stack must solve a documented need and include deployment/maintenance cost.

## Definition of done

Acceptance checks pass; failures/limitations are explicit; meaningful tests cover changed behavior; relevant docs/config are updated; no secret/binary leakage; handoff and PR identify exact evidence; integration passes on current main; task board points to the merged commit. Performance/research claims additionally link reproducible run artifacts.
