#!/usr/bin/env bash
# Pre-push gate: lint plus only the test directories whose code changed against origin/main.
# CI still runs every slice; this is for agents to avoid pushing red without paying for the full suite.
set -euo pipefail
cd "$(dirname "$0")/.."
BASE="${1:-origin/main}"
CHANGED=$(git diff --name-only "$(git merge-base HEAD "$BASE")" HEAD; git diff --name-only; git ls-files -o --exclude-standard)
CHECK_PART=lint scripts/check.sh
DIRS=()
for d in tests/*/; do
  n=$(basename "$d")
  [ "$n" = e2e ] && continue
  if echo "$CHANGED" | grep -Eq "(^|/)(${n}|archipelago_${n})(/|_|\.)"; then DIRS+=("$d"); fi
done
if echo "$CHANGED" | grep -Eq '^(pyproject.toml|uv.lock|packages/contracts/)'; then DIRS=(tests); fi
if [ ${#DIRS[@]} -eq 0 ]; then echo "no affected test directories"; exit 0; fi
echo "affected: ${DIRS[*]}"
uv run pytest -q -m "not docker" "${DIRS[@]}"
