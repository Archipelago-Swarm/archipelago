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

## Update run 20261010T154653Z, round 2 (machine B, Docker daemon available)

- RAN: `docker build` of `api.Dockerfile` and `web.Dockerfile` both succeed (so the `uv sync --frozen --package archipelago-api` and web `npm ci` assumptions hold). The api container started, `/healthz` 200; anonymous `POST /v1/runs`, `POST /v1/runs/x/commands`, `GET /v1/runs/x`, `GET /v1/runs/x/events` all 401.
- Added `tests/infra/test_api_image.py` (build + run + anonymous-401 check); `py -m pytest tests/infra -q`: 4 passed (not skipped; docker present). Not formatted with ruff (not installed here).
- Still NOT RUN: node image build (placeholder, no entrypoint), full compose stack up, smoke.sh against a stack, restart recovery, replay retrievability, rollback, any Vultr/TigerData step, spend inventory. The API login cookie is still `secure=False` (outside T10 paths).
- Task card still reads waiting/unclaimed; A must assign T10 formally. Deployment is blocked on the human actions above.

## Supervisor checkpoint 2026-10-10T15:53:30Z

- Run: 20261010T154653Z
- Machine: B
- Task/branch: T10 / agent/B/20261010T154653Z/T10
- Base: 45bdc473257fb74683742baf82491ac07808a592
- Round: 4
- State: in_progress
- External check exit: 1
- Independent review: not run
- Next issue: External checks failed (exit 1); inspect local check log
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Supervisor checkpoint 2026-10-10T15:55:46Z

- Run: 20261010T154653Z
- Machine: B
- Task/branch: T10 / agent/B/20261010T154653Z/T10
- Base: 45bdc473257fb74683742baf82491ac07808a592
- Round: 5
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["Acceptance checks are all still unchecked in the task card, and the task status is still 'waiting'.", "The handoff (agents/handoffs/T10/LATEST.md) says none of the acceptance checks are met. The images were not built before the latest update, and smoke.sh, the local four-node smoke, restart recovery and rollback were never run. Only 'docker compose config' and the api image anonymous-rejection test are verified.", "There is no evidence of an actual Vultr URL, commit-tagged images, or a TigerData connection. The deployment is blocked on human actions (host or budget approval, TigerData strings, DNS). Local packaging is not complete either, so the blocked-fallback check is not satisfied.", "The node image is a placeholder: there is no archipelago_node entrypoint, and packages/node is not a uv workspace member. The four-node integration smoke cannot run with real nodes.", "web.Dockerfile and the 'npm ci' workspace invocation are unverified. The handoff lists the web build as not run; only the api image build has a test.", "TIGERDATA_URL is passed to the API, but nothing consumes it because psycopg is not a locked runtime dependency. TigerData metrics are not wired.", "The API login cookie is secure=False (noted in app.py as a T10 item), so HTTPS-only auth is incomplete. The fix is outside T10's allowed paths and was never serialized through the integrator.", "The api image test needs Docker. The external check output shows '3 skipped', which probably includes the Docker-dependent tests, so the image and compose tests may not have run in the gating check.", "The handoff has stale 'Independent review: not run' checkpoints with external check exit 1. A checkpoint for the passing run and the evidence of the final state are missing.", "tests/infra/test_api_image.py has an uncommitted working-tree change (line-length reformatting). Commit it, or the pushed branch will not match what was checked."]}
- Next issue: Acceptance checks are all still unchecked in the task card, and the task status is still 'waiting'.; The handoff (agents/handoffs/T10/LATEST.md) says none of the acceptance checks are met. The images were not built before the latest update, and smoke.sh, the local four-node smoke, restart recovery and rollback were never run. Only 'docker compose config' and the api image anonymous-rejection test are verified.; There is no evidence of an actual Vultr URL, commit-tagged images, or a TigerData connection. The deployment is blocked on human actions (host or budget approval, TigerData strings, DNS). Local packaging is not complete either, so the blocked-fallback check is not satisfied.; The node image is a placeholder: there is no archipelago_node entrypoint, and packages/node is not a uv workspace member. The four-node integration smoke cannot run with real nodes.; web.Dockerfile and the 'npm ci' workspace invocation are unverified. The handoff lists the web build as not run; only the api image build has a test.; TIGERDATA_URL is passed to the API, but nothing consumes it because psycopg is not a locked runtime dependency. TigerData metrics are not wired.; The API login cookie is secure=False (noted in app.py as a T10 item), so HTTPS-only auth is incomplete. The fix is outside T10's allowed paths and was never serialized through the integrator.; The api image test needs Docker. The external check output shows '3 skipped', which probably includes the Docker-dependent tests, so the image and compose tests may not have run in the gating check.; The handoff has stale 'Independent review: not run' checkpoints with external check exit 1. A checkpoint for the passing run and the evidence of the final state are missing.; tests/infra/test_api_image.py has an uncommitted working-tree change (line-length reformatting). Commit it, or the pushed branch will not match what was checked.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Update run 20261010T154653Z (worker, final)

- Docker 29.8.2 is available. `py -m pytest tests/infra -q`: 4 passed, 0 skipped (compose config and api image tests really ran).
- `docker build -f infra/docker/web.Dockerfile -t archipelago-web:t10 .` succeeded (npm ci workspace invocation works).
- Reformatted `tests/infra/test_api_image.py` (line length only); needs to be committed with this update.
- Still NOT MET: all acceptance checks. Not run: smoke.sh, four-node smoke, restart recovery, rollback, Vultr/TigerData. Node image still a placeholder; psycopg wiring and cookie `secure=True` are outside T10 paths and need the integrator.
- Deployment remains blocked on the human actions listed above; local packaging is partial (api + web images build; node image does not).

## Supervisor checkpoint 2026-10-10T15:57:29Z

- Run: 20261010T154653Z
- Machine: B
- Task/branch: T10 / agent/B/20261010T154653Z/T10
- Base: 45bdc473257fb74683742baf82491ac07808a592
- Round: 6
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["The worker's own final handoff update says every acceptance check is NOT MET. The task card checkboxes are all unchecked and status is still 'waiting'.", "No local four-node integration smoke has been run. smoke.sh was not run, and the node image is a placeholder with no real archipelago_node entrypoint. Compose validation exists, but it is only one part of the first check.", "No evidence of restart recovery (checkpoints preserved, replay retrievable) or of a verified rollback.", "No actual Vultr URL, commit-tagged images, TigerData connection, or resource and spend inventory is recorded. The deployment is blocked on human actions (host or budget approval, TigerData strings, DNS).", "The blocked-fallback check requires local packaging to be complete. It is not: the node image does not build into a working node. TIGERDATA_URL is not consumed because psycopg is not wired, and the login cookie is still secure=False, which leaves authenticated HTTPS incomplete.", "Uncommitted changes remain in the worktree: agents/handoffs/T10/LATEST.md and infra/docker/web.Dockerfile, plus the test reformat the handoff mentions. The branch does not match what was checked."]}
- Next issue: The worker's own final handoff update says every acceptance check is NOT MET. The task card checkboxes are all unchecked and status is still 'waiting'.; No local four-node integration smoke has been run. smoke.sh was not run, and the node image is a placeholder with no real archipelago_node entrypoint. Compose validation exists, but it is only one part of the first check.; No evidence of restart recovery (checkpoints preserved, replay retrievable) or of a verified rollback.; No actual Vultr URL, commit-tagged images, TigerData connection, or resource and spend inventory is recorded. The deployment is blocked on human actions (host or budget approval, TigerData strings, DNS).; The blocked-fallback check requires local packaging to be complete. It is not: the node image does not build into a working node. TIGERDATA_URL is not consumed because psycopg is not wired, and the login cookie is still secure=False, which leaves authenticated HTTPS incomplete.; Uncommitted changes remain in the worktree: agents/handoffs/T10/LATEST.md and infra/docker/web.Dockerfile, plus the test reformat the handoff mentions. The branch does not match what was checked.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Update run 20261010T154653Z (machine B), local stack smoke

- Real `docker compose up --build proxy web api grafana` on local Docker 29.8: api, web images build; api, web healthy. `infra/scripts/smoke.sh` (BASE_URL=https://localhost, curl -k) now passes all 9 checks (health, ready, web, anon create/get rejected, bad/good login, HTTP->308, grafana 401). Stack torn down with `down -v`.
- Fixed two real bugs found by running: proxy crash-looped (`cap_drop ALL` blocked caddy's file capability: added `cap_add: NET_BIND_SERVICE`; empty `ACME_EMAIL` broke the Caddyfile `email`: compose now defaults it). smoke.sh `code()` printed `000000` on curl failure.
- `py -m pytest tests/infra -q`: 4 passed (before the compose edit; compose test not re-run after).
- Still NOT MET: four-node smoke (node image placeholder, no entrypoint), restart recovery, rollback, any Vultr/TigerData evidence, spend inventory. Secure cookie / psycopg gaps unchanged (outside reserved paths).

## Supervisor checkpoint 2026-10-10T16:01:27Z

- Run: 20261010T154653Z
- Machine: B
- Task/branch: T10 / agent/B/20261010T154653Z/T10
- Base: 45bdc473257fb74683742baf82491ac07808a592
- Round: 7
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["The latest handoff update says four-node smoke, restart recovery, rollback, Vultr/TigerData evidence and spend inventory are all still NOT MET. No evidence in the worktree contradicts that.", "Acceptance check 1 is only partly met. The 9-check smoke ran against the proxy, web, api and grafana services only. There is no four-node integration smoke, and the node image is a placeholder with no real entrypoint.", "Acceptance check 2 is only partly met. Anonymous create/get rejection and Grafana 401 were smoke-tested locally, but no evidence shows the DB and peer ports are not public in the production profile.", "No evidence of restart recovery: checkpoints preserved and replay retrievable after a container restart.", "No evidence of a verified rollback to the previous image, and no commit-tagged image deployment.", "No Vultr URL, TigerData connection evidence, or resource/spend inventory is recorded.", "The blocked-fallback check requires local packaging to be complete, and it is not. The node image is a stub, TIGERDATA_URL is not consumed (psycopg not wired), and the login cookie is still secure=False, so authenticated HTTPS is incomplete.", "The compose.yml and smoke.sh fixes and the handoff update are uncommitted. The tests/infra run (4 passed) predates the compose edit and was not re-run, so there is no test coverage of the new compose.", "The task card status is still 'waiting' and every checkbox is unchecked."]}
- Next issue: The latest handoff update says four-node smoke, restart recovery, rollback, Vultr/TigerData evidence and spend inventory are all still NOT MET. No evidence in the worktree contradicts that.; Acceptance check 1 is only partly met. The 9-check smoke ran against the proxy, web, api and grafana services only. There is no four-node integration smoke, and the node image is a placeholder with no real entrypoint.; Acceptance check 2 is only partly met. Anonymous create/get rejection and Grafana 401 were smoke-tested locally, but no evidence shows the DB and peer ports are not public in the production profile.; No evidence of restart recovery: checkpoints preserved and replay retrievable after a container restart.; No evidence of a verified rollback to the previous image, and no commit-tagged image deployment.; No Vultr URL, TigerData connection evidence, or resource/spend inventory is recorded.; The blocked-fallback check requires local packaging to be complete, and it is not. The node image is a stub, TIGERDATA_URL is not consumed (psycopg not wired), and the login cookie is still secure=False, so authenticated HTTPS is incomplete.; The compose.yml and smoke.sh fixes and the handoff update are uncommitted. The tests/infra run (4 passed) predates the compose edit and was not re-run, so there is no test coverage of the new compose.; The task card status is still 'waiting' and every checkbox is unchecked.
- Resume: fetch this branch, inspect latest commit and continue the task card.
