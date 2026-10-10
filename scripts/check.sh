#!/usr/bin/env bash
# Integration-tier gate used locally, in CI and in the container smoke build.
# SKIP_DOCKER=1 deselects tests marked 'docker' (no daemon on this machine); 'make check-full' and CI run them.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 tools/check_foundation.py
uv run python agents/controller.py validate
uv run ruff check packages services tests agents/controller.py agents/launch.py
uv run ruff format --check packages services tests agents/controller.py agents/launch.py
uv run mypy
uv run python -m archipelago_contracts.export --check
if [ "${SKIP_DOCKER:-}" = "1" ]; then
  uv run pytest -q -m "not docker"
else
  uv run pytest -q
fi
npm run gen:check -w @archipelago/contracts
npm run lint
npm run typecheck
npm test
npm run build
