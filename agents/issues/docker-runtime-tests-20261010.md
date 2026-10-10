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
