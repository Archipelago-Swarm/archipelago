# Smoke-check design (T10)

Script: `infra/scripts/smoke.sh` (UNVERIFIED at runtime: no Docker in the authoring sandbox; `bash -n` only. CI runs it via `tests/infra/test_smoke_and_replay.py`). It is black-box over HTTPS and exits nonzero on any failure.

Implemented checks: health/readiness, web index, anonymous create/get rejected (401), bad login rejected, good login, plain HTTP not served in clear, Grafana requires login, and (when `HOST_IP` is set, run externally) that 5432/3000/8000/9000 are closed.

Designed but not implemented (depend on unmerged wiring; implement when the node entrypoint, sim2d adapter and TigerData ingest are connected):
1. Create a 4-node run via `POST /v1/runs` with the login cookie; step it N ticks; read `/v1/runs/{id}/events` and assert ordered sequence.
2. Restart recovery: record node checkpoint listings, `docker compose restart node-01 api`, assert checkpoint files unchanged and the run is resumable or cleanly reported.
3. Replay: fetch the replay for the finished run and compare event count with step 1.
4. TigerData: query `runs` and `events` for the run id using the reader role and assert rows exist (evidence of the actual connection).
5. Peer isolation: from the api container, `nc -z node-01 9000` must fail (nodes are on the internal `peers` network only); from the host, 9000 must be closed.
6. Four-node local smoke with `--profile local` on a Docker-capable dev machine.

Known gaps to resolve before the checks are meaningful: the api cookie is set with `secure=False` (see comment in `services/api/src/archipelago_api/app.py` for T10; needs `secure=True` behind TLS, a change outside T10's allowed paths, so it needs A's serialized ownership); the simulation coordinator is not a compose service yet; psycopg is not yet a locked runtime dependency of the API image.

## Restart and replay (acceptance check 4)

`tests/infra/test_smoke_and_replay.py` runs smoke.sh, completes a run, leaves a second run active, restarts the api container, and asserts: the finished run keeps `completed`/`stopped`, the active run reports `interrupted`, and the events endpoint returns nothing that was not emitted before.

Known gap: only run metadata is persisted (`/data/runs.json`); the event log is in memory, so after a restart `GET /v1/runs/{id}/events` returns an empty list for old runs. Replay survival across restart is not met until T08 persists events/artifacts; the test deliberately does not claim it.

smoke.sh fixes: the port loop printed a false `PASS port 22 closed` without probing (22 removed) and could hang on filtered ports (now `timeout 3`); added an authenticated unknown-run check (404) proving proxy plus auth routing; `http://` origin derivation now handles http base URLs and `HTTP_URL` override.
