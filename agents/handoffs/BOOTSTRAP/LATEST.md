# Handoff: BOOTSTRAP (autonomous control plane) / 2026-10-10

- State: REVIEW (ledger task T22). Awaiting verifier (B or a human) then integrator (A).
- Branch: claude/quirky-dirac-4eomw1. Base: fdee33e (main). Last good commit: recorded in `agents/TASKS.yaml` T22.
- Owner: bootstrap agent (cloud session).

## Objective
Retrospective of the 2026-10-10 A/B run, then a repo-based control plane so another agent can continue from the repository alone.

## Delivered
See `agents/reports/AUTONOMY_READINESS.md` (implemented / convention / future / unsupported, and the comparison with the previous night) and `agents/reports/LAST_RUN_RETROSPECTIVE.md`.

## Acceptance for T22 (run these)
- `make check-fast` exit 0.
- `SKIP_DOCKER=1 make check-integration` exit 0.
- `uv run python agents/controller.py validate` exit 0.

## Added after review request
`agents/launch.py` (tick/start/status/stop/schedule), `controller.py --remote` (shared-ledger publishing), ADR-0007, tasks T20 (now depends on T23) and T23 (live launcher trial, human-blocked). PR: https://github.com/Archipelago-Swarm/archipelago/pull/8 (subscribed for CI/review events).

## Not verified
GitHub Actions run of the new `ci.yml`; any real `claude -p` session driven by `launch.py` (fake binary only); Docker-marked tests; `make check-full`. No live agent has been driven through the ledger.

## Decisions
Directory is `agents/` not `.agents/` (ADR-0006). Legacy runner kept pending T20; `mail_watch.py` and `idle_watch.py` removed. T09 reclassified as scope-reduced COMPLETE with remaining acceptance in T17 (reversible; the reasoning is in the ledger note).

## Next actions
1. Push CI, confirm `fast` and `bootstrap` jobs pass; fix workflow issues first.
2. Verifier: write `agents/handoffs/BOOTSTRAP/VERIFICATION.yaml` (schema agents/schemas/verification.schema.json) after running the three acceptance commands on the last good commit, then `controller.py verify T22`; A runs `complete`.
3. Run T14, T16, T20 as the first ledger-driven tasks and count interventions with `log-event`.
4. Human decisions listed in the retrospective (remote branch deletion, T18 ADR, T10 credentials).
