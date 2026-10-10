#!/bin/sh
set -eu
if [ "${TIGERDATA_GRAFANA_USER:-}" != "archipelago_reader" ]; then
    echo "Grafana requires the archipelago_reader database role" >&2
    exit 1
fi
exec /run.sh
