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

## Update run 20261010T154653Z (worker, round 8)

- Re-ran `py -m pytest tests/infra -q` AFTER the compose edit; added `test_production_profile_has_no_local_db_and_hardened_proxy` (prod profile has no timescaledb, api receives TIGERDATA_URL, proxy cap_drop ALL + NET_BIND_SERVICE). Result recorded below in this session's run: see test output (5 expected).
- Evidence for check 2 (static): only `proxy` publishes ports in both profiles (existing test); DB and nodes sit on internal networks.
- Still NOT MET: four-node smoke, restart recovery, rollback, Vultr/TigerData evidence, spend inventory. Blockers unchanged: no node entrypoint (needs packages/node + uv.lock, outside T10 paths), psycopg wiring and `secure=True` cookie outside T10 paths; Vultr/TigerData need human credentials/budget.

## Supervisor checkpoint 2026-10-10T16:03:26Z

- Run: 20261010T154653Z
- Machine: B
- Task/branch: T10 / agent/B/20261010T154653Z/T10
- Base: 45bdc473257fb74683742baf82491ac07808a592
- Round: 8
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["The latest handoff, written by the worker, lists the four-node smoke, restart recovery, rollback, Vultr/TigerData evidence and spend inventory as NOT MET. Nothing in the worktree contradicts that.", "Acceptance check 1: there is no four-node integration smoke. The node image has no real entrypoint, so only a static Compose test and a proxy/web/api/grafana smoke exist.", "Acceptance check 2: the evidence is static only. A test shows that only the proxy publishes ports. No runtime evidence shows the DB and peer ports are not public. Authenticated HTTPS is incomplete because the login cookie is still secure=False.", "No evidence that a container restart preserves checkpoints or that the replay stays retrievable.", "No commit-tagged image deployment and no verified rollback to the previous image.", "No Vultr URL, TigerData connection evidence, or resource/spend inventory is recorded. TIGERDATA_URL is passed to the api but not consumed, because psycopg is not wired.", "The blocked-fallback check requires local packaging to be complete. It is not complete: the node image is a stub, and the psycopg wiring and secure cookie are outside the T10 allowed paths.", "The new test and the handoff update are uncommitted. The handoff does not record the test run result ('see test output').", "The task card is still status 'waiting' with every checkbox unchecked, so the task is not ready for a human PR review."]}
- Next issue: The latest handoff, written by the worker, lists the four-node smoke, restart recovery, rollback, Vultr/TigerData evidence and spend inventory as NOT MET. Nothing in the worktree contradicts that.; Acceptance check 1: there is no four-node integration smoke. The node image has no real entrypoint, so only a static Compose test and a proxy/web/api/grafana smoke exist.; Acceptance check 2: the evidence is static only. A test shows that only the proxy publishes ports. No runtime evidence shows the DB and peer ports are not public. Authenticated HTTPS is incomplete because the login cookie is still secure=False.; No evidence that a container restart preserves checkpoints or that the replay stays retrievable.; No commit-tagged image deployment and no verified rollback to the previous image.; No Vultr URL, TigerData connection evidence, or resource/spend inventory is recorded. TIGERDATA_URL is passed to the api but not consumed, because psycopg is not wired.; The blocked-fallback check requires local packaging to be complete. It is not complete: the node image is a stub, and the psycopg wiring and secure cookie are outside the T10 allowed paths.; The new test and the handoff update are uncommitted. The handoff does not record the test run result ('see test output').; The task card is still status 'waiting' with every checkbox unchecked, so the task is not ready for a human PR review.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Update run 20261010T154653Z (worker, round 9)

- `py -m pytest tests/infra -q` after the compose edit and the new prod-profile test: **5 passed in 3.59s** (replaces the "see test output" note above).
- No code changes this round. Remaining acceptance checks are blocked by things outside `infra/` and `tests/infra/`, or by human credentials:
  - Four-node smoke: needs an `archipelago_node` entrypoint, `packages/node` as a uv workspace member and a refreshed `uv.lock`.
  - Authenticated HTTPS: api login cookie is still `secure=False` (services/api).
  - TigerData: api does not consume `TIGERDATA_URL` (psycopg not wired).
  - Vultr URL, TigerData evidence, spend inventory, commit-tagged deploy and rollback: need human credentials and budget.
  - Restart recovery: depends on the node entrypoint.
- Task card status is the integrator's to change; left as is.

## Supervisor checkpoint 2026-10-10T16:04:57Z

- Run: 20261010T154653Z
- Machine: B
- Task/branch: T10 / agent/B/20261010T154653Z/T10
- Base: 45bdc473257fb74683742baf82491ac07808a592
- Round: 9
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["The latest handoff, written by the worker, lists the remaining acceptance checks as blocked or unmet. Nothing in the worktree contradicts that.", "Check 1: there is no local four-node integration smoke. The node image has no real entrypoint, and packages/node is not a uv workspace member. Only static Compose tests (5 tests in tests/infra) exist.", "Check 2: the evidence is static only. The api login cookie is still secure=False, so authenticated HTTPS is incomplete.", "Check 3: no Vultr URL, commit/image tags or TigerData connection evidence is recorded. The api does not consume TIGERDATA_URL because psycopg is not wired.", "Check 4: no evidence that a container restart preserves checkpoints or that the replay stays retrievable.", "Check 5: no verified rollback to the previous image and no resource or spend inventory.", "Check 6: the blocked-fallback condition requires complete local packaging, and it is not complete. The node entrypoint, psycopg wiring and secure cookie are outside the T10 allowed paths and have not been done.", "The handoff update is uncommitted (agents/handoffs/T10/LATEST.md is modified), and the task card is still 'waiting' with every checkbox unchecked."]}
- Next issue: The latest handoff, written by the worker, lists the remaining acceptance checks as blocked or unmet. Nothing in the worktree contradicts that.; Check 1: there is no local four-node integration smoke. The node image has no real entrypoint, and packages/node is not a uv workspace member. Only static Compose tests (5 tests in tests/infra) exist.; Check 2: the evidence is static only. The api login cookie is still secure=False, so authenticated HTTPS is incomplete.; Check 3: no Vultr URL, commit/image tags or TigerData connection evidence is recorded. The api does not consume TIGERDATA_URL because psycopg is not wired.; Check 4: no evidence that a container restart preserves checkpoints or that the replay stays retrievable.; Check 5: no verified rollback to the previous image and no resource or spend inventory.; Check 6: the blocked-fallback condition requires complete local packaging, and it is not complete. The node entrypoint, psycopg wiring and secure cookie are outside the T10 allowed paths and have not been done.; The handoff update is uncommitted (agents/handoffs/T10/LATEST.md is modified), and the task card is still 'waiting' with every checkbox unchecked.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Update run 20261010T154653Z (machine B, worker round 2)

- No code change this round. Remaining acceptance checks are blocked on items outside `infra/` and `tests/infra/`, or on human action:
  - Check 1 (local four-node smoke): needs a real node entrypoint and `packages/node` as a uv workspace member (shared files, A must serialize). Only static Compose tests exist (`tests/infra`, 5 tests).
  - Check 2: api login cookie still `secure=False` (services/api, outside T10 paths); authenticated HTTPS is static-config evidence only.
  - Check 3: no Vultr URL, image tags or TigerData evidence; needs host/budget approval and connection strings. The api does not consume `TIGERDATA_URL` until psycopg is wired.
  - Checks 4-5: restart recovery, rollback and spend inventory need a running stack; not run. No spend.
  - Check 6: local packaging is NOT complete (node entrypoint, psycopg, secure cookie), so the blocked-fallback condition is not yet satisfied either.
- Task card status stays `waiting`, all boxes unchecked (worker may not change it; integrator owns it).
- Needed from A: assign T10; land node entrypoint + uv workspace membership, psycopg wiring, and `secure=True` cookie. Then on a Docker machine run build + `infra/scripts/smoke.sh`.

## Supervisor checkpoint 2026-10-10T16:06:18Z

- Run: 20261010T154653Z
- Machine: B
- Task/branch: T10 / agent/B/20261010T154653Z/T10
- Base: 45bdc473257fb74683742baf82491ac07808a592
- Round: 10
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["Check 1 is not met. There is no local four-node integration smoke. The node image is a placeholder with no archipelago_node entrypoint, and packages/node is not a uv workspace member. Only static Compose tests (5 in tests/infra) and a proxy/web/api/grafana smoke exist.", "Check 2 is only partly met. The evidence is static (only proxy publishes ports). There is no runtime evidence that DB and peer ports are closed, and the api login cookie is still secure=False, so authenticated HTTPS is incomplete.", "Check 3 is not met. There is no Vultr URL, commit-tagged images or TigerData connection evidence. The api does not consume TIGERDATA_URL because psycopg is not wired.", "Check 4 is not met. There is no evidence that a container restart preserves checkpoints or that a replay stays retrievable.", "Check 5 is not met. There is no verified rollback to the previous image and no resource or spend inventory.", "Check 6 is not met. The blocked-fallback condition requires complete local packaging. The node entrypoint, psycopg wiring and secure cookie are still missing, and the worker's own handoff says so.", "The task card is still 'waiting' with every acceptance box unchecked. The latest handoff update in agents/handoffs/T10/LATEST.md is uncommitted. The passing external check only covers static tests and lint, not these acceptance items."]}
- Next issue: Check 1 is not met. There is no local four-node integration smoke. The node image is a placeholder with no archipelago_node entrypoint, and packages/node is not a uv workspace member. Only static Compose tests (5 in tests/infra) and a proxy/web/api/grafana smoke exist.; Check 2 is only partly met. The evidence is static (only proxy publishes ports). There is no runtime evidence that DB and peer ports are closed, and the api login cookie is still secure=False, so authenticated HTTPS is incomplete.; Check 3 is not met. There is no Vultr URL, commit-tagged images or TigerData connection evidence. The api does not consume TIGERDATA_URL because psycopg is not wired.; Check 4 is not met. There is no evidence that a container restart preserves checkpoints or that a replay stays retrievable.; Check 5 is not met. There is no verified rollback to the previous image and no resource or spend inventory.; Check 6 is not met. The blocked-fallback condition requires complete local packaging. The node entrypoint, psycopg wiring and secure cookie are still missing, and the worker's own handoff says so.; The task card is still 'waiting' with every acceptance box unchecked. The latest handoff update in agents/handoffs/T10/LATEST.md is uncommitted. The passing external check only covers static tests and lint, not these acceptance items.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Update run 20261010T160917Z (machine B, worker round 3)

- No code change. Re-checked: `packages/node` still has no `archipelago_node` entrypoint and is not a uv workspace member; `services/api/src/archipelago_api/app.py:113` still `secure=False`; psycopg not in api deps. All outside `infra/`, `tests/infra/`.
- Acceptance checks 1-6 remain unmet; no Docker/Vultr/spend actions taken. Same asks of A as the round-2 update. pytest is not installed in the default `python` here, so `tests/infra` was not re-run.

## Supervisor checkpoint 2026-10-10T16:11:11Z

- Run: 20261010T160917Z
- Machine: B
- Task/branch: T10 / agent/B/20261010T160917Z/T10
- Base: a84d1005b3ea17fc159dd9c38394224a163b00dc
- Round: 1
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["Check 1: no local four-node integration smoke. The node image is a placeholder with no archipelago_node entrypoint, and packages/node is not a uv workspace member. Only static Compose tests exist in tests/infra.", "Check 2: only static evidence that just the proxy publishes ports. There is no runtime evidence that DB and peer ports are closed. The api login cookie is still secure=False (services/api/src/archipelago_api/app.py:113), so authenticated HTTPS is incomplete.", "Check 3: no Vultr URL, commit-tagged images or TigerData connection evidence. The api does not consume TIGERDATA_URL because psycopg is not wired.", "Check 4: no evidence that a container restart preserves checkpoints or that replay stays retrievable.", "Check 5: no verified rollback to the previous image, and no resource or spend inventory.", "Check 6: the blocked-fallback condition requires complete local packaging. The node entrypoint, psycopg wiring and secure cookie are still missing, and the worker's own handoff says so.", "agents/handoffs/T10/LATEST.md has uncommitted changes, so the latest handoff is not pushed. The task card still says 'waiting' with every box unchecked.", "The passing external check covers only static tests, lint and build. It does not cover any of the acceptance items."]}
- Next issue: Check 1: no local four-node integration smoke. The node image is a placeholder with no archipelago_node entrypoint, and packages/node is not a uv workspace member. Only static Compose tests exist in tests/infra.; Check 2: only static evidence that just the proxy publishes ports. There is no runtime evidence that DB and peer ports are closed. The api login cookie is still secure=False (services/api/src/archipelago_api/app.py:113), so authenticated HTTPS is incomplete.; Check 3: no Vultr URL, commit-tagged images or TigerData connection evidence. The api does not consume TIGERDATA_URL because psycopg is not wired.; Check 4: no evidence that a container restart preserves checkpoints or that replay stays retrievable.; Check 5: no verified rollback to the previous image, and no resource or spend inventory.; Check 6: the blocked-fallback condition requires complete local packaging. The node entrypoint, psycopg wiring and secure cookie are still missing, and the worker's own handoff says so.; agents/handoffs/T10/LATEST.md has uncommitted changes, so the latest handoff is not pushed. The task card still says 'waiting' with every box unchecked.; The passing external check covers only static tests, lint and build. It does not cover any of the acceptance items.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Update run 20261010T160917Z (machine B, worker round 4)

- Added `tests/infra/test_runtime_ports.py`: brings up proxy, web, api, timescaledb (`-p archi-t10-rt`, `--no-build`, existing `:dev` images), checks 80/443 open and 5432/8000/9000/3000 closed on the host, restarts api and re-checks health, then `down -v`. `py -m pytest tests/infra/test_runtime_ports.py`: 1 passed (15s). Gives runtime evidence for the closed-port half of check 2 and an api container-restart health check only; it does NOT show checkpoint preservation or replay retrieval (check 4).
- Removed a leftover `t10smoke` compose project that held host ports 80/443 (it was an earlier smoke stack of this task).
- Unchanged and outside T10 paths: node entrypoint / uv membership, `secure=False` cookie (app.py:113), psycopg wiring. Checks 1, 3, 4 (checkpoints), 5, 6 remain unmet. No Vultr/spend actions.

## Supervisor checkpoint 2026-10-10T16:12:17Z

- Run: 20261010T160917Z
- Machine: B
- Task/branch: T10 / agent/B/20261010T160917Z/T10
- Base: a84d1005b3ea17fc159dd9c38394224a163b00dc
- Round: 2
- State: in_progress
- External check exit: 1
- Independent review: not run
- Next issue: External checks failed (exit 1); inspect local check log
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Update run 20261010T160917Z (machine B, worker round 5)

- Fixed external check failure (exit 1): `tests/infra/test_runtime_ports.py` had a ruff E501 and was not ruff-formatted. Now `ruff check`/`ruff format --check` pass on tests/infra; `py -m pytest tests/infra` 6 passed; mypy clean. Full `scripts/check.sh` not re-run (node/npm steps untouched).
- Acceptance checks 1, 3, 4 (checkpoints), 5, 6 unchanged; blockers remain outside T10 paths (node entrypoint, secure cookie, psycopg).

## Supervisor checkpoint 2026-10-10T16:14:18Z

- Run: 20261010T160917Z
- Machine: B
- Task/branch: T10 / agent/B/20261010T160917Z/T10
- Base: a84d1005b3ea17fc159dd9c38394224a163b00dc
- Round: 3
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["The T10 handoff says acceptance checks 1, 3, 4 (checkpoints), 5 and 6 are unchanged and unmet. The task is not ready for human PR review.", "No Vultr deployment evidence is recorded: no URL, commit or images, TigerData connection, spend status or resource inventory. Deployment is blocked on credentials and budget, and the handoff lists no completed human steps.", "Rollback has not been verified, and restart recovery is only partly evidenced. `tests/infra/test_runtime_ports.py` exists, but the handoff gives no evidence that checkpoint preservation or replay retrieval were verified.", "The local four-node integration smoke is not shown to pass. The node image is a placeholder with no `archipelago_node` entrypoint, and `packages/node` is not a uv workspace member. The handoff does not show image builds or `smoke.sh` being run.", "The login cookie uses `secure=False`, and the API has no wiring for `psycopg` or `TIGERDATA_URL`. The handoff says both blockers are outside the T10 paths and are not fixed.", "The task card's own status and next step still read 'waiting' and 'wait for dependencies', and the handoff calls this a prep branch rather than a formal T10 assignment. The handoff states that the 'Compose validation and local four-node integration smoke' check is only partly met.", "This round's diff is only ruff formatting of a test file plus a handoff note. It adds no acceptance evidence. The external check passing means lint, tests and build are clean, not that the acceptance checks are met."]}
- Next issue: The T10 handoff says acceptance checks 1, 3, 4 (checkpoints), 5 and 6 are unchanged and unmet. The task is not ready for human PR review.; No Vultr deployment evidence is recorded: no URL, commit or images, TigerData connection, spend status or resource inventory. Deployment is blocked on credentials and budget, and the handoff lists no completed human steps.; Rollback has not been verified, and restart recovery is only partly evidenced. `tests/infra/test_runtime_ports.py` exists, but the handoff gives no evidence that checkpoint preservation or replay retrieval were verified.; The local four-node integration smoke is not shown to pass. The node image is a placeholder with no `archipelago_node` entrypoint, and `packages/node` is not a uv workspace member. The handoff does not show image builds or `smoke.sh` being run.; The login cookie uses `secure=False`, and the API has no wiring for `psycopg` or `TIGERDATA_URL`. The handoff says both blockers are outside the T10 paths and are not fixed.; The task card's own status and next step still read 'waiting' and 'wait for dependencies', and the handoff calls this a prep branch rather than a formal T10 assignment. The handoff states that the 'Compose validation and local four-node integration smoke' check is only partly met.; This round's diff is only ruff formatting of a test file plus a handoff note. It adds no acceptance evidence. The external check passing means lint, tests and build are clean, not that the acceptance checks are met.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Worker update 2026-10-10 (run 20261010T160917Z, machine B)

Changed (infra/, tests/infra/ only):
- `infra/node/entrypoint.py`: real node entrypoint (T05 `PeerServer` on the private network, atomic checkpoint `{boots, seen}` in `NODE_CHECKPOINT_DIR`). Replaces the placeholder `archipelago_node`.
- `infra/docker/node.Dockerfile`: single-stage, stdlib-only, no uv sync (the old `uv sync --frozen` failed, exit 2). Uses `PYTHONPATH` for peer and transport.
- `tests/infra/test_node_entrypoint.py`: deliver an envelope, kill, restart; checkpoint is preserved and boots increments.

Evidence (run locally):
- `uv run pytest tests/infra`: 7 passed. `ruff check`/`format`: clean.
- `docker build -f infra/docker/node.Dockerfile -t archipelago/node:dev .`: succeeded.
- `docker run` plus `docker restart` with a named volume: log shows `boots=1` then `boots=2`. This is checkpoint-preserved-on-restart for one node only.

Still unmet: api/web image builds, four-node `smoke.sh` run, replay retrievability across restart, rollback, all Vultr/TigerData/spend evidence (credentials and budget missing), `secure=False` cookie and `TIGERDATA_URL` wiring (outside T10 paths). Task card status is not mine to change.

## Supervisor checkpoint 2026-10-10T16:17:45Z

- Run: 20261010T160917Z
- Machine: B
- Task/branch: T10 / agent/B/20261010T160917Z/T10
- Base: a84d1005b3ea17fc159dd9c38394224a163b00dc
- Round: 4
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["The local four-node integration smoke has not been run. infra/scripts/smoke.sh has not been run against a stack. The handoff says the api and web image builds are unmet. Only the node image build and a one-node restart were run.", "There is no Vultr evidence: no URL, commit or image tags, TigerData connection, spend status or resource inventory. Credentials and budget are missing. Per the task card, deployment then stays blocked, and this is not ready for review as a completed deployment.", "Rollback to the previous image has not been verified.", "Restart recovery is only shown for one node, where boots went from 1 to 2 with a named volume. There is no evidence for the four-node stack. Replay retrievability across restart is not demonstrated.", "The acceptance check 'no anonymous mutation endpoints' is not fully backed. The API login cookie still has secure=False. TIGERDATA_URL has no consumer, and psycopg is not a locked runtime dependency. The handoff says these are outside T10 paths and unresolved.", "Several tests (test_compose, test_api_image, test_runtime_ports) skip when docker is not installed or when ports 80/443 are in use. The external check showed 3 skipped. That run is therefore not proof of the compose and port checks.", "The task card still says 'waiting' with no assignment. The handoff calls this a prep branch rather than a formal T10 assignment. The uncommitted changes (node entrypoint, Dockerfile, new test, handoff) are not committed or pushed in this worktree."]}
- Next issue: The local four-node integration smoke has not been run. infra/scripts/smoke.sh has not been run against a stack. The handoff says the api and web image builds are unmet. Only the node image build and a one-node restart were run.; There is no Vultr evidence: no URL, commit or image tags, TigerData connection, spend status or resource inventory. Credentials and budget are missing. Per the task card, deployment then stays blocked, and this is not ready for review as a completed deployment.; Rollback to the previous image has not been verified.; Restart recovery is only shown for one node, where boots went from 1 to 2 with a named volume. There is no evidence for the four-node stack. Replay retrievability across restart is not demonstrated.; The acceptance check 'no anonymous mutation endpoints' is not fully backed. The API login cookie still has secure=False. TIGERDATA_URL has no consumer, and psycopg is not a locked runtime dependency. The handoff says these are outside T10 paths and unresolved.; Several tests (test_compose, test_api_image, test_runtime_ports) skip when docker is not installed or when ports 80/443 are in use. The external check showed 3 skipped. That run is therefore not proof of the compose and port checks.; The task card still says 'waiting' with no assignment. The handoff calls this a prep branch rather than a formal T10 assignment. The uncommitted changes (node entrypoint, Dockerfile, new test, handoff) are not committed or pushed in this worktree.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Worker update 2026-10-10 (run 20261010T160917Z, round 5, machine B) — local stack evidence

Only this handoff changed this round. Commands run from repo root with a temp env file (token/password placeholders, not committed), project `t10smoke`, torn down with `down -v` afterwards:
- `docker build -f infra/docker/{api,web}.Dockerfile` : both succeeded (api, web).
- `docker compose -f infra/compose/compose.yml --env-file <tmp> --profile local -p t10smoke up -d`: proxy, web, api, grafana, timescaledb, node-01..04 all up; api, web and all 4 nodes `healthy`.
- `BASE_URL=https://localhost API_TOKEN=<tmp> SMOKE_CURL_OPTS=-k bash infra/scripts/smoke.sh`: 9 PASS, exit 0 (health, ready, web, anon create/get 401, bad login 401, good login, http->308, grafana 401). The closed-port check needs HOST_IP and was NOT run.
- Restart recovery, 4 nodes: `docker compose restart node-01..04 api` : boots 1 -> 2 on every node with named volumes; all healthy again.
- Rollback (local only): tagged dev images as `:prev`, `IMAGE_TAG=prev ... up -d --no-build`: api/web/nodes switched to `:prev`, healthy, boots=3 (checkpoints preserved), smoke 9 PASS. This only proves the tag-switch mechanism; it is not a rollback between two real commits and not on Vultr.

Still unmet: replay retrievability across restart (no run was created; the simulation coordinator is not a compose service), TigerData connection (local timescaledb not exercised by the API; `TIGERDATA_URL` has no consumer, psycopg not locked), cookie `secure=False` (outside T10 paths), and all Vultr evidence (URL, commit/images, spend, inventory): credentials and budget missing, so deployment remains BLOCKED. Human step needed: provide Vultr host + budget approval and TigerData URL. Task card status is not mine to change.

## Supervisor checkpoint 2026-10-10T16:21:13Z

- Run: 20261010T160917Z
- Machine: B
- Task/branch: T10 / agent/B/20261010T160917Z/T10
- Base: a84d1005b3ea17fc159dd9c38394224a163b00dc
- Round: 5
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["Check 3 has no evidence. There is no Vultr URL, deployed commit or image tags, TigerData connection evidence, spend status or resource inventory. The handoff says credentials and budget are missing, so deployment is blocked.", "Check 4 is only partly met. Node checkpoints survive a restart on all 4 nodes (boots 1 to 2). Replay retrievability across restart was never shown, because no run was created and the simulation coordinator is not a compose service.", "Check 5 is not met. The rollback was only a local switch between :dev and :prev tags of the same build. It is not a rollback between two real commit-tagged images. There is no resource inventory or spend status.", "Check 2 is only partly met. The compose tests and test_runtime_ports.py show that only the proxy publishes ports and that 5432/8000/9000/3000 are closed locally. The smoke.sh closed-port check needs HOST_IP and was not run. The API login cookie is still secure=False (services/api/src/archipelago_api/app.py:113), so authenticated HTTPS is incomplete.", "Check 6 is not met. It needs local packaging to be complete while deployment stays blocked. TIGERDATA_URL has no consumer because psycopg is not a locked dependency. The secure cookie fix is missing. The handoff does not record the blocked state as a final handoff.", "Check 1 is only partly met. The 4-node stack came up and smoke.sh passed 9 checks, but only in a manual run recorded in the handoff. The node image is a stdlib-only stub entrypoint (infra/node/entrypoint.py), not the real learner or simulation node. tests/infra covers the compose config, the api image, the ports and a single node restart. It has no automated four-node smoke.", "agents/handoffs/T10/LATEST.md has uncommitted changes, so the latest handoff is not pushed. The task card still reads waiting and unclaimed with every acceptance box unchecked. The docker-dependent tests in tests/infra skip without docker or free ports 80/443. The 3 skips in the external run suggest the gating check may not have exercised them."]}
- Next issue: Check 3 has no evidence. There is no Vultr URL, deployed commit or image tags, TigerData connection evidence, spend status or resource inventory. The handoff says credentials and budget are missing, so deployment is blocked.; Check 4 is only partly met. Node checkpoints survive a restart on all 4 nodes (boots 1 to 2). Replay retrievability across restart was never shown, because no run was created and the simulation coordinator is not a compose service.; Check 5 is not met. The rollback was only a local switch between :dev and :prev tags of the same build. It is not a rollback between two real commit-tagged images. There is no resource inventory or spend status.; Check 2 is only partly met. The compose tests and test_runtime_ports.py show that only the proxy publishes ports and that 5432/8000/9000/3000 are closed locally. The smoke.sh closed-port check needs HOST_IP and was not run. The API login cookie is still secure=False (services/api/src/archipelago_api/app.py:113), so authenticated HTTPS is incomplete.; Check 6 is not met. It needs local packaging to be complete while deployment stays blocked. TIGERDATA_URL has no consumer because psycopg is not a locked dependency. The secure cookie fix is missing. The handoff does not record the blocked state as a final handoff.; Check 1 is only partly met. The 4-node stack came up and smoke.sh passed 9 checks, but only in a manual run recorded in the handoff. The node image is a stdlib-only stub entrypoint (infra/node/entrypoint.py), not the real learner or simulation node. tests/infra covers the compose config, the api image, the ports and a single node restart. It has no automated four-node smoke.; agents/handoffs/T10/LATEST.md has uncommitted changes, so the latest handoff is not pushed. The task card still reads waiting and unclaimed with every acceptance box unchecked. The docker-dependent tests in tests/infra skip without docker or free ports 80/443. The 3 skips in the external run suggest the gating check may not have exercised them.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Worker update 2026-10-10 (run 20261010T160917Z, round 6, machine B): final blocked-state record

Changed (tests/infra/ and this handoff only): added `tests/infra/test_four_nodes.py`, an automated four-node check. It brings up node-01..04 (project `archi-t10-nodes`, `--no-build`, existing `:dev` image), waits for every checkpoint to show `boots=1`, restarts all four, and waits for `boots=2` on each. Torn down with `down -v`.

Evidence: `uv run pytest tests/infra -q`: 8 passed, 0 skipped (35s, docker present). `ruff check`/`ruff format` clean. No leftover `archi-t10*` containers.

Final state of the six checks:
1. Partly met. Compose config, api/web/node image builds and an automated four-node start/restart test exist. The node is the infra stand-in entrypoint, not the real learner or simulation node. `smoke.sh` is a manual run (9 PASS, recorded above), not a pytest.
2. Partly met. Only `proxy` publishes ports; 5432/8000/9000/3000 are closed locally (`test_runtime_ports.py`). `smoke.sh` HOST_IP closed-port check is for the deployed host and was not run. The api login cookie is still `secure=False` (app.py:113), outside T10 paths, so authenticated HTTPS is incomplete.
3. NOT MET, BLOCKED. No Vultr URL, deployed commit or image tags, or TigerData connection. Vultr host/budget approval and TigerData connection strings were never provided. `TIGERDATA_URL` has no consumer (psycopg not locked), outside T10 paths.
4. Partly met. Node checkpoints survive restart on all four nodes (automated). Replay retrievability is not shown: the simulation coordinator is not a compose service and no run was created.
5. NOT MET. Only a local `:dev` to `:prev` tag switch of the same build; no rollback between two commit-tagged images.
6. Local packaging is complete for what T10 can own (images, compose profiles, proxy, runbooks, smoke, tests); deployment is BLOCKED on the human actions listed at the top. The remaining local gaps need the integrator: real node entrypoint and uv membership, psycopg wiring, `secure=True` cookie.

Spend status: $0. No cloud resource was created and no paid service was called.
Resource inventory: Vultr: none. TigerData: none. Local Docker only, with images `archipelago/{api,web,node}:{dev,prev}` and no running containers or volumes from this task.

State for the integrator: blocked_on_human (host/budget, TigerData URL, DNS) and on shared-file changes by A. Task card is not mine to change.

## Supervisor checkpoint 2026-10-10T16:24:21Z

- Run: 20261010T160917Z
- Machine: B
- Task/branch: T10 / agent/B/20261010T160917Z/T10
- Base: a84d1005b3ea17fc159dd9c38394224a163b00dc
- Round: 6
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["Check 3 (Vultr) has no evidence. There is no Vultr URL, deployed commit or commit-tagged image, or TigerData connection. The handoff says credentials and budget were never provided, so deployment is blocked and cannot be reviewed as done.", "Check 5 is not met. The only rollback run was a local :dev to :prev tag switch of the same build, not a rollback between two real commit-tagged images. There is no resource inventory or spend record from an actual deployment.", "Check 4 is only partly met. Node checkpoints survive a restart on all four nodes (automated in test_four_nodes.py). Replay retrievability across restart is not shown. No run was created and the simulation coordinator is not a compose service.", "Check 2 is only partly met. Only the static and local checks show that the proxy is the only published service and that 5432/8000/9000/3000 are closed. The smoke.sh HOST_IP closed-port check was never run. The API login cookie is still secure=False (services/api/src/archipelago_api/app.py:113), so authenticated HTTPS is incomplete.", "Check 1 is only partly met. The node is an infra stand-in (infra/node/entrypoint.py), not the real learner or simulation node. smoke.sh ran only manually (9 PASS, recorded in the handoff), with no pytest or CI evidence.", "Check 6 is not met as written. It needs complete local packaging while deployment stays blocked. TIGERDATA_URL has no consumer because psycopg is not a locked dependency, and the secure cookie fix and real node uv membership are missing. These are outside T10's allowed paths and need the integrator.", "The tests/infra tests skip when docker is missing, and the docker-dependent ones also skip when ports 80/443 are busy. The external check showed 3 skipped, so the gating check may not have exercised them.", "The worktree has uncommitted changes: agents/handoffs/T10/LATEST.md is modified and tests/infra/test_four_nodes.py is untracked. The final blocked-state handoff is not pushed.", "The task card is still 'waiting' and unclaimed with every acceptance box unchecked. The worker's own final record says checks 3 and 5 are NOT MET and the rest are partial. The external check passing only shows lint, type and tests are clean, not that the acceptance checks are met."]}
- Next issue: Check 3 (Vultr) has no evidence. There is no Vultr URL, deployed commit or commit-tagged image, or TigerData connection. The handoff says credentials and budget were never provided, so deployment is blocked and cannot be reviewed as done.; Check 5 is not met. The only rollback run was a local :dev to :prev tag switch of the same build, not a rollback between two real commit-tagged images. There is no resource inventory or spend record from an actual deployment.; Check 4 is only partly met. Node checkpoints survive a restart on all four nodes (automated in test_four_nodes.py). Replay retrievability across restart is not shown. No run was created and the simulation coordinator is not a compose service.; Check 2 is only partly met. Only the static and local checks show that the proxy is the only published service and that 5432/8000/9000/3000 are closed. The smoke.sh HOST_IP closed-port check was never run. The API login cookie is still secure=False (services/api/src/archipelago_api/app.py:113), so authenticated HTTPS is incomplete.; Check 1 is only partly met. The node is an infra stand-in (infra/node/entrypoint.py), not the real learner or simulation node. smoke.sh ran only manually (9 PASS, recorded in the handoff), with no pytest or CI evidence.; Check 6 is not met as written. It needs complete local packaging while deployment stays blocked. TIGERDATA_URL has no consumer because psycopg is not a locked dependency, and the secure cookie fix and real node uv membership are missing. These are outside T10's allowed paths and need the integrator.; The tests/infra tests skip when docker is missing, and the docker-dependent ones also skip when ports 80/443 are busy. The external check showed 3 skipped, so the gating check may not have exercised them.; The worktree has uncommitted changes: agents/handoffs/T10/LATEST.md is modified and tests/infra/test_four_nodes.py is untracked. The final blocked-state handoff is not pushed.; The task card is still 'waiting' and unclaimed with every acceptance box unchecked. The worker's own final record says checks 3 and 5 are NOT MET and the rest are partial. The external check passing only shows lint, type and tests are clean, not that the acceptance checks are met.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Supervisor checkpoint 2026-10-10T16:27:00Z

- Run: 20261010T160917Z
- Machine: B
- Task/branch: T10 / agent/B/20261010T160917Z/T10
- Base: a84d1005b3ea17fc159dd9c38394224a163b00dc
- Round: 7
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["Check 3 has no evidence: no Vultr URL, no deployed commit or image tags, no TigerData connection. The handoff says host/budget approval and TigerData strings were never provided. TIGERDATA_URL has no consumer because psycopg is not a locked dependency.", "Check 5 is not met. The only rollback was a local :dev to :prev tag switch of the same build, not a rollback between two real commit-tagged images. No Vultr resource inventory or deployment spend record exists; the $0 figure only says nothing was deployed.", "Check 4 is partly met. Node checkpoint survival across restart of all four nodes is automated in tests/infra/test_four_nodes.py. Replay retrievability across restart is not shown: no run was created and the simulation coordinator is not a compose service.", "Check 2 is partly met. Static compose tests and test_runtime_ports.py show only the proxy publishes ports and 5432/8000/9000/3000 are closed locally. The smoke.sh HOST_IP closed-port check was never run. The API login cookie is still secure=False (services/api/src/archipelago_api/app.py:113), so authenticated HTTPS is incomplete.", "Check 1 is partly met. The four-node test runs a stand-in stdlib entrypoint (infra/node/entrypoint.py), not the real learner or simulation node. The smoke.sh run (9 PASS) was manual and is recorded only in the handoff, with no pytest or CI evidence.", "Check 6 is not satisfied as written. Local packaging is still incomplete: the real node entrypoint and uv workspace membership, psycopg wiring and secure cookie are all missing. The handoff places these outside T10 paths, so they need the integrator.", "The docker-dependent tests (test_compose, test_api_image, test_runtime_ports, test_four_nodes) skip without docker or when ports 80/443 are busy. The external check showed 3 skipped, so the gating run may not have exercised them.", "The task card still reads 'waiting' and unclaimed, with every acceptance box unchecked. Its Latest handoff field says 'none'. The worker's own final record lists checks 3 and 5 as NOT MET and the rest as partial.", "I could not run git status or the tests, because Bash was denied. I could not confirm that the final handoff and tests/infra/test_four_nodes.py are committed and pushed."]}
- Next issue: Check 3 has no evidence: no Vultr URL, no deployed commit or image tags, no TigerData connection. The handoff says host/budget approval and TigerData strings were never provided. TIGERDATA_URL has no consumer because psycopg is not a locked dependency.; Check 5 is not met. The only rollback was a local :dev to :prev tag switch of the same build, not a rollback between two real commit-tagged images. No Vultr resource inventory or deployment spend record exists; the $0 figure only says nothing was deployed.; Check 4 is partly met. Node checkpoint survival across restart of all four nodes is automated in tests/infra/test_four_nodes.py. Replay retrievability across restart is not shown: no run was created and the simulation coordinator is not a compose service.; Check 2 is partly met. Static compose tests and test_runtime_ports.py show only the proxy publishes ports and 5432/8000/9000/3000 are closed locally. The smoke.sh HOST_IP closed-port check was never run. The API login cookie is still secure=False (services/api/src/archipelago_api/app.py:113), so authenticated HTTPS is incomplete.; Check 1 is partly met. The four-node test runs a stand-in stdlib entrypoint (infra/node/entrypoint.py), not the real learner or simulation node. The smoke.sh run (9 PASS) was manual and is recorded only in the handoff, with no pytest or CI evidence.; Check 6 is not satisfied as written. Local packaging is still incomplete: the real node entrypoint and uv workspace membership, psycopg wiring and secure cookie are all missing. The handoff places these outside T10 paths, so they need the integrator.; The docker-dependent tests (test_compose, test_api_image, test_runtime_ports, test_four_nodes) skip without docker or when ports 80/443 are busy. The external check showed 3 skipped, so the gating run may not have exercised them.; The task card still reads 'waiting' and unclaimed, with every acceptance box unchecked. Its Latest handoff field says 'none'. The worker's own final record lists checks 3 and 5 as NOT MET and the rest as partial.; I could not run git status or the tests, because Bash was denied. I could not confirm that the final handoff and tests/infra/test_four_nodes.py are committed and pushed.
- Resume: fetch this branch, inspect latest commit and continue the task card.
