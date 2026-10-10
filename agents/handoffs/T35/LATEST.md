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

## Implementation checkpoint
Completed: 16 live experiment panels, phase annotations, safe run_id SQL selector; legacy selector/units/empty labels/time filtering fixed. Canonical events carry phase; no nonexistent metrics.phase reference. Provisioning still uses existing env-only datasource. Local Compose now requires env passwords and rejects any datasource username other than archipelago_reader; initializes SELECT-only login on a fresh database.

Tests authored: migrated table/column extraction + SQLite EXPLAIN and empty queries; phase isolation, peer counts/reasons, update counts, null loss, policy versions, fault phases and persistence drops; JSON/YAML structure/units/datasource resolution/env guard; conditional real TimescaleDB migration+EXPLAIN+empty execution and reader write denial. Static path always executes; absent Docker gives an explicit warning, no skip/xfail.

Validation executed in tool JS: JSON serialize/parse of generated live dashboard, 16 unique panel ids, all paths inside reservation; API reads verified schema/contract field names. These are construction checks, not pytest/lint passes.
Validation NOT RUN: all uv, ruff, mypy, make, Docker and Grafana checks listed above. No local process can launch; environment failure occurs before a command runs. No ledger transition made. Status remains WIP / validation blocked, not REVIEW.

Files modified:
- observability/grafana/dashboards/live-experiment.json
- observability/grafana/dashboards/archipelago.json
- observability/docker-compose.yml
- observability/grafana/init-reader.sh
- observability/grafana/require-reader.sh
- observability/README.md
- tests/observability/test_dashboards.py
- agents/handoffs/T35/LATEST.md

Decisions/limitations:
- No new third-party dependency. Tests use existing pytest/PyYAML and psycopg; SQLite stdlib validates the supported query subset, not all PostgreSQL grammar.
- Metric names telemetry_backlog and telemetry_dropped must be emitted by live producers; coordinate names before integration, do not silently relabel missing data.
- LearningEvent has no sender property; dashboard shows deciding node, reason and candidate score rather than invented sender provenance.
- Production database operator must enable reader LOGIN out of band and retain only migration SELECT grants. Local bootstrap is not executed here.
- No changes to infra/services/migrations/manifests/CI/ledger, no cloud resource creation, no merge.

Next executable actions for Claude verifier:
1. Checkout this exact pushed WIP commit in an isolated worktree, uv sync --frozen.
2. uv run pytest tests/observability -q; capture whether Docker path ran. Do not treat absent Docker as real database validation.
3. uv run ruff check packages services tests; uv run ruff format --check packages services tests; uv run mypy; make check-integration. Apply any required formatter repair only in T35 paths.
4. Run local Grafana with required env secrets, verify reader-only setup and empty/data panel renders. Existing databases require operator initialization.
5. Confirm runtime metric names and integrate through Claude only after independent verification.
