# Branch cleanup

Machine A runs `tools/agents/cleanup_branches.py --apply` after each completed run has been integrated. The command archives each run report at `agents/runs/<run-id>-<machine>.md` on `main`, then removes generated remote refs only when their content is already safe:

- A task or carry branch is deleted only when its head is an ancestor of `origin/main`.
- A report branch is deleted only when it changes exactly its report file and that file has an identical Git blob on `origin/main`.
- The active run's task, source, and report refs are protected even if otherwise eligible. Named work branches (for example `agent/B/T10/prep`), divergent checkpoints, `main`, and `agent-coordination` are never selected.
- Every deletion uses the observed remote SHA as a lease. If the branch moved, deletion fails and the next cleanup pass reassesses it. Archiving must push successfully before any report ref can be removed.

From a clean, up-to-date `main` checkout on A, preview with `uv run python tools/agents/cleanup_branches.py`. Apply with `uv run python tools/agents/cleanup_branches.py --apply`. A failed or interrupted cleanup leaves remaining refs for the next pass and does not block coding. Do not delete the local `.agent-runtime` worktrees or logs as part of this procedure; keep unfinished branches and their handoffs for recovery.
