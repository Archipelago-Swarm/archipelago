# Rollback and teardown (T10)

Status: DRAFT. All commands NOT RUN.

## Rollback to the previous image (no schema reversal)

Principle: images are tagged by commit and kept on the host; migrations are additive, so older code runs against the newer schema. Never run destructive DDL as part of a rollback.

Before each deploy, record the current tag: `grep ^IMAGE_TAG= infra/compose/.env > ~/previous-tag`.

```bash
# NOT RUN
cd ~/archipelago
PREV=$(cut -d= -f2 ~/previous-tag)
docker image inspect archipelago/api:$PREV archipelago/web:$PREV archipelago/node:$PREV >/dev/null   # must exist
sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=$PREV/" infra/compose/.env
git checkout <PREVIOUS_COMMIT_SHA> -- infra/compose infra/proxy        # config matching that image
docker compose -f infra/compose/compose.yml --env-file infra/compose/.env up -d --no-build
BASE_URL=https://<SITE_ADDRESS> API_TOKEN=<token> infra/scripts/smoke.sh
```
Pass criteria: smoke exits 0, `ps` shows previous tag, named volumes (api-data, node-0N) unchanged. Do not `docker image prune` until the new tag is accepted.

## Restart recovery check (NOT RUN)

```bash
docker compose -f infra/compose/compose.yml --env-file infra/compose/.env exec node-01 ls -l /node-data > before.txt
docker compose -f infra/compose/compose.yml --env-file infra/compose/.env restart node-01 api
# wait for healthy, then:
docker compose -f infra/compose/compose.yml --env-file infra/compose/.env exec node-01 ls -l /node-data > after.txt
diff before.txt after.txt   # checkpoints present and not truncated
```

## Teardown

Stop the app but keep data: `docker compose ... down` (no `-v`). To delete data (needs explicit operator OK, because volumes hold checkpoints and replays): back up first, e.g. `docker run --rm -v archipelago_api-data:/d -v $PWD:/b alpine tar czf /b/api-data.tgz -C /d .`, then `down -v`.

If a Vultr instance was created for this project (only with an operator budget): export artifacts, destroy the instance and any block storage, reserved IP and snapshots in the console (or `vultr-cli instance delete <id>` with the operator's key), then list all resources to confirm zero remaining, and record the final usage. TigerData service lifecycle is the operator's decision; drop only the project roles and data when told to.

## Resource inventory template (fill at deploy and after teardown)

| Resource | ID | Created (UTC) | Monthly cost | Status |
|---|---|---|---|---|
| Vultr instance | | | | |
| Block storage / snapshots / reserved IP | | | | |
| DNS record | | | | |
| TigerData service | | | | |
