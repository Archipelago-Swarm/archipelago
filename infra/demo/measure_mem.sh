#!/usr/bin/env bash
# Memory measurement of the CPU-wheel node image (CI / a host with Docker). NOT runnable without a daemon.
#
#   make demo-up PLAN=demo            # stack up, nothing running yet
#   infra/demo/measure_mem.sh demo    # starts a run, samples while it trains, prints the rule result
#   make demo-down
#
# Procedure: while a run is in progress, sample `docker stats` (cgroup memory incl. page cache) every 2 s and,
# after the run, read VmHWM (peak RSS) and RssAnon from /proc/1/status inside each container (PID 1 is the
# python runtime: exec-form ENTRYPOINT). The peak that sizes the limit is the largest VmHWM over the four nodes.
# Rule (amendment A16): limit = 1.5 x peak training RSS, rounded UP to a multiple of 64 MiB.
#
#   infra/demo/measure_mem.sh --rule <peak_mib>     # just apply the rule (offline)
set -euo pipefail

rule() { awk -v p="$1" 'BEGIN { l = p * 1.5; r = int(l / 64); if (r * 64 < l) r++; print r * 64 }'; }

if [ "${1:-}" = "--rule" ]; then
  rule "${2:?peak MiB}"
  exit 0
fi

PLAN="${1:-demo}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/artifacts/demo/mem"
mkdir -p "$OUT"
DC=(docker compose -p archipelago-demo -f "$ROOT/infra/compose/compose.yml"
    --env-file "$ROOT/infra/compose/.env.example" --env-file "$ROOT/infra/compose/local.env" --profile local)
export DEMO_PLAN="$PLAN"

python3 "$ROOT/infra/demo/run_demo.py" run --plan "$PLAN" &
RUN_PID=$!
echo "ts,container,mem_usage,mem_pct" > "$OUT/docker_stats.csv"
while kill -0 "$RUN_PID" 2>/dev/null; do
  docker stats --no-stream --format '{{.Name}},{{.MemUsage}},{{.MemPerc}}' \
    | grep -E 'node-0[1-4]' | sed "s/^/$(date -u +%FT%TZ),/" >> "$OUT/docker_stats.csv" || true
  sleep 2
done
wait "$RUN_PID" || echo "run exited non-zero; measuring what was reached" >&2

peak=0
echo "node,VmHWM_MiB,RssAnon_MiB" | tee "$OUT/vmhwm.csv"
for n in node-01 node-02 node-03 node-04; do
  status="$("${DC[@]}" exec -T "$n" cat /proc/1/status)"
  hwm_kb="$(awk '/^VmHWM:/ {print $2}' <<<"$status")"
  anon_kb="$(awk '/^RssAnon:/ {print $2}' <<<"$status")"
  hwm=$(( hwm_kb / 1024 ))
  echo "$n,$hwm,$(( anon_kb / 1024 ))" | tee -a "$OUT/vmhwm.csv"
  [ "$hwm" -gt "$peak" ] && peak="$hwm"
done
limit="$(rule "$peak")"
echo "peak_vmhwm_mib=$peak recommended_mem_limit_mib=$limit (1.5x peak rounded up to 64 MiB)" | tee "$OUT/result.txt"
echo "Set mem_limit: ${limit}m on node-01..04 in infra/compose/compose.yml (currently a provisional 1g)."
