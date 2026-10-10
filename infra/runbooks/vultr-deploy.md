# Vultr deploy runbook (T10)

Status: DRAFT. Every command below is NOT RUN. Nothing has been provisioned or built. Do not execute without the human approvals listed in "Gates".

## Gates (all required before step 1)

1. Operator approves a host: either an existing Vultr instance (preferred, no new spend) or a written budget cap for one new instance (see `budget-guard.md`).
2. Vultr API key or console access supplied by the operator out of band (never committed, never in a handoff).
3. TigerData service exists; operator supplies a TLS connection string for a writer role and a read-only role (`packages/storage/migrations/0002_roles.sql`).
4. A DNS name resolving to the host (for ACME certificates). Without it use a self-signed `SITE_ADDRESS=<ip>` only for a private smoke test, and record that limitation.
5. Docker is available on the host (installed on the host, not required on the dev machine).
6. T03, T04, T05, T06, T08 merged; node entrypoint (`archipelago_node`) exists. As of this prep the node image cannot build (see `node.Dockerfile` header).

## Sizing starting point (decision, not measurement)

Ubuntu 22.04/24.04, 2 vCPU / 4 GB RAM / 80 GB disk covers the compose limits in `infra/compose/compose.yml` (about 3.4 GB RAM cap if all services hit limits; measure a 4-node run before resizing).

## Steps

Run on the host over SSH as a non-root sudo user, unless noted.

### 1. Host hardening (NOT RUN)
```bash
sudo apt-get update && sudo apt-get install -y ca-certificates curl git ufw
sudo ufw default deny incoming && sudo ufw default allow outgoing
sudo ufw allow from <OPERATOR_IP>/32 to any port 22 proto tcp
sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
sudo ufw enable
# Docker: follow https://docs.vultr.com/how-to-install-docker-on-ubuntu-2204 (Compose v2 plugin).
```
Note: Docker publishes ports by editing iptables and bypasses ufw for published ports; compose publishes only 80/443 on purpose. Also set the Vultr firewall group (console) to allow only 22 from the operator, 80, 443.

### 2. Fetch the exact commit (NOT RUN)
```bash
git clone https://github.com/<OWNER>/archipelago.git && cd archipelago
git fetch origin && git checkout <COMMIT_SHA>   # the merged main commit being deployed
export IMAGE_TAG=$(git rev-parse --short=12 HEAD)
```

### 3. Configure secrets on the host only (NOT RUN)
```bash
cp infra/compose/.env.example infra/compose/.env && chmod 600 infra/compose/.env
# edit: SITE_ADDRESS, ACME_EMAIL, IMAGE_TAG, ARCHIPELAGO_API_TOKEN (openssl rand -hex 24),
# ARCHIPELAGO_ALLOWED_ORIGINS=https://<SITE_ADDRESS>, GRAFANA_ADMIN_PASSWORD, TIGERDATA_* (sslmode=require)
```

### 4. Static validation and build (NOT RUN)
```bash
docker compose -f infra/compose/compose.yml --env-file infra/compose/.env config -q
docker compose -f infra/compose/compose.yml --env-file infra/compose/.env build
docker image ls 'archipelago/*'      # record image IDs in the deploy handoff
```

### 5. Migrate TigerData (NOT RUN)
Run migrations with the owner/admin credential from the operator, once, from the host or a trusted machine:
```bash
for f in packages/storage/migrations/*.sql; do psql "$TIGERDATA_ADMIN_URL" -v ON_ERROR_STOP=1 -f "$f"; done
```
The migrations are idempotent DDL and additive; rollback never reverses schema.

### 6. Start (NOT RUN)
```bash
docker compose -f infra/compose/compose.yml --env-file infra/compose/.env up -d
docker compose -f infra/compose/compose.yml --env-file infra/compose/.env ps   # all healthy
```

### 7. Smoke check (NOT RUN)
```bash
BASE_URL=https://<SITE_ADDRESS> API_TOKEN=<token> HOST_IP=<ip> infra/scripts/smoke.sh   # from an external machine
```
Then the restart-recovery check (see `smoke-checks.md`) and record: URL, commit, image IDs, TigerData row count for the smoke run, `docker stats --no-stream`, and spend status.

## Evidence the integrator needs (acceptance map)

| Acceptance | Evidence to capture |
|---|---|
| Compose validation, local four-node smoke | `docker compose config -q` exit 0; local `--profile local up` + `smoke.sh` output (needs Docker on a dev machine) |
| No anonymous mutation / public DB or peer ports | `smoke.sh` PASS lines incl. external port scan |
| Actual URL, commit/images, TigerData evidence | URL, `git rev-parse HEAD`, `docker image ls --digests`, query result on the run row |
| Restart preserves checkpoints, replay retrievable | before/after checkpoint listing from node volumes; replay fetch |
| Rollback verified, inventory/spend recorded | `rollback-teardown.md` log, Vultr instance list, invoice/usage screenshot or CLI text |
