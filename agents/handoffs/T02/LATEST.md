# Handoff: T02 / initial executable night runner

- State: review candidate; real two-computer trial and remote CI still pending
- Run / machine / worker: bootstrap / A / architecture agent
- Branch: `agent/A/T02/overnight-loop`
- Base: T01 review branch at `844d2e0`, merged with main correction `0d8691a`
- Reserved paths: `tools/agents/`, `tests/agents/`, `agents/operations/`, this handoff; A integrator also fixes `.gitattributes` and root pointers for Windows

## Delivered

`tools/agents/night.py` runs a bounded fresh-session loop. A publishes an immutable eight-hour plan on `agent-coordination`; B joins exactly that plan. Initial owner lanes are A: T03/T05 and B: T04/T06/T08. B's existing T04 branch is used as a source for its new night worktree, preserving its published progress. Each task has its own branch, locked dependency install, scoped path audit, full repository check, fresh read-only reviewer, pushed handoff and remote checkpoint. The runner reports after each slice and writes a morning report branch. No auto-merge or cloud deployment occurs.

Rate-limit waits persist their next eligible UTC time and use a reported reset when available, otherwise 15/30/60-minute backoff capped by ten probes and the shared deadline. Billing/authentication/permission errors, unknown API spend, unreserved file edits and rejected pushes stop or block instead of silently continuing. API mode requires a positive per-machine dollar cap; subscription mode uses wall-clock and iteration caps. One coding worker runs per machine in this version.

## Validation on A (Windows, 2026-10-10)

- `python -m unittest discover -s tests/agents -v`: ten tests passed, including two local clones agreeing on the same plan, duplicate assignment rejection, a fake worker/check/reviewer cycle with a pushed remote checkpoint, recovery of B's prior branch, lock exclusion, error classification and path audit.
- `scripts/check.sh` through Git Bash: 41 Python tests passed, 28 Vitest tests passed, Ruff/mypy/ESLint/TypeScript/build passed.
- `uv run ruff check tools/agents tests/agents` and `uv run ruff format --check tools/agents tests/agents` passed.
- A single `claude -p` one-turn smoke with the runner's output/permission/turn flags returned `OK`, exit 0, on Claude Code 2.1.296. This was a CLI/auth smoke, not an overnight task run.
- The first Windows full check caught CRLF conversion of generated TypeScript. `.gitattributes` now pins TS/JS to LF; generator check and subsequent full suite pass.

## Remaining gate / limits

- T01 and this branch must land on main with CI evidence before the documented launcher is used from clean main.
- Test the actual A/B startup once on both computers. B's last readiness handoff reported `uv` and Docker missing; install `uv` for any run and Docker before T08. `gh` is optional to the runner.
- The current runner has a fixed plan, one worker per machine and review branches; dynamic reallocation, concurrent workers within one machine, automatic PR creation and merge, resource caps beyond task count, and a hard OS-kill recovery test are future work.
- No real eight-hour training/coding session or Vultr deployment has run. The CLI can terminate early when independent tasks are reviewable or blocked.

## Exact next actions

1. Fetch/review this branch and run `scripts/check.sh` and the new runner tests on current main integration.
2. Merge T01 then T02, preserving the B T04 source branch. Check CI status; fix any platform failure.
3. On B install `uv` (and Docker for T08), stop its interactive T04 writer, and push its latest handoff.
4. Run a short supervised A/B trial with `--hours 0.33 --max-rounds 1`, then start a fresh eight-hour run only if the trial confirms remote plan publication, branch isolation, checkpoint/restart, and no prompt stalls.

The exact commit SHA for this handoff is the pushed head of `agent/A/T02/overnight-loop`; look it up after publication. Do not resume from the T01 branch alone.
