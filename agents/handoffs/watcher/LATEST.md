# Handoff: idle watcher (B, 2026-10-10 UTC)

- State: ready for integrator review; not a numbered task. Branch: `agent/B/idle-watcher`.
- Adds `tools/agents/idle_watch.py A|B`: loops `night.py --billing subscription`, fast-forwards a clean `main` (the runner requires `HEAD == origin/main`), idles 3 min when no task is assigned, backs off 3-30 min on failures, and never exits except on `.agent-runtime/STOP`. Single instance via pidfile.
- After every pass it plain-pushes (never force) local `agent/<machine>/*` branches, so commits the runner did not push (for example a conflict-resolution merge with no later file changes) still reach the remote and the other machine's watcher can see them.
- Machine A can run it as `python tools/agents/idle_watch.py A` from a clean `main` checkout once this is merged (or copy the file).
- Not covered: surviving a reboot (use a logon scheduled task), and Docker for T08 on B.
- Validation: syntax-checked and run on B as a local copy (`.agent-runtime/idle-watch-B.py`); this tracked version is the same logic parameterized by machine and not yet run.
