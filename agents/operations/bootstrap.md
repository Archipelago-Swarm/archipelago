# Workspace bootstrap (T01)

Recorded 2026-10-10 on computer A (Linux 6.18). Python 3.13.16 locally (CI pins 3.12; `requires-python >=3.12`), Node v22.22.0, npm 10.9.4, uv 0.11.32, Docker CLI 29.8.2 (no daemon reachable in the authoring sandbox).

## Commands (repo root)

```sh
uv sync --frozen && npm ci      # locked installs (uv.lock, package-lock.json)
scripts/check.sh                # everything CI runs: foundation docs, ruff, mypy, schema drift, pytest, TS drift/lint/typecheck/tests/build
npm run gen:types               # after `uv run python -m archipelago_contracts.export`
docker build -f infra/docker/ci.Dockerfile -t archipelago-ci . && docker run --rm archipelago-ci
```

## Shared-file owners (serialized; request via integrator A)

| Path | Owner |
|---|---|
| `pyproject.toml`, `uv.lock`, `package.json`, `package-lock.json` | integrator (A) |
| `packages/contracts/` (models, schemas, generated, fixtures) | integrator (A); contract changes need an ADR |
| `.github/workflows/`, `scripts/check.sh`, `infra/docker/ci.Dockerfile` | integrator (A) |

## Not validated here

The container smoke build was NOT run locally (no Docker daemon); first CI run is its evidence. `apps/web` is a scaffold that renders one fixture record, not the dashboard.
