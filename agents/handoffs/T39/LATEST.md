# Handoff: T39 Coordinator amendments (live-runtime.md section 13-14)

- State: IMPLEMENTED and locally validated; worktree branch, not pushed.
- Paths touched: services/coordinator/**, tests/coordinator/**, packages/adapters/sim2d/**, tests/sim/**.

## Invariant
The coordinator drives four fake nodes through multi-episode scenarios using exactly the section 14 message shapes. The fake nodes record any deviation (unknown/missing field in configure, reset, feedback, episode_end) in `violations`, and every scenario test asserts it is empty.

## Implemented (test that demonstrates it)
- A2 feedback: `executed_command`, `action_index`, `deadline_missed`; sent to every node asked to act (a missed node is told `stay`/0/true); all acks awaited, bounded `2*deadline_ms`, before act(t+1). `test_feedback_reports_...acks_precede_the_next_act_round` (journal order across nodes), `test_a_slow_feedback_ack_holds_back_the_next_act_round`, late-reply and stalled-node tests.
- A5 configure: once per run per node before the first reset, values from `Plan.node_config` plus world values read from the live world. `test_configure_is_sent_once_...`, `test_a_node_that_refuses_configure_...`.
- A4 episode_end `{episode, tick}` to every non-killed node (terminated and unavailable included), 202 `{window_id}` recorded, a stuck ack costs at most the control timeout and never stalls the run; reset timeout 8 s (> node's 5 s window wait). Reset now carries `fault_schedule` (section 14); `set_schedule`, `seed`, `episode_kind` are no longer sent.
- A9 plan: `COORDINATOR_PLAN_FILE` (one Plan, or `{"plans": {name: Plan}}`), read per request; `POST /v1/runs` takes `{run_config, plan_name?}`; request-supplied `plan`/`node_urls` is 422; plan name and file SHA-256 are in status and run manifest; missing/invalid file is 503 `plan_unavailable`; required in production.
- A10 snapshots: public stream shows only obstacles in the union of discovered cells (`Sim2DAdapter.public_snapshot`); admin route returns the contract snapshot (all obstacles) plus `privileged: {targets, found, battery}` with fresh event ids.
- A13: `Plan.battery_scale` (default 1.0, owned by the plan; refused in `COORDINATOR_WORLD_KWARGS`); fault windows ending after `min(min_survival_ticks, max_ticks)` are rejected before start. `min_survival_ticks` is verified against the real GridWorld.
- A14: `Sim2DAdapter.kill` (renamed from `remove_node`; vanish, discovered cells stay public), per-episode RunConfig (`<run>-e<k>`, env seed), adapter stamps are wall-clock and `sim_tick` global, `topology.links` from current allowed links (`snapshot(links)`). `MAX_RUN_ID` lowered 64 -> 56 for the suffix.
- A7: every coordinator record has `sim_tick = episode*max_ticks + tick`; plan ticks (fault, kill, outage) stay episode-local. Restart recovery converts back.
- Determinism: fake-node stalls are `threading.Event` holds released by the test after it observed the coordinator's reaction (no sleeps as stalls); the one timed test (`reset_waits_longer...`) waits 2.5 s on purpose (longer than the old 2 s control timeout, inside the 5 s window).

## Evidence (2026-10-10, this worktree)
- `uv run ruff check packages services tests`, `ruff format --check`, `uv run mypy`: clean.
- `uv run pytest tests/coordinator tests/sim -q`: 88 passed, repeated 3x (about 28 s each) while the machine was loaded.
- `uv run pytest -q -m "not docker" --ignore=tests/e2e`: 539 passed, 5 skipped, 1 failed: `tests/noderuntime/test_nonblocking.py::test_long_validation_and_checkpoint_do_not_stall_acting` (`decisions_accepted == 0`; node-runtime owner's timing-sensitive test, no coordinator or sim2d code involved; also fails when run alone on the loaded host).
- Not run: Docker/Compose, tests/e2e, real node runtime against this coordinator (T29).

## For the integrator
- Node runtime must accept section 14 shapes: `configure` command (the current `protocol.py` has none), `feedback` extra fields, `reset` with `fault_schedule` only, `episode_end {tick}` returning 202.
- API (owner B): `POST /v1/runs` to the coordinator must send `{run_config, plan_name?}` only; the plan file and `COORDINATOR_PLAN_FILE` must be mounted in Compose; the snapshot route response has an extra `privileged` key; `services/api/.../runs.py` calls `adapter.snapshot()` (still privileged, unchanged signature compatible).
- Single-computer cleanup (user request): no Computer A/B text exists in T39's paths. Remaining mentions are outside them (agents/controller.py `--machine`, agents/launch.py, agents/OWNERSHIP.yaml, agents/PROTOCOL.md, TASKS.yaml/STATUS.yaml machine fields, historical handoffs and agents/runs/*-A/B.md records, agents/operations/*). Integrator-owned; not edited here.
