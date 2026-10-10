# Smoke-check design (T10)

Script: `infra/scripts/smoke.sh` (NOT RUN against any stack; only `bash -n` syntax-checked). It is black-box over HTTPS and exits nonzero on any failure.

Implemented checks: health/readiness, web index, anonymous create/get rejected (401), bad login rejected, good login, plain HTTP not served in clear, Grafana requires login, and (when `HOST_IP` is set, run externally) that 5432/3000/8000/9000 are closed.

Designed but not implemented (depend on unmerged wiring; implement when the node entrypoint, sim2d adapter and TigerData ingest are connected):
1. Create a 4-node run via `POST /v1/runs` with the login cookie; step it N ticks; read `/v1/runs/{id}/events` and assert ordered sequence.
2. Restart recovery: record node checkpoint listings, `docker compose restart node-01 api`, assert checkpoint files unchanged and the run is resumable or cleanly reported.
3. Replay: fetch the replay for the finished run and compare event count with step 1.
4. TigerData: query `runs` and `events` for the run id using the reader role and assert rows exist (evidence of the actual connection).
5. Peer isolation: from the api container, `nc -z node-01 9000` must fail (nodes are on the internal `peers` network only); from the host, 9000 must be closed.
6. Four-node local smoke with `--profile local` on a Docker-capable dev machine.

Known gaps to resolve before the checks are meaningful: the api cookie is set with `secure=False` (see comment in `services/api/src/archipelago_api/app.py` for T10; needs `secure=True` behind TLS, a change outside T10's allowed paths, so it needs A's serialized ownership); the simulation coordinator is not a compose service yet; psycopg is not yet a locked runtime dependency of the API image.
