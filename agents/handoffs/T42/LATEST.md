# Handoff: T42 Owner C (Infra / Demo)

- State: integrated on main (PR #12, #22). Local Docker validation done for each docker test individually (a Docker daemon was available in the integrator session); the full docker slice is checked by CI on PR #22.
- Last updated at PR #22 head after commit `b36f454` (plan name in body, stop with latest revision, API command reply no longer terminates a run). Branch: `claude/elegant-pascal-a8a3hp`.
- Owned paths touched: `infra/**`, `tests/infra/**`, `tests/e2e/**`, `Makefile` demo-* targets only; PR #22 also fixed `infra/docker/api.Dockerfile` (coordinator package in the API image) and `infra/demo/artifacts.py`.
- Resolved since the first handoff: control-message and telemetry mismatches (items 1-3 below) are fixed by T39/T27/T29 amendments; `tests/e2e` (16 tests, ~80 s, no Docker) passes without the control shim; the plan name travels in the request body (`"plan": "<name>"`), not a query parameter.
- Still open: CPU-wheel node memory (only the CUDA wheel was measurable: ~390-400 MiB per node, limit stays 1g provisional), real Vultr/TigerData runs, `make demo` end-to-end on a clean machine, a regression test for the artifact generator fixes.

## Invariant

"One command (`make demo`) launches the whole stack reproducibly and writes demo artifacts."

Demonstrated offline: artifact generation from recorded events, the driver against a fake API (login, run, poll, paged events, artifacts), plans through the coordinator `Plan` model, compose rendering and network/port/secret invariants through `docker compose config` (no daemon needed), Dockerfile pins against `uv.lock`, and a real coordinator + four real node processes completing a train/validation/test run with a cut window (`tests/e2e`). NOT demonstrated: image builds, `compose up`, the API in live mode, `make demo` itself. Those need Docker and open items below.

## What exists

* `infra/docker/node.Dockerfile` (CPU torch pinned `==2.14.1`, non-root, OMP/MKL=1, only needed packages, healthcheck on :8080/healthz, entrypoint `python -m archipelago_noderuntime`), `infra/docker/coordinator.Dockerfile` (no torch). The stand-in `infra/node/entrypoint.py` and its test were deleted.
* `infra/compose/compose.yml`: coordinator + node-01..04, networks per A12 (peers/control/ingest/core; nodes not on core), required tokens, api live env, read-only plan mount, per-node volumes, restart policies, provisional limits (nodes 1g, coordinator 256m, both marked provisional), only the proxy publishes ports (`PROXY_HTTP_PORT` / `PROXY_HTTPS_PORT` configurable). `infra/compose/local.env` holds the DEV-ONLY values; `.env.example` keeps the secrets empty.
* `infra/demo/`: `plans/smoke.json`, `plans/demo.json`, `artifacts.py` (pure), `run_demo.py`, `measure_mem.sh`, `README.md`.
* Makefile: `demo-build demo-up demo-run demo-down demo` (`PLAN=smoke|demo`).
* Tests: `tests/infra/` (`test_compose`, `test_images`, `test_plans`, `test_demo_artifacts`, `test_run_demo`, `test_measure_mem` offline; `test_demo_stack`, `test_four_nodes` Docker tier; `test_runtime_ports`, `test_smoke_and_replay` adapted to local.env). `tests/e2e/`: `procs.py` launcher, `test_live_local.py`, `test_live_faults.py`, `test_live_contract.py`.

## Open items and the exact requests to other owners

1. Coordinator -> node control mismatch (owner A: T27 repair / T39). The nodes answer 422 to `reset` (extra `seed`, `episode_kind`), `set_schedule` (coordinator sends `{run_id, episode, schedule, schedule_sha256}`, node requires `{fault_schedule}`) and `episode_end` (extra `run_id`, `episode`). Without a fix no run can start against real nodes ("no node reachable at episode reset"). `tests/e2e/procs.ControlShim` rewrites exactly those three messages so the rest of the stack can be exercised; `test_live_contract.py::test_coordinator_control_messages_are_accepted_by_nodes` fails until the services agree. Delete the shim then.
2. Telemetry wire format (owner A node / owner B API). Node ships `{node_id, host, commit, config_hash, seed, records:[{event_id, phase, record}]}`; the API ingest accepts exactly `{source, boot_id, events}` (A7/8.1; `context` also pending), so every real node batch is a 400. Also `create_app_from_env` does not mount `make_router`, and does not read `ARCHIPELAGO_ADAPTER=live`, `COORDINATOR_URL`, `COORDINATOR_PLAN_FILE`. Failing guards: `test_node_telemetry_batches_are_accepted_by_the_api_ingest`, `test_api_telemetry_route_is_mounted_in_the_served_app`.
3. `POST /v1/runs` in live mode (owner B). `run_demo.py` posts the contract `RunConfig` as the body with `?plan=<name>` and an `Idempotency-Key` header (compatible with the current signature). If B chooses another shape (A9: "run config plus optional plan name") only `Api.start_run` changes.
4. A1 tick-cadence exchange windows are not implemented in the node runtime (exchange only at `episode_end`), so a cut inside an episode never intersects an exchange. Failing guards: `test_live_faults.py::test_exchange_windows_run_on_a_tick_cadence_and_see_the_cut`, `::test_an_offer_decision_is_logged_inside_an_episode_not_only_at_its_end`. The node has no `EXCHANGE_EVERY_TICKS` config yet (A5 `configure` is also not sent by the coordinator), so plans cannot set `exchange_every_ticks`.
5. `Plan` has no `battery_scale` (A13): the world is set by compose env (`DEMO_BATTERY_SCALE=4`, node `WORLD_BATTERY_SCALE`). `test_plans.py` fails if the model grows the field without the plans carrying it.
6. `n_targets` is 0 in the demo world on purpose: the sim ends an episode when all targets are found, which in the local smoke happened after 4 ticks. The return is exploration reward only. Decision for the orchestrator/T30 before the demo is presented; `DEMO_N_TARGETS` overrides it.
7. Checkpoint file names: the learner writes `model.npz`, A17 says `policy.npz`; `PEER_TOKEN` (A8) is passed to nodes but not read by the node runtime yet.
8. `.dockerignore` (root, integrator-owned) does not exclude `.claude/worktrees`, `artifacts`, `.pytest_cache`; add them to keep the build context small.
9. Node memory: local RSS with the CUDA wheel was about 712 MB at idle-training. Limit stays a PROVISIONAL 1g until `infra/demo/measure_mem.sh` runs on the CPU image (rule: 1.5 x peak rounded up to 64 MiB; 686 MiB peak would need 1088 MiB).

## T22 request ("fix the stalling on T22")

T22 (control-plane bootstrap) shows ACTIVE in the ledger on `claude/quirky-dirac-4eomw1` with a handoff at REVIEW awaiting a verifier, and blocks T20, T23, T25. Its paths (`agents/controller.py`, `agents/launch.py`, `agents/TASKS.yaml`, `.github/**`) are not mine and the ledger is integrator-only, so nothing was changed. Needed from the integrator: run the three acceptance commands on its last good commit, write `agents/handoffs/BOOTSTRAP/VERIFICATION.yaml`, `controller.py verify T22` then `complete`, or release the stale ACTIVE claim.

## Resume

`uv sync --frozen --group torch`; `uv run pytest tests/infra -q -m "not docker"` (offline), `uv run pytest tests/e2e -q` (about 4 minutes; 5 of the e2e tests fail for items 1, 2 and 4 above by design). On a Docker host: `make demo` (smoke), `make demo PLAN=demo`, `infra/demo/measure_mem.sh demo`.
