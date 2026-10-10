# Handoff: T05 / 20261010T061419Z (worker A)

- State: in_progress (worker cannot mark done; awaiting integrator review)
- Reserved paths: packages/transport/, packages/node/peer/, tests/transport/

## Current state
- Memory `Network` (gates, seeded loss/delay/bandwidth, checks, dedupe, bounded inbox, stats, latest-only catch-up, retry), separate `Telemetry`, `load_manifest`.
- `PeerServer` (HTTP, same fault schedule; 200/202/422/400/404/413), `post`, `serve_manifest`, `PeerClient`.
- New this round: `PeerServer.set_links` detects a restored inbound link and POSTs `/catchup`; sender's `on_catchup` resends only the latest. `Network.last_seq` replaces the `_seen` reach-in.
- Tests added: cut/restore gated link -> receiver gets v1 and v3 only; bandwidth-deferred 202.

## Evidence (this round, worker-run)
- `uv run pytest -q tests/transport` 14 passed; `ruff check`, `ruff format`, `mypy` clean. Full suite and npm steps not run by worker; supervisor owns them.

## Known scope limits
- Reconnect detection is for the application gate (`set_links`), not real connection loss. No multi-process/netem tests (documented as pending in the README).
- 422 detection still compares aggregate rejected counts.

## History (earlier supervisor checkpoints; reviews below predate the fixes above)

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

## Supervisor checkpoint 2026-10-10T06:17:52Z

- Run: 20261010T061419Z
- Machine: A
- Task/branch: T05 / agent/A/20261010T061419Z/T05
- Base: ebf81adfd106fe3bbf8faf752dcf254e49ee6e95
- Round: 1
- State: in_progress
- External check exit: 0
- Independent review: {"pass": false, "issues": ["The reconnection acceptance check is only partly met. The check says reconnection requests a bounded latest update. In the code, nothing detects a reconnect and the receiver never requests anything. The caller must call PeerClient.catch_up (or the memory network's reconnect path) by hand. The README and handoff admit this. The HTTP catch-up test restarts a server instead of cutting and restoring a gated link, so no test shows a cut link being restored and then producing a bounded latest-only update.", "The final README and handoff changes are uncommitted. `git status` shows ` M agents/handoffs/T05/LATEST.md` and ` M packages/transport/README.md`. The task card requires committing and pushing with the implementation. The fault-scope documentation check is only satisfied in the working tree, not in the branch.", "The handoff is not ready for review. It says the supervisor external check passed 'earlier' and that the worker did not re-run the full suite, mypy or the npm steps. It has no final evidence section. Its 'Next' section still lists unfinished work (receiver-initiated catch-up, real network-fault tests).", "PeerServer.accept reads the private `net._seen` to tell delivered (200) from deferred (202). Its 422 check compares the sum of `rejected` counts before and after. Both are fragile reach-ins on Network internals. Nothing tests that a bandwidth-deferred message returns 202 and is later delivered, apart from the single fault-schedule test.", "There are no multi-process or real network-fault tests. The task card allows documenting these as pending, and the README does that, so this is not a blocker. It does mean that 'cut link' is verified only at the application level."]}
- Next issue: The reconnection acceptance check is only partly met. The check says reconnection requests a bounded latest update. In the code, nothing detects a reconnect and the receiver never requests anything. The caller must call PeerClient.catch_up (or the memory network's reconnect path) by hand. The README and handoff admit this. The HTTP catch-up test restarts a server instead of cutting and restoring a gated link, so no test shows a cut link being restored and then producing a bounded latest-only update.; The final README and handoff changes are uncommitted. `git status` shows ` M agents/handoffs/T05/LATEST.md` and ` M packages/transport/README.md`. The task card requires committing and pushing with the implementation. The fault-scope documentation check is only satisfied in the working tree, not in the branch.; The handoff is not ready for review. It says the supervisor external check passed 'earlier' and that the worker did not re-run the full suite, mypy or the npm steps. It has no final evidence section. Its 'Next' section still lists unfinished work (receiver-initiated catch-up, real network-fault tests).; PeerServer.accept reads the private `net._seen` to tell delivered (200) from deferred (202). Its 422 check compares the sum of `rejected` counts before and after. Both are fragile reach-ins on Network internals. Nothing tests that a bandwidth-deferred message returns 202 and is later delivered, apart from the single fault-schedule test.; There are no multi-process or real network-fault tests. The task card allows documenting these as pending, and the README does that, so this is not a blocker. It does mean that 'cut link' is verified only at the application level.
- Resume: fetch this branch, inspect latest commit and continue the task card.

## Supervisor checkpoint 2026-10-10T06:19:39Z

- Run: 20261010T061419Z
- Machine: A
- Task/branch: T05 / agent/A/20261010T061419Z/T05
- Base: ebf81adfd106fe3bbf8faf752dcf254e49ee6e95
- Round: 2
- State: review
- External check exit: 0
- Independent review: {"pass": true, "issues": ["Process: the implementation, tests, README and handoff changes are still uncommitted (git status shows M on all five files). They must be committed and pushed before human PR review, because the contract requires a pushed handoff.", "Weak test: test_seeded_loss_reproducible_and_send_nonblocking only checks that two seeded runs match. Its name claims non-blocking behaviour that it doesn't assert. Non-blocking sends are covered only indirectly, by test_telemetry_separate_and_partition_never_blocks.", "Known limit, documented: PeerServer.accept decides 422 by comparing aggregate rejected counts rather than the verdict for that envelope. A 202 (deferred) envelope is only delivered when a later request ticks the network.", "Known limit, documented: reconnect catch-up only detects links changed through set_links. Real connection loss and netem or multi-process faults are listed as pending in packages/transport/README.md, as the task card allows."]}
- Next issue: none
- Resume: fetch this branch, inspect latest commit and continue the task card.

## B-lane fix proposal: flaky `test_http_bad_requests` on Windows (2026-10-10 UTC)

- Symptom: `tests/transport/test_peer_http.py::test_http_bad_requests` failed ~2 of 3 runs on B (Windows) with `ConnectionAbortedError: [WinError 10053]`; it also fails the whole-repo check, which blocked T06 on B.
- Cause: `PeerServer`'s POST handler replied (404 for unknown paths, 413 for oversized bodies) without reading the request body. Closing a socket with unread bytes makes Windows reset the connection, so the client saw an abort instead of the status.
- Fix (branch `agent/B/transport-413-drain`, one file, `packages/node/peer/archipelago_peer/__init__.py`): always consume the request body first; bodies over the limit are drained in 64 KiB chunks (capped at 8x MAX_PAYLOAD) and discarded.
- Evidence: `uv run pytest tests/transport` passed 12/12 runs after the fix; ruff clean. No test change needed.
- Ownership: this file is in T05's reserved paths (A). B did not touch `main`; A or the integrator should review and merge.
