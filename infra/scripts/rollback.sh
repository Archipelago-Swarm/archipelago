#!/usr/bin/env bash
# Roll the stack back to the previous image tag. No schema reversal, never removes volumes.
#   infra/scripts/rollback.sh <current-tag> <previous-tag>
# Env: COMPOSE_PROJECT (compose -p), COMPOSE_ENV_FILE (default infra/compose/.env),
#      ROLLBACK_SERVICES (default: web api node-01..node-04), COMPOSE_PROFILES (passed through).
# Idempotent: re-running with the same tags leaves the stack on the previous tag.
set -euo pipefail

usage() { echo "usage: $0 <current-tag> <previous-tag>" >&2; exit 2; }

[[ $# -eq 2 ]] || usage
CURRENT=$1
PREVIOUS=$2
[[ -n "$CURRENT" && -n "$PREVIOUS" ]] || usage
if [[ "$CURRENT" == "$PREVIOUS" ]]; then
  echo "refusing: current and previous tag are both '$CURRENT'" >&2
  exit 2
fi
tag_re='^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$'
for t in "$CURRENT" "$PREVIOUS"; do
  [[ "$t" =~ $tag_re ]] || { echo "refusing: invalid image tag '$t'" >&2; exit 2; }
done

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ENV_FILE=${COMPOSE_ENV_FILE:-$ROOT/infra/compose/.env}
read -r -a SERVICES <<<"${ROLLBACK_SERVICES:-web api node-01 node-02 node-03 node-04}"
compose=(docker compose)
if [[ -n "${COMPOSE_PROJECT:-}" ]]; then compose+=(-p "$COMPOSE_PROJECT"); fi
compose+=(-f "$ROOT/infra/compose/compose.yml" --env-file "$ENV_FILE")

# Verify every previous-tag image exists locally before touching anything.
for img in web api node; do
  if ! docker image inspect "archipelago/$img:$PREVIOUS" >/dev/null 2>&1; then
    echo "refusing: image archipelago/$img:$PREVIOUS not present locally; nothing changed" >&2
    exit 1
  fi
done

echo "rollback: $CURRENT -> $PREVIOUS (services: ${SERVICES[*]})"
# --no-build: only use the existing image; --no-deps: leave proxy/db/volumes alone.
IMAGE_TAG="$PREVIOUS" "${compose[@]}" up -d --no-build --no-deps "${SERVICES[@]}"
echo "rollback: services now on archipelago/*:$PREVIOUS; volumes untouched, no schema change"
echo "rollback: image archipelago/*:$CURRENT kept on host (do not prune until accepted)"
