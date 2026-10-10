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

Known gaps to resolve before the checks are meaningful: the simulation coordinator is not a compose service yet. The login cookie is Secure by default (`ARCHIPELAGO_COOKIE_SECURE`).

## Restart and replay (acceptance check 4)

`tests/infra/test_smoke_and_replay.py` runs smoke.sh, completes a run, pauses a second run so it stays active, restarts the api container, and asserts: the finished run keeps `completed`/`stopped`, the active run reports `interrupted` (`process_shutdown`), and the finished run's replay (`GET /v1/runs/{id}/events`) equals the events captured before the restart. Events are stored per run as JSON Lines under the data volume (`<data>/events/`).

Replay durability is implemented in the api (append-only event log on the data volume) and covered by `tests/api/test_event_replay.py`; the Docker restart assertion is UNVERIFIED until CI runs it.

smoke.sh fixes: the port loop printed a false `PASS port 22 closed` without probing (22 removed) and could hang on filtered ports (now `timeout 3`); added an authenticated unknown-run check (404) proving proxy plus auth routing; `http://` origin derivation now handles http base URLs and `HTTP_URL` override.
