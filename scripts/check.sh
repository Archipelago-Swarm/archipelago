#!/usr/bin/env bash
# Integration-tier gate used locally, in CI and in the container smoke build.
# SKIP_DOCKER=1 deselects tests marked 'docker' (no daemon on this machine); 'make check-full' and CI run them.
# CHECK_PART selects one slice (default: all, in order). Single source of truth for local use and CI:
#   lint     static checks, cheapest first: foundation, ledger, ruff, format, contract drift, mypy
#   gate     lint + fast torch-free deterministic tests (the PR gate; seconds to ~1 min)
#   smoke    import + API health in a clean install (used inside the container smoke image)
#   py-live  pytest for the heavy live-runtime suites (learning, noderuntime, coordinator, experiments)
#   py-rest  pytest for everything else (non-docker)
#   docker   docker-marked tests only
#   web      npm gen:check, lint, typecheck, test, build
set -euo pipefail
cd "$(dirname "$0")/.."
PART="${CHECK_PART:-all}"
LIVE=(tests/learning tests/noderuntime tests/coordinator tests/experiments tests/swarm)
IGNORE_LIVE=()
for d in "${LIVE[@]}"; do IGNORE_LIVE+=("--ignore=$d"); done

FAST=(tests/agents/test_controller.py tests/contracts tests/sim tests/api tests/transport)
LINT_PATHS=(packages services tests infra/vultr experiments agents/controller.py agents/launch.py)

part() { [ "$PART" = all ] || [ "$PART" = "$1" ]; }

if [ "$PART" = format ]; then
  uv run ruff format "${LINT_PATHS[@]}"
  uv run ruff check --fix "${LINT_PATHS[@]}"
  exit 0
fi
if part lint || [ "$PART" = gate ]; then
  python3 tools/check_foundation.py
  uv run python agents/controller.py validate
  uv run ruff check "${LINT_PATHS[@]}"
  uv run ruff format --check "${LINT_PATHS[@]}"
  uv run python -m archipelago_contracts.export --check
  uv run mypy
fi
if [ "$PART" = gate ]; then
  uv run pytest -q -m "not docker" "${FAST[@]}"
fi
if [ "$PART" = smoke ]; then
  uv run python -c "import archipelago_contracts, archipelago_api.app"
  uv run pytest -q -m "not docker" tests/api/test_api.py
fi
if part py-live; then
  uv run pytest -q -m "not docker" --durations=10 "${LIVE[@]}"
fi
if part py-rest; then
  uv run pytest -q -m "not docker" --durations=10 "${IGNORE_LIVE[@]}"
fi
if [ "$PART" = docker ] || { [ "$PART" = all ] && [ "${SKIP_DOCKER:-}" != "1" ]; }; then
  uv run pytest -q -m docker
fi
if part web; then
  npm run gen:check -w @archipelago/contracts
  npm run lint
  npm run typecheck
  npm test
  npm run build
fi
