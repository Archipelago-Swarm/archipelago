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

## Not done
- Manifest is loaded but not yet used to wire PeerServer URLs/clients automatically.
- HTTP path has no delay/loss/bandwidth schedule; no multi-process test.
- Did not run the npm steps of `scripts/check.sh`.

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
