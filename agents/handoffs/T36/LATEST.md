# T36 telemetry ingest handoff

Status: WIP / validation blocked; NOT REVIEW, NOT verified, NOT COMPLETE.
Owner: codex/T36; machine A; sole writer is Codex T36 support worker.
Branch: agent/T36-api-telemetry-ingest-endpoint
Base: 7d848fadf79577c14f5117630e6351e537e8686b (claude/elegant-pascal-a8a3hp)
Implementation checkpoint: fb7dadc82d6ff1536ae81ecf70a493e3e9abf08d
Last good commit: none (no executable checks ran).
Draft PR: https://github.com/Archipelago-Swarm/archipelago/pull/13
Date: 2026-10-10 UTC

## Objective and changes
Section 8.1 POST /v1/telemetry router factory, without editing app.py.
Implemented separate bearer token authentication (>=16 chars, constant-time byte comparison, login-token reuse refused); streaming 256 KiB / 500-event limits; JSON/envelope validation; canonical per-item Action/LearningEvent/MetricSample/WorldSnapshot validation and unknown-run reasons; dedupe; atomic bounded admission; 503 + Retry-After with no mutation; run-sequence assignment with producer sequence preserved; replay/subscriber delivery; O(1) Persister enqueue; ordered off-loop disk writer; lifespan shutdown drain; durable dedupe recovery beyond replay tail.

Behavioral tests mount the router on existing create_app runtime and cover auth/limits, mixed per-item rejection, repeated batches, all four record kinds, mixed runtime/telemetry log ordering, stalled disk overload, stalled real Persister sink, shutdown drain and cross-restart dedupe.

## Exact execution evidence
Attempt: Get-Location; git status --short; git remote -v
Result: process NOT CREATED; no shell exit code.
Attempt: uv run pytest tests/api/test_telemetry_ingest.py -q
Result: process NOT CREATED; no pytest output or exit code; NOT RUN.
Both returned: exec-server rejected request (-32603): helper_unknown_error: setup refresh had errors.
This was one bounded retry to see whether process execution recovered.

NOT RUN:
- uv sync --frozen
- uv run pytest tests/api/test_telemetry_ingest.py -q
- uv run pytest tests/api -q
- uv run ruff check packages services tests
- uv run ruff format --check packages services tests
- uv run mypy
- make check-fast
- make check-integration

Every executable acceptance criterion remains UNVERIFIED. No test, formatting, typing, performance or integration PASS claimed. No skips, xfails or failure bypasses added.
GitHub API reads and scoped task-branch commits succeeded. No local worktree could be created because process execution failed; task branch is the isolated implementation checkpoint. Ledger/controller state was not changed.

## Decisions and integration boundary
No dependencies, cloud calls, spending or credentials added.
Integrator T29 mounts after app.state.manager = mgr:
    from .telemetry import make_router
    app.include_router(make_router(mgr))
Set TELEMETRY_TOKEN separately from ARCHIPELAGO_API_TOKEN.

Router installs an EventLog-compatible bounded adapter on manager.log so ALL simulation and telemetry log appends share one serial off-loop writer. Otherwise synchronous RunManager._emit could overtake a queued telemetry append and EventLog.load would discard its lower sequence. Ordinary simulator events are best effort: shared-queue saturation sheds them with a generic warning and ingest.dropped counter, while telemetry requests reject atomically. Integrator must review this capacity/drop tradeoff.

Accepted means admitted to memory/writer/Persister spool, not committed to disk or TigerData. Shutdown timeout reports pending work; a stalled worker thread cannot safely be killed. Dedupe IDs are retained for manager lifetime and reconstructed from durable history on startup; not a transactional database index.

Stream entries retain existing API type/tick/status compatibility fields plus canonical kind, and source_sequence. T33 consumption requires integration verification.
Router's nested lifespan calls RunManager.shutdown before draining its writer because parent app cleanup runs later. Existing shutdown is idempotent; review with T29 lifecycle changes.

## Files modified
- services/api/src/archipelago_api/telemetry.py
- tests/api/test_telemetry_ingest.py
- agents/handoffs/T36/LATEST.md

## Next executable steps
1. Claude/verifier checks out exact PR head in an execution-capable worktree, runs uv sync --frozen, targeted pytest, ruff formatting/check, mypy, broader API and integration checks.
2. Repair any actual runtime/type/format failures in reserved paths, then record evidence before REVIEW.
3. T29 mounts router, supplies separate token, verifies T29/T33 live/replay and shutdown behavior.
4. Maintain one task-branch writer. Codex is pausing after published WIP, not claiming task completion.
5. Change PR base to main once elegant branch merges. At PR creation T36 prompt was still absent main.

## Risks
Code/tests have not executed. Draft PR is a recovery checkpoint, not functional evidence. Claude retains merge/integration ownership. Existing integrator-registered handoff placeholder was replaced; no competing worker implementation was found.
