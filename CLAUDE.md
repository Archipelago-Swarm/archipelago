# Archipelago: required agent instructions

Read, in order: `agents/LESSONS.md`, `agents/PROTOCOL.md`, `agents/CONTRACT.md`, `agents/vision/roadmap.md`. Task state is in `agents/TASKS.yaml`: run `python agents/controller.py status` and `next`. For a new setup follow `agents/START_HERE.md`. For an assigned task also read its handoff on the task branch (`agents/handoffs/<ID>/LATEST.md`) and the contracts it lists.

**You are not finished when code is written.** You are finished when the assigned acceptance criteria have been verified, relevant validation passes, state has been documented (handoff, ledger), and the work is ready for verification or integration. Workers stop at `REVIEW`; only the integrator completes a task after a verifier PASS.

Rules that apply to every agent, including delegated ones:
- The repository is the source of truth. A chat transcript is not a handoff; every active, blocked, paused or finished task needs a pushed Markdown handoff.
- Change task state only through `python agents/controller.py --remote ...` (shared ledger on origin; claims cannot collide).
- You may start or stop runners yourself: `python agents/launch.py start|status|stop|tick --machine X` (PROTOCOL section 13). In an ephemeral cloud session use a routine that calls `tick`, not a detached loop. Stay inside the task's `owned_paths`.
- Do not create watchers, daemons, polling loops, mailboxes or branch-messaging. Nothing may depend on a process outliving your session (LESSONS L-001, L-002).
- Validate with `make check-fast` constantly and `make check-integration` before REVIEW. Say exactly what you did not run.
- Same failure twice, or a retry budget spent: BLOCKED with a complete `BLOCKER.md`. Make reversible decisions yourself and document them; escalate only what PROTOCOL section 10 lists.
- Do not confuse coding agents with simulated drone nodes. Do not start `tools/agents/night.py` until its preflight and `tests/agents` pass.
