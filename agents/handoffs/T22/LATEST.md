# Handoff: T22 repair (control-plane hardening)

- State: REVIEW-ready. Base 276c80a. Fixes the 8 defects in `agents/handoffs/BOOTSTRAP/VERIFICATION.yaml`.

## Done
- `controller.verify`: exit codes judged against the ledger; every ledger command required, unknown commands refused; PASS needs every ledger assertion with result `met` (verdict key `assertions`, validated in the controller because the schema forbids extra keys); `verified_commit` and `last_good_commit` both resolved to full shas and must be equal, null refused; verifier must differ from owner.
- Ownership: `--by` required and equal to owner for start/review/record-failure/block; requeue/unblock also accept the integrator machine; requeue clears owner/machine/branch; unblock refuses open `human:*` blockers without `--resolved`, and the 4th unblock forces FAILED (`UNBLOCK_CAP = 3`).
- `complete`: commit must resolve, be an ancestor of `origin/<ledger-branch>` (else HEAD), contain the verified commit, and be a merge commit or a later descendant.
- Retry: `same_failure_signature` floor and loader default 3; signatures normalized (line numbers stripped).
- `launch.py`: sessions only in `.agent-runtime/worktrees/<machine>-<task>`; tick errors on dirty (incl. untracked) shared checkout or worktree, or worktree on main/master; DENIED extended; unverified claude flags documented in code. Integrator sessions can no longer merge (by design).
- PROTOCOL.md updated.

## Not done / needs the integrator (outside reserved paths)
- `agents/schemas/task.schema.json`: make `same_failure_signature` optional with `default: 3`; `agents/TASKS.yaml` entries still say 2 (the controller clamps to 3).
- `agents/schemas/verification.schema.json`: add optional `assertions: [{description, result: met|unmet|not_checked}]`.
- Callers of `start/review/block/record-failure/requeue/unblock` (scripts, docs outside reserved paths) must now pass `--by`.
- Shared checkout on main is allowed (no session runs there); only the session worktree must not be on main.

## Not run
Live `claude -p` session (fake binary only), Docker tests, GitHub CI.
