#!/bin/sh
# PostgreSQL init runs this only for a new, empty local database.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\getenv reader_password TIGERDATA_GRAFANA_PASSWORD
ALTER ROLE archipelago_reader LOGIN PASSWORD :'reader_password';
ALTER ROLE archipelago_reader SET default_transaction_read_only = on;
SQL
