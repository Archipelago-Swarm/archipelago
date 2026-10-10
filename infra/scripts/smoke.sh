#!/usr/bin/env bash
# Smoke check for a deployed (or local) stack. NOT RUN: written without Docker or a host.
# Usage: BASE_URL=https://demo.example.com API_TOKEN=... infra/scripts/smoke.sh
# Exit 0 only if every check passes; prints one PASS/FAIL line per check. No secrets are printed.
set -u
BASE_URL="${BASE_URL:?set BASE_URL}"
API_TOKEN="${API_TOKEN:?set API_TOKEN}"
CURL=(curl -sS --max-time 10 ${SMOKE_CURL_OPTS:-})
fail=0
check() { # name, expected, actual
  if [ "$2" = "$3" ]; then echo "PASS $1"; else echo "FAIL $1 (expected $2, got $3)"; fail=1; fi
}
code() { "${CURL[@]}" -o /dev/null -w '%{http_code}' "$@" || true; }

check "healthz"                   200 "$(code "$BASE_URL/healthz")"
check "readyz"                    200 "$(code "$BASE_URL/readyz")"
check "web index"                 200 "$(code "$BASE_URL/")"
# No anonymous mutation or read of run data.
check "anon create run rejected"  401 "$(code -X POST -H 'content-type: application/json' -d '{}' "$BASE_URL/v1/runs")"
check "anon get run rejected"     401 "$(code "$BASE_URL/v1/runs/none")"
check "bad login rejected"        401 "$(code -X POST -H 'content-type: application/json' -d '{"token":"wrong-wrong-wrong-wrong"}' "$BASE_URL/v1/login")"
check "good login"                200 "$(code -X POST -H 'content-type: application/json' -d "{\"token\":\"$API_TOKEN\"}" "$BASE_URL/v1/login")"
# HTTP must redirect or refuse, never serve the API in clear text.
http_url="http://${BASE_URL#https://}"
hc="$(code --max-redirs 0 "$http_url/v1/runs/none")"
case "$hc" in 301|302|307|308|000) echo "PASS http not served in clear ($hc)";; *) echo "FAIL http served in clear ($hc)"; fail=1;; esac
# Grafana must require a login.
gc="$(code "$BASE_URL/grafana/api/dashboards/home")"
case "$gc" in 401|302) echo "PASS grafana requires login ($gc)";; *) echo "FAIL grafana anonymous ($gc)"; fail=1;; esac
# Public ports: only 80/443 may answer (run from outside the host).
if [ -n "${HOST_IP:-}" ]; then
  for p in 22 5432 3000 8000 9000; do
    if [ "$p" != 22 ] && (exec 3<>"/dev/tcp/$HOST_IP/$p") 2>/dev/null; then echo "FAIL port $p open"; fail=1; else echo "PASS port $p closed"; fi
  done
fi
# TODO once T03/T05/T08 wiring exists: create a 4-node run via POST /v1/runs, step it, read events,
# restart a node container, confirm its checkpoint index is unchanged, fetch the replay, and query
# TigerData for the run row. See infra/runbooks/smoke-checks.md.
exit "$fail"
