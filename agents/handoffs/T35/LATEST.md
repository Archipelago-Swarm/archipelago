# T35 checkpoint
Status: WIP implementation; acceptance NOT RUN. Owner: codex/T35, machine A.
Branch: agent/T35-grafana-live-experiment-dashboar
Base: 90f99b23df516928431816e2a2e52097728686bf (claude/elegant-pascal-a8a3hp)
Last good implementation commit: none.

Objective: provision live experiment Grafana panels with reader-only access and schema validation.
Plan: query canonical events.payload for phase-aware metrics and learning decisions; preserve existing metrics panels; validate every SQL query against migrated schema statically and with TimescaleDB when Docker is available; publish draft for independent execution.
Reserved paths: observability/**, tests/observability/**, this handoff only.
Dependencies: none; integration owner is Claude.

Attempted command: Get-Location via exec_command. No exit code: process creation rejected with helper_unknown_error: setup refresh had errors.
Not run: uv sync --frozen; uv run pytest tests/observability -q; uv run ruff check packages services tests; uv run ruff format --check packages services tests; uv run mypy; make check-integration; Docker/Grafana.
Acceptance: no PASS or REVIEW claim. API-only edits are possible; independent runner must execute acceptance.
Decisions: metrics table lacks phase, so live curves read canonical metric_sample payload from events. No schema/public-contract change, dependency addition, cloud spending or ledger edit.
Next: implement scoped files and tests, push WIP checkpoint and ask integrator to execute checks before review.
