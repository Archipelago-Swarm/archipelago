#!/usr/bin/env bash
# Integration-tier gate used locally, in CI and in the container smoke build.
# SKIP_DOCKER=1 deselects tests marked 'docker' (no daemon on this machine); 'make check-full' and CI run them.
# CHECK_PART selects one slice so CI can run the slices as parallel jobs (default: all, in order):
#   lint     foundation, ledger, ruff, mypy, contract drift
#   py-live  pytest for the heavy live-runtime suites (learning, noderuntime, coordinator, experiments)
#   py-rest  pytest for everything else (non-docker)
#   docker   docker-marked tests only
#   web      npm gen:check, lint, typecheck, test, build
set -euo pipefail
cd "$(dirname "$0")/.."
PART="${CHECK_PART:-all}"
LIVE=(tests/learning tests/noderuntime tests/coordinator tests/experiments)
IGNORE_LIVE=()
for d in "${LIVE[@]}"; do IGNORE_LIVE+=("--ignore=$d"); done

part() { [ "$PART" = all ] || [ "$PART" = "$1" ]; }

if part lint; then
  python3 tools/check_foundation.py
  uv run python agents/controller.py validate
  uv run ruff check packages services tests infra/vultr experiments agents/controller.py agents/launch.py
  uv run ruff format --check packages services tests infra/vultr experiments agents/controller.py agents/launch.py
  uv run mypy
  uv run python -m archipelago_contracts.export --check
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
