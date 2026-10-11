# Archipelago: required agent instructions

Read, in order: `agents/LESSONS.md`, `agents/PROTOCOL.md`, `agents/CONTRACT.md`, `agents/vision/roadmap.md`. Task state is in `agents/TASKS.yaml`: run `python agents/controller.py status` and `next`. For a new setup follow `agents/START_HERE.md`. For an assigned task also read its handoff on the task branch (`agents/handoffs/<ID>/LATEST.md`) and the contracts it lists.

**You are not finished when code is written.** You are finished when the assigned acceptance criteria have been verified, relevant validation passes, state has been documented (handoff, ledger), and the work is ready for verification or integration. Workers stop at `REVIEW`; only the integrator completes a task after a verifier PASS.

Rules that apply to every agent, including delegated ones:
- The repository is the source of truth. A chat transcript is not a handoff; every active, blocked, paused or finished task needs a pushed Markdown handoff.
- Change task state only through `python agents/controller.py --remote ...` (shared ledger on origin; claims cannot collide).
- You may start or stop runners yourself: `python agents/launch.py start|status|stop|tick|prompt` (PROTOCOL sections 3 and 13). All agents are Claude cloud sessions (no machines A/B): dispatch workers with `create_session` using `launch.py prompt`, or use a routine that calls `tick`; never a detached loop. Stay inside the task's `owned_paths`.
- Do not create watchers, daemons, polling loops, mailboxes or branch-messaging. Nothing may depend on a process outliving your session (LESSONS L-001, L-002).
- Validate with `make check-fast` constantly and `make check-integration` before REVIEW. Say exactly what you did not run.
- Same failure twice, or a retry budget spent: BLOCKED with a complete `BLOCKER.md`. Make reversible decisions yourself and document them; escalate only what PROTOCOL section 10 lists.
- Do not confuse coding agents with simulated drone nodes. Do not start `tools/agents/night.py` until its preflight and `tests/agents` pass.

## Hang protection (Windows dev machine)
Node-process, Docker and e2e tests hang here. `.claude/settings.json` runs `scripts/hook_no_hang.py` before every Bash call and blocks: pytest without `timeout N`, pytest on `tests/infra|e2e|swarm|noderuntime|experiments`, `vitest` watch mode, Docker and `make demo/check-full/check-integration`. The root `conftest.py` also kills any test over 120 s and any pytest run over 420 s, and skips those suites on win32 (`ARCH_ALLOW_SLOW=1` re-enables them; run them in CI/Linux). Test logic in-process instead.
