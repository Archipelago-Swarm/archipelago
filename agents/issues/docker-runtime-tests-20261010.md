# Docker-runtime tests fail without a Docker daemon (open, not fixed)

- Recorded 2026-10-10 by A during integration (PR #5). Nothing here is skipped or suppressed; the tests are left failing where the environment cannot run them.
- Reproduction (authoring sandbox, no Docker daemon): `uv run pytest tests/infra -q` -> 1 failed, 2 errors, from `docker: failed to connect to the docker API at unix:///var/run/docker.sock`.

| Test | Needs | Last known result |
|---|---|---|
| `tests/infra/test_api_image.py::test_api_image_builds_and_rejects_anonymous` | daemon; `docker build` of `infra/docker/api.Dockerfile` | FAILED here (no daemon). B's records do not show it passing; unverified |
| `tests/infra/test_four_nodes.py::test_four_nodes_keep_checkpoints_across_restart` | daemon; host ports; four node containers | ERROR here (no daemon). Unverified |
| `tests/infra/test_runtime_ports.py::test_only_proxy_ports_open_and_restart_recovers` | daemon; free host ports 80/443; existing `:dev` images | ERROR here. B reported 1 passed (15s) on its machine |

## To fix later
1. Run `uv run pytest tests/infra -q` on a Docker-capable machine (B) and record exact results per test here.
2. Decide whether these belong in the default `scripts/check.sh` gate or in a separate Docker job. Today they are in it, so any machine without a daemon fails the gate. Choose deliberately; do not hide failures by skipping.
3. Confirm they pass in GitHub Actions (`bootstrap` job) or file the real error.
4. Still not run anywhere on record: T08 real-DB test (`tests/storage/test_timescale_integration.py`, skipped by its own guard when Docker is down) and image builds for web/node.
