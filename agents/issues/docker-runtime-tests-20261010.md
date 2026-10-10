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

## GitHub Actions result (PR #5, first CI run, job `bootstrap`, run 38069880407)

GitHub runners DO have a Docker daemon, so these tests actually ran there. Result: `143 passed, 3 skipped, 2 errors`.

- `test_four_nodes.py` and `test_runtime_ports.py` ERROR at fixture setup: `docker compose ... up -d --no-build <services>` exited 1.
- Likely root cause (from the compose file and test code, not yet reproduced): both tests start services with `--no-build`, but compose references prebuilt local images `archipelago/{web,api,node}:dev` (`infra/compose/compose.yml` lines 51, 59, 108). Nothing in `ci.yml` or the tests builds them, so a fresh runner has no such images. On B's machine they existed from earlier manual builds, which is why B saw a pass.
- Proper fix (deliberately NOT done here): have the tests or the CI job build the images first (`docker compose build`), then re-run on a clean Docker host. Then record real results here.
- `test_api_image.py` did not error in CI (it builds its own image); it only failed in the sandbox because no daemon exists.

## Unrelated finding: stray gitlinks on main

`.claude/worktrees/wf_37b0f56c-fca-2`, `wf_37b0f56c-fca-3`, `wf_fa014e97-0fa-1` are committed as submodule-style gitlinks (mode 160000) with no `.gitmodules` entry. They are leftover Claude Code worktree pointers to agent branch SHAs. They make `git submodule foreach` fail in the checkout cleanup step (warning only: `No url found for submodule path`). Not removed here; fix by `git rm --cached` them and ignoring `.claude/worktrees/`.

## Fix applied (pending CI confirmation)

- `tests/infra/test_four_nodes.py` and `test_runtime_ports.py` now start the stack with `up -d --build` instead of `--no-build`, so a clean host builds `archipelago/{web,api,node}:dev` itself. Not verified locally (no daemon); GitHub Actions is the first evidence.
- Stray `.claude/worktrees/*` gitlinks removed from the index and `.claude/worktrees/` added to `.gitignore`.

## Update after PR #5 merge (CI evidence)

- On GitHub Actions (main `1fd1ebd`, run 38073356624 / PR run 38073353702): `145 passed, 3 skipped`. The Docker runtime tests passed with `--build`, and `tests/storage/test_timescale_integration.py` ran and passed against real TimescaleDB. The 3 skips are pybullet (not installed).
- Locally (no daemon) the Docker tests still fail by design; they are not skipped.

## T10 fan-out (this branch) - what is and is not proven

New Docker-dependent tests, UNVERIFIED until CI runs them: `tests/infra/test_smoke_and_replay.py`, `tests/infra/test_rollback.py::test_rollback_to_previous_image_keeps_volumes`, and the new `import archipelago_storage, psycopg` assertion in `test_api_image.py`.

Known gaps, deliberately NOT hidden:
- T10 acceptance check 4 (replay retained across restart) is NOT met: `runs.py` keeps events in memory only. `test_smoke_and_replay.py` pins the current behaviour (empty events after restart) and must be changed to assert `replay == before` once events are persisted.
- Persister (TIGERDATA_URL) has no real-DB test and nothing calls `migrate()` on startup; if the `run` row is shed from the spool, later event rows can fail the FK and stall a batch (`packages/storage` Writer is all-or-nothing per batch).
- A non-local TIGERDATA_URL without sslmode only shows up as recurring flush failures.
- rollback.sh runs the CURRENT compose files (documented in its output); it does not check the running tag equals `<current-tag>`.
- Vultr/TigerData evidence (check 3), and spend inventory (check 5), need operator credentials/budget.

## Update: PR #6 CI and persistence fan-out (wf_b2b3ce5b-cd1)

- PR #6 CI: green on `76cf62c` after the smoke test waited for Grafana through the proxy. The earlier `grafana anonymous (502)` was a startup race, not a crash. Rollback Docker test and the api-image import check passed in CI.
- Now closed in code (CI still must confirm the Docker/DB parts): acceptance check 4 (replay across restart) via durable per-run JSONL events in the api; persister applies migrations at startup; FK-poisoned rows are quarantined and counted instead of stalling a batch; remote TIGERDATA_URL must set sslmode to require/verify-ca/verify-full and `host=`/`hostaddr=` overrides are judged; real-DB persister test added.
- Still open: Vultr/TigerData evidence (check 3), spend inventory (check 5), simulation coordinator as a compose service, real-DB behaviour of the FK salvage (psycopg `sqlstate` on a Timescale hypertable) until CI runs `test_persister_integration.py`.
- Verifier minor notes, deliberately left: event log reopens the file per event and fsyncs on status events inside the run loop (latency risk); case-insensitive filesystems alias ids differing by case (Linux target unaffected).
