#!/usr/bin/env bash
# Single bootstrap check entrypoint used locally, in CI and in the container smoke build.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 tools/check_foundation.py
uv run ruff check packages services tests
uv run ruff format --check packages services tests
uv run mypy
uv run python -m archipelago_contracts.export --check
uv run pytest -q
npm run gen:check -w @archipelago/contracts
npm run lint
npm run typecheck
npm test
npm run build
