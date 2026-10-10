# Handoff: T05 / 20261010T054510Z (worker A)

- State: in_progress
- Reserved paths: packages/transport/, packages/node/peer/, tests/transport/

## Completed
- `packages/transport/archipelago_transport/__init__.py`: memory `Network` (directed gates, seeded loss, delay, bandwidth, version/hash/size checks, dedupe, bounded inbox, byte stats, latest-only reconnect catch-up), plus `send_reliable` (timeout/retry/give-up in `tick()`), `load_manifest` (static manifest), and separate `Telemetry` channel.
- `packages/node/peer/archipelago_peer/__init__.py`: stdlib HTTP `PeerServer` (POST /envelope, reuses Network gate/validation; 200 accepted, 422 rejected, 400/404/413) and `post()` with timeout/retry.
- `packages/transport/README.md`: application-level fault scope and pending real network-fault tests.
- Tests (`tests/transport/`): 9 pass (`uv run pytest -q tests/transport`); ruff + mypy clean on packages/tests.

## Fault scope
See `packages/transport/README.md`. Application-level only; real network-fault tests pending.

## Round 4 worker update
- Peer: `PeerServer(**faults)` now takes seed/loss/delay/bandwidth; a message lost/rejected -> 422, deferred by delay/bandwidth -> 202 (no longer reported 200). Added `serve_manifest` (servers bound to manifest URLs) and `PeerClient` (send, `catch_up` resends only the latest update).
- Removed both `sys.path.insert` hacks from the package and tests; `tests/transport/conftest.py` sets paths (pyproject is shared, so no packaging change).
- New HTTP tests: 400/404/413, bad hash, bad version, stale, loss/delay status, manifest wiring + reconnect catch-up. Full `uv run pytest -q`: 54 passed; ruff clean. mypy and npm steps of `scripts/check.sh` not run.

## Not done
- No multi-process test; no real network-fault tests (documented in README).
- Nothing committed (supervisor owns commits).

## Next
Wire manifest to peer clients; real network-fault tests.

## Supervisor checkpoint 2026-10-10T05:54:07Z

- Run: 20261010T054510Z
- Machine: A
- Task/branch: T05 / agent/A/20261010T054510Z/T05
- Base: 2d71e98ab484ca79eb22bfa3e23270cd1edb2f7c
- Round: 1
- State: in_progress
- External check exit: 1
- Independent review: not run
- Next issue: External checks failed (exit 1); inspect local check log
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Worker update (round 2)
- Cause of external check failure: `ruff check`/`ruff format --check` on transport files (E501, E702, UP037, formatting). Fixed in `packages/transport/` and `tests/transport/` only.
- Verified: `uv run ruff check packages tests`, `ruff format --check`, `uv run mypy`, `uv run pytest -q` (46 passed). Did not run the npm steps of `scripts/check.sh`.
- Still not done: HTTP endpoints, timeout/retry, manifests, `packages/node/peer/`, telemetry-separation test.

## Supervisor checkpoint 2026-10-10T05:55:35Z

- Run: 20261010T054510Z
- Machine: A
- Task/branch: T05 / agent/A/20261010T054510Z/T05
- Base: 2d71e98ab484ca79eb22bfa3e23270cd1edb2f7c
- Round: 2
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["Implementation slice 1 is not done. There are no static manifests and no direct private HTTP endpoints. packages/node/peer/ does not exist. The handoff admits this.", "Implementation slice 2 is only partly done. Version/hash/size checks, deduplication and bounded queues exist. Timeout/retry does not, and there is no test for it.", "Telemetry as a separate channel is untested. The 'Partitioned peers never block acting' check is covered only by a send-nonblocking assertion in the seeded-loss test, and nothing exercises a separate telemetry path.", "The delay and bandwidth schedule has no dedicated test. The 4 tests cover cut/allowed links, reject cases, reconnect-latest and seeded loss. Bandwidth limits, delay and sent/dropped/received byte stats are not asserted.", "The fault-scope documentation exists only in the handoff. The task card requires the application-level scope and the pending real network-fault tests to be documented, and no architecture or docs file records them.", "The latest handoff still says state: in_progress with 'Not done' items. The worktree has uncommitted changes to the handoff, the transport package and the tests. The 'Independent review: not run' line is stale."]}
- Next issue: Implementation slice 1 is not done. There are no static manifests and no direct private HTTP endpoints. packages/node/peer/ does not exist. The handoff admits this.; Implementation slice 2 is only partly done. Version/hash/size checks, deduplication and bounded queues exist. Timeout/retry does not, and there is no test for it.; Telemetry as a separate channel is untested. The 'Partitioned peers never block acting' check is covered only by a send-nonblocking assertion in the seeded-loss test, and nothing exercises a separate telemetry path.; The delay and bandwidth schedule has no dedicated test. The 4 tests cover cut/allowed links, reject cases, reconnect-latest and seeded loss. Bandwidth limits, delay and sent/dropped/received byte stats are not asserted.; The fault-scope documentation exists only in the handoff. The task card requires the application-level scope and the pending real network-fault tests to be documented, and no architecture or docs file records them.; The latest handoff still says state: in_progress with 'Not done' items. The worktree has uncommitted changes to the handoff, the transport package and the tests. The 'Independent review: not run' line is stale.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Supervisor checkpoint 2026-10-10T05:57:45Z

- Run: 20261010T054510Z
- Machine: A
- Task/branch: T05 / agent/A/20261010T054510Z/T05
- Base: 2d71e98ab484ca79eb22bfa3e23270cd1edb2f7c
- Round: 3
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["Nothing is committed. The transport package, tests, README and handoff changes are uncommitted, and packages/node/ and packages/transport/README.md are untracked. The task card requires committing and pushing with the implementation, and the work cannot be PR-reviewed from this branch.", "The latest handoff (agents/handoffs/T05/LATEST.md) still says State: in_progress. Its 'Not done' list admits the manifest is not wired to peer clients, the HTTP path has no delay/loss/bandwidth schedule, and there is no multi-process test. It also says the npm steps of the check were not run. The 'Independent review: not run' lines and the earlier failing review are stale.", "Slice 1 is only partly done. The manifest is loaded by load_manifest but never used to build PeerServer URLs or clients. The HTTP path has no delay, loss or bandwidth schedule, so those faults exist only in the memory Network.", "The HTTP peer is covered by one test (test_peer_http.py). It checks accept, duplicate, cut link and unreachable. It does not test oversized, stale or bad-hash payloads, or the 400, 404 and 413 paths. It does not test reconnect catch-up over HTTP. Timeout/retry is tested over HTTP only by a single unreachable-peer case.", "PeerServer.accept calls net.send then net.tick and decides success by whether the rejected count changed. A message dropped by seeded loss, bandwidth or delay is therefore reported as 200 accepted, even though it never reaches the consumer. This is a stubbed-success path.", "The 'Reconnection requests a bounded latest update' acceptance check is covered only in the memory network. Nothing at the HTTP or peer level requests a catch-up on reconnect.", "packages/node/peer/archipelago_peer/__init__.py and tests/transport/test_peer_http.py use sys.path.insert hacks to import across packages. This is fragile and bypasses the project's packaging."]}
- Next issue: Nothing is committed. The transport package, tests, README and handoff changes are uncommitted, and packages/node/ and packages/transport/README.md are untracked. The task card requires committing and pushing with the implementation, and the work cannot be PR-reviewed from this branch.; The latest handoff (agents/handoffs/T05/LATEST.md) still says State: in_progress. Its 'Not done' list admits the manifest is not wired to peer clients, the HTTP path has no delay/loss/bandwidth schedule, and there is no multi-process test. It also says the npm steps of the check were not run. The 'Independent review: not run' lines and the earlier failing review are stale.; Slice 1 is only partly done. The manifest is loaded by load_manifest but never used to build PeerServer URLs or clients. The HTTP path has no delay, loss or bandwidth schedule, so those faults exist only in the memory Network.; The HTTP peer is covered by one test (test_peer_http.py). It checks accept, duplicate, cut link and unreachable. It does not test oversized, stale or bad-hash payloads, or the 400, 404 and 413 paths. It does not test reconnect catch-up over HTTP. Timeout/retry is tested over HTTP only by a single unreachable-peer case.; PeerServer.accept calls net.send then net.tick and decides success by whether the rejected count changed. A message dropped by seeded loss, bandwidth or delay is therefore reported as 200 accepted, even though it never reaches the consumer. This is a stubbed-success path.; The 'Reconnection requests a bounded latest update' acceptance check is covered only in the memory network. Nothing at the HTTP or peer level requests a catch-up on reconnect.; packages/node/peer/archipelago_peer/__init__.py and tests/transport/test_peer_http.py use sys.path.insert hacks to import across packages. This is fragile and bypasses the project's packaging.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Supervisor checkpoint 2026-10-10T05:59:46Z

- Run: 20261010T054510Z
- Machine: A
- Task/branch: T05 / agent/A/20261010T054510Z/T05
- Base: 2d71e98ab484ca79eb22bfa3e23270cd1edb2f7c
- Round: 4
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["The code and tests cover the acceptance checks. I read the code and tests but did not run them. The external check passed, with 54 tests passing. That covers cut and allowed links, duplicate, stale, oversized and bad-hash rejection, latest-only catch-up, delay, bandwidth and byte stats, timeout and retry, a separate telemetry channel, and HTTP 400/404/413/422/202 handling. The blockers are in the records around the code.", "The T05 work is not fully committed. Uncommitted changes remain to agents/handoffs/T05/LATEST.md, packages/node/peer/archipelago_peer/__init__.py, tests/transport/test_peer_http.py and tests/transport/test_transport.py. tests/transport/conftest.py is untracked. The 202 and 422 fault-schedule handling, the PeerClient and serve_manifest code, and the HTTP tests described in the handoff's round 4 update are all in this uncommitted set. The task card requires committing and pushing with the implementation, and a PR cannot be reviewed from this branch as it stands.", "The handoff agents/handoffs/T05/LATEST.md contradicts the code. Its 'Next' section still says 'Wire manifest to peer clients', but serve_manifest and PeerClient exist and are tested. The 'Completed' section says '9 pass' but the full suite is 54 (this task's tests/transport share of that is not stated). It also says 'Nothing committed' and 'mypy and npm steps not run', though the external check ran those steps and exited 0. The earlier failing review entries are stale. The file has no final state or evidence section. The contract requires an accurate handoff, so this must be reconciled.", "packages/transport/README.md says HTTP-level delay and loss schedules are pending. PeerServer now takes seed, loss, delay and bandwidth, and test_http_fault_schedule_is_not_reported_as_accepted tests it. The fault-scope documentation must be updated to say what is application-level and what real network-fault tests are still pending.", "'Reconnection requests a bounded latest update' is implemented as PeerClient.catch_up, a sender-side resend of the newest envelope. Nothing makes the reconnecting receiver request it, and nothing detects the reconnect. The handoff and README should state this scope. The HTTP catch-up test also simulates the reconnect by restarting the server, not by cutting and restoring a link."]}
- Next issue: The code and tests cover the acceptance checks. I read the code and tests but did not run them. The external check passed, with 54 tests passing. That covers cut and allowed links, duplicate, stale, oversized and bad-hash rejection, latest-only catch-up, delay, bandwidth and byte stats, timeout and retry, a separate telemetry channel, and HTTP 400/404/413/422/202 handling. The blockers are in the records around the code.; The T05 work is not fully committed. Uncommitted changes remain to agents/handoffs/T05/LATEST.md, packages/node/peer/archipelago_peer/__init__.py, tests/transport/test_peer_http.py and tests/transport/test_transport.py. tests/transport/conftest.py is untracked. The 202 and 422 fault-schedule handling, the PeerClient and serve_manifest code, and the HTTP tests described in the handoff's round 4 update are all in this uncommitted set. The task card requires committing and pushing with the implementation, and a PR cannot be reviewed from this branch as it stands.; The handoff agents/handoffs/T05/LATEST.md contradicts the code. Its 'Next' section still says 'Wire manifest to peer clients', but serve_manifest and PeerClient exist and are tested. The 'Completed' section says '9 pass' but the full suite is 54 (this task's tests/transport share of that is not stated). It also says 'Nothing committed' and 'mypy and npm steps not run', though the external check ran those steps and exited 0. The earlier failing review entries are stale. The file has no final state or evidence section. The contract requires an accurate handoff, so this must be reconciled.; packages/transport/README.md says HTTP-level delay and loss schedules are pending. PeerServer now takes seed, loss, delay and bandwidth, and test_http_fault_schedule_is_not_reported_as_accepted tests it. The fault-scope documentation must be updated to say what is application-level and what real network-fault tests are still pending.; 'Reconnection requests a bounded latest update' is implemented as PeerClient.catch_up, a sender-side resend of the newest envelope. Nothing makes the reconnecting receiver request it, and nothing detects the reconnect. The handoff and README should state this scope. The HTTP catch-up test also simulates the reconnect by restarting the server, not by cutting and restoring a link.
- Resume: fetch this branch, inspect latest commit and continue the task card.
