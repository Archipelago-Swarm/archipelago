# Handoff: T10 / prep (machine B, static packaging only)

- State: in_progress (prep branch, not a T10 assignment; deployment blocked)
- Run / machine / worker: B, T10 prep worker
- Branch / base commit: agent/B/T10/prep from origin/main 7999daf
- Resume from branch/commit: agent/B/T10/prep (pushed)
- Reserved paths: infra/, agents/handoffs/T10/ (task card dependencies T03,T04,T05,T06,T08 not all confirmed merged; A must record an assignment before this is used)

## Intended outcome and acceptance

T10 acceptance (task card): compose validation and four-node smoke, no anonymous mutation or public DB/peer ports, actual Vultr evidence, restart recovery, verified rollback, spend status. None of the acceptance checks is met yet; this prep only writes artifacts.

## Written (not verified by running)

- `infra/docker/api.Dockerfile`, `web.Dockerfile`, `node.Dockerfile` (multi-stage, non-root, healthchecks; node image is a PLACEHOLDER: no `archipelago_node` entrypoint and packages/node is not a uv workspace member).
- `infra/compose/compose.yml` (proxy, web, api, grafana, node-01..04, timescaledb under profile `local`), `infra/compose/.env.example`.
- `infra/proxy/Caddyfile` (TLS, security headers, routes /v1,/healthz,/readyz to api, /grafana to grafana), `infra/proxy/web-nginx.conf`.
- `infra/scripts/smoke.sh` (black-box checks incl. anonymous rejection and closed ports).
- `infra/runbooks/`: `vultr-deploy.md`, `rollback-teardown.md`, `budget-guard.md`, `smoke-checks.md`.

## Validation

Working dir: C:\archipelago\.agent-runtime\worktrees\T10prep.
- Compose YAML parsed with PyYAML via `py`: services listed, all referenced networks/volumes declared, only `proxy` publishes ports, nodes sit only on the internal `peers` network with their own volume, cap_drop ALL. PASS (structure only).
- Dockerfile instruction/continuation sanity script: PASS (not a real build).
- `bash -n infra/scripts/smoke.sh`: PASS (syntax only).
- NOT RUN: `docker compose config`, any `docker build`, hadolint, Caddyfile validation (`caddy validate`), `shellcheck`, smoke.sh against a stack, local four-node smoke, migrations, restart recovery, rollback, any Vultr or TigerData action. No cloud spend, no installs.

## Known gaps / decisions

- Node image cannot build until a node entrypoint exists and is in uv.lock.
- API: login cookie `secure=False` (app.py, comment says T10); needs `secure=True` behind TLS, outside T10 paths, needs A to serialize.
- psycopg is not a locked runtime dependency (see T08 handoff); `TIGERDATA_URL` is passed to api but nothing consumes it until that wiring exists. Simulation coordinator is not a compose service.
- `api.Dockerfile` assumes `uv sync --frozen --no-dev --package archipelago-api` works with the workspace lock (unverified); web Dockerfile `npm ci` with workspace flags unverified (npm ci is typically root-level; adjust if it fails).
- Images are built on the host (no registry, no cost); ghcr is an alternative.
- Grafana is served under /grafana with its own login; anonymous disabled.

## Human actions needed

1. Approve host or budget cap (see `infra/runbooks/budget-guard.md`); supply Vultr access out of band.
2. Create TigerData service and supply writer/reader TLS connection strings; run migrations 0001/0002 as admin.
3. DNS name for the host.
4. A Docker-capable machine (or the host) to run `docker compose config`, builds and the local four-node smoke.
5. A to assign T10 formally and unblock the shared-file changes above.

## Next steps

1. On a Docker machine: `docker compose -f infra/compose/compose.yml --env-file infra/compose/.env.example --profile local config -q` (set required secrets in a copy first).
2. Build api and web images; fix any path/lock issues; run local smoke.
3. After node entrypoint lands, build node image; extend smoke.sh with the designed checks.
4. Follow `infra/runbooks/vultr-deploy.md` only after the gates.

## Update run 20261010T154653Z (machine B)

- Added `tests/infra/test_compose.py`: runs real `docker compose config --format json` (dummy secrets, `.env.example`) for default and `local` profiles; asserts only `proxy` publishes ports and the four nodes have distinct volumes and sit only on the internal `peers` network. `py -m pytest tests/infra -q`: 3 passed.
- `docker compose config` is now actually verified (it needs `ARCHIPELAGO_API_TOKEN` and `GRAFANA_ADMIN_PASSWORD` set). Still NOT RUN: image builds, smoke.sh, restart recovery, rollback, any Vultr/TigerData step.

## Supervisor checkpoint 2026-10-10T15:47:01Z

- Run: 20261010T154653Z
- Machine: B
- Task/branch: T10 / agent/B/20261010T154653Z/T10
- Base: 45bdc473257fb74683742baf82491ac07808a592
- Round: 1
- State: in_progress
- External check exit: 1
- Independent review: not run
- Next issue: External checks failed (exit 1); inspect local check log
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Supervisor checkpoint 2026-10-10T15:47:35Z

- Run: 20261010T154653Z
- Machine: B
- Task/branch: T10 / agent/B/20261010T154653Z/T10
- Base: 45bdc473257fb74683742baf82491ac07808a592
- Round: 2
- State: in_progress
- External check exit: 1
- Independent review: not run
- Next issue: External checks failed (exit 1); inspect local check log
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Supervisor checkpoint 2026-10-10T15:49:19Z

- Run: 20261010T154653Z
- Machine: B
- Task/branch: T10 / agent/B/20261010T154653Z/T10
- Base: 45bdc473257fb74683742baf82491ac07808a592
- Round: 3
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["Most T10 acceptance checks have no implementation evidence. The handoff (agents/handoffs/T10/LATEST.md) says image builds, smoke.sh, restart recovery, rollback and any Vultr/TigerData step were NOT RUN.", "Check 1 is partly met. `docker compose config` is verified by tests/infra/test_compose.py, but no image has been built and there is no local four-node integration smoke. The node image is a placeholder with no node entrypoint, and packages/node is not a uv workspace member.", "Check 2 has only static evidence. Compose config tests show only the proxy publishes ports. smoke.sh has never run against a stack, so there is no evidence that anonymous mutation endpoints are rejected. Per the handoff, the API login cookie is secure=False.", "Check 3 has no evidence. There is no Vultr URL, deployed commit or image tags, or TigerData connection evidence. The handoff lists the host/budget approval, DNS and TigerData credentials as outstanding human actions.", "Checks 4 and 5 have no evidence. No restart-recovery or replay-retrievability test exists, no rollback was verified, and no resource inventory or spend status was recorded.", "Check 6 is not satisfied. Local packaging is declared incomplete by its own handoff: the node image can't build, the api/web Dockerfiles and the uv/npm workspace flags are unverified, and psycopg and TIGERDATA_URL are not wired. The deployment-blocked state is also not recorded as a final handoff.", "The task card still reads 'Status: waiting', 'unclaimed' and 'Latest handoff: none'. The handoff says the work is a prep branch, not a formal T10 assignment. The latest handoff checkpoints record 'Independent review: not run' and external check exit 1.", "tests/infra/test_compose.py has uncommitted changes. They are formatting only (ruff reformat), which is harmless. The 3 skipped tests in the external run are probably these tests, skipped for lack of docker, so even the static compose evidence may not have been exercised in that run."]}
- Next issue: Most T10 acceptance checks have no implementation evidence. The handoff (agents/handoffs/T10/LATEST.md) says image builds, smoke.sh, restart recovery, rollback and any Vultr/TigerData step were NOT RUN.; Check 1 is partly met. `docker compose config` is verified by tests/infra/test_compose.py, but no image has been built and there is no local four-node integration smoke. The node image is a placeholder with no node entrypoint, and packages/node is not a uv workspace member.; Check 2 has only static evidence. Compose config tests show only the proxy publishes ports. smoke.sh has never run against a stack, so there is no evidence that anonymous mutation endpoints are rejected. Per the handoff, the API login cookie is secure=False.; Check 3 has no evidence. There is no Vultr URL, deployed commit or image tags, or TigerData connection evidence. The handoff lists the host/budget approval, DNS and TigerData credentials as outstanding human actions.; Checks 4 and 5 have no evidence. No restart-recovery or replay-retrievability test exists, no rollback was verified, and no resource inventory or spend status was recorded.; Check 6 is not satisfied. Local packaging is declared incomplete by its own handoff: the node image can't build, the api/web Dockerfiles and the uv/npm workspace flags are unverified, and psycopg and TIGERDATA_URL are not wired. The deployment-blocked state is also not recorded as a final handoff.; The task card still reads 'Status: waiting', 'unclaimed' and 'Latest handoff: none'. The handoff says the work is a prep branch, not a formal T10 assignment. The latest handoff checkpoints record 'Independent review: not run' and external check exit 1.; tests/infra/test_compose.py has uncommitted changes. They are formatting only (ruff reformat), which is harmless. The 3 skipped tests in the external run are probably these tests, skipped for lack of docker, so even the static compose evidence may not have been exercised in that run.
- Resume: fetch this branch, inspect latest commit and continue the task card.
