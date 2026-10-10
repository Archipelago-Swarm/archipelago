# Vultr and TigerData operations tooling (T34)

Stdlib plus `psycopg`. Nothing here creates cloud resources: the Vultr client is GET-only and all
host work is plain `ssh`. Secrets come only from the environment and never reach logs or reports.
Run from the repo root with `PYTHONPATH=infra/vultr` (or `cd infra/vultr`).

Environment: `VULTR_API_KEY`, `OPERATOR_IP`, `ARCHIPELAGO_API_TOKEN`, `GRAFANA_ADMIN_PASSWORD`,
`TIGERDATA_URL` (writer login), `TIGERDATA_READER_URL`, `TIGERDATA_ADMIN_URL` (owner, migrations),
`TIGERDATA_GRAFANA_*`, `SITE_ADDRESS`, `ACME_EMAIL`. All steps accept `--evidence-dir` (default `evidence/`).

## Steps and evidence

| Step | Command | Evidence written |
|---|---|---|
| 1 inventory | `python -m archipelago_ops inventory` | `inventory.json` (balance, pending, instances, plan prices) |
| 2 record start | `python -m archipelago_ops record-start` (once, before any spend) | `spend-start.json` |
| 3 guard | `python -m archipelago_ops guard --plan plan.json` | `guard-report.json` (computed costs); exit 0 pass, 2 limit violated (message names it), 3 refused |
| 4 TigerData | `python -m archipelago_ops tigerdata` | `tigerdata-report.json` (hosts and check results, no credentials); exit 1 on any failure |
| 5 bootstrap | `... deploy bootstrap --host H --identity-file KEY --ssh-user root` | `deploy-log.txt` |
| 6 deploy | `... deploy deploy --host H --identity-file KEY --manifest m.json` | `deploy-log.txt` |
| 7 smoke | `... deploy smoke --host H --identity-file KEY --manifest m.json` (runs `infra/scripts/smoke.sh` locally; needs `ARCHIPELAGO_API_TOKEN`) | `deploy-log.txt` |
| 8 rollback | `... deploy rollback --host H --identity-file KEY --previous-manifest prev.json` | `deploy-log.txt` |

`deploy` steps are dry-run by default (exact commands printed, secrets masked). Add `--execute
--inventory inventory.json --plan plan.json --start spend-start.json` to run: the guard is
evaluated first in the same invocation and any non-zero result stops everything.

## Plan file (`plan.json`)

```json
{"instances": [{"label": "arch-1", "plan": "vc2-2c-4gb", "duration_hours": 48}],
 "region": "ewr", "experiment_end": "2026-10-14T00:00:00Z",
 "approved": true, "expires_at": "2026-10-11T00:00:00Z", "plan_hash": "<sha256>"}
```

`plan_hash` is the sha256 of the canonical JSON (sorted keys, compact separators) of the plan without
`approved`, `plan_hash`, `expires_at`; compute it with
`python -c "from archipelago_ops.guard import plan_hash; import json,sys; print(plan_hash(json.load(open(sys.argv[1]))))" plan.json`.
Editing the plan after approval invalidates the hash. The operator creates instances by hand; the
plan only authorises the spend that guard evaluates. An empty `instances` list still needs approval.

## Cost formula (see `guard.py`)

`730` hours per month, safety multiplier `1.25`. Existing instances count at the full monthly price.
New instance: `min(monthly, monthly/730 * max(duration_hours, hours_to_experiment_end) * 1.25)`.
Projected monthly = existing + new (limit 200 USD). Projected cumulative = spend since the recorded
start (`|delta balance| + delta pending`) + existing instances' burn to experiment end (x1.25) + new
(limit 100 USD). Instances including existing: max 5. Exactly at a limit passes. Unknown plan fails.
Verify the account balance sign convention on the first real inventory; the absolute value is used.

## Release manifest

`{"release": "r1", "commit": "<40 hex>", "repo_url": "https://...", "images": {"api": "name@sha256:<64 hex>", "web": "...", "node": "..."}}`.
Deploy pulls each digest, tags it `archipelago/<svc>:<release>`, writes a 0600 env file
(`IMAGE_TAG=<release>`) and runs compose with `--no-build`. The host keeps `~/archipelago-deploy/current.json`
and `previous.json`. Rollback re-applies the previous manifest (compose files from its commit, no schema reversal).

## Tests

`uv run pytest infra/vultr/tests -q`. `test_tigerdata_integration.py` needs a Docker daemon (CI only).
