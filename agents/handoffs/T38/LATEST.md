# Handoff: T38 / adopt the T37-selected variant in the PyTorch live runtime

- State: review (ready for verification; NOT pushed, NOT merged; the integrator merges)
- Run / machine / worker: cloud session, T38 owner
- Branch / worktree / base commit: local branch `t38-live-variant` = `origin/main` + merge of local `t37-variant-study` (d615800), then T38 commits on top
- Last good commit: see `git log t38-live-variant` (last commit message starts "T38:")
- Reserved paths used: `packages/node/**`, `packages/learning/**`, `services/coordinator/**`, `tests/{noderuntime,learning,coordinator,e2e,infra}/**`, `infra/demo/plans/**`, `infra/compose/compose.yml` (env only), `agents/architecture/live-runtime.md`, this handoff. `packages/sim/**`, `packages/adapters/sim2d/**` and `services/api/**` needed no change (T37 already put `rew-v1` in the world; the adapter already takes the reward id from the RunConfig).

## Intended outcome and acceptance

Make the live decentralized nodes learn the way the T37 NumPy study did: observation `grid-flat-v2-visits-shared` (82 floats), reward `rew-v1`, learner schedule (epsilon 1.0 to 0.05 over the first 50% of the training episodes, lr 1e-3, replay 50000, double DQN), versioned ids end to end, shared visited-cell summaries over the existing peer channel. Acceptance (1)-(6) of the assignment:

| # | acceptance | result |
|---|---|---|
| 1 | node-side encoder equals the NumPy harness encoder on fixed states | PASS: `tests/noderuntime/test_v2_parity.py`, 5 seeds x 2 ids, element-wise equality at every tick of 70-tick random-action episodes (at least 80 vectors per case, asserted), plus golden hashes `tests/noderuntime/golden_v2_parity.json` that pin the harness and the node encoder |
| 2 | coordinator world with `rew-v1` equals the harness per step | PASS: `tests/coordinator/test_reward_ids.py`, 3 seeds, scripted actions through the real coordinator + fake nodes, per-step rewards identical to the harness and the total equal to the rew-v1 component formula |
| 3 | TorchLearner regression on v2 obs / rew-v1 | PASS: `tests/learning/test_v2_learner.py` (200 episodes, validation seeds 100-104: +51.7 vs idle -39.0 vs untrained -236.9); Torch double-DQN equals the NumPy reference step by step |
| 4 | e2e with the new ids incl. partitions and restart | PASS: `uv run pytest tests/e2e -q` (24 passed) |
| 5 | non-docker suite, ruff, mypy; plans and compose | PASS, see Validation |
| 6 | handoff + A18 | this file and `live-runtime.md` section 15 |

## Completed and verified

**Ids.** Encoders `grid-flat-v2-visits-s{S}-r{R}` (57 floats at R=2) and `grid-flat-v2-visits-shared-s{S}-r{R}` (82), reward `rew-v1` (selected by `Plan.reward_id`, authoritative over `RunConfig.reward_id`), learner schedule `sched-t37-v1` (registry in `archipelago_learning.schedules`, mirrored in `archipelago_coordinator.models.LEARNER_SCHEDULES`, a test keeps them equal; `sched-v0` is the legacy recipe). Recorded in: coordinator status and `manifest.json` (`ids`), node status, node checkpoint identity (`counters.json`: encoder, encoder_sha256, reward_id, learner_schedule, double_dqn), peer model payload header (encoder, encoder_sha256, reward_id and, recorded not matched, learner_schedule), node telemetry (metric `ids:<encoder>:<reward>:<schedule>`).

**Rejections (named reasons).** Peer candidate with another encoder or reward id: `incompatible encoder: ...` / `incompatible reward_id: ...`. Checkpoint with another encoder/reward/schedule: `checkpoint encoder mismatch` / `reward_id mismatch` / `learner_schedule mismatch` (identity fields reordered so the versioned ids are named first). A pre-A18 checkpoint reads as `sched-v0`/single DQN and loads only into a legacy-configured node. Configure that contradicts the registry, names an unknown id or a wrong geometry: 422 (node and, earlier, the coordinator).

**Node.** `NodeMemory` (`archipelago_learning/visits.py`): buffer from the crops, stand-on counts from the poses, idempotent per tick, reset per episode, checkpointed and restored. `Node.act/feedback` encode under `amu` (v1 path unchanged). Per-training-episode epsilon (`train_ep`, persisted). Double DQN in `TorchLearner` (`double=`). The node-private validation world uses the same encoder, memory and (shared) a per-tick visit swap between its drones, and the run's reward id. The replay checkpoint stores only the filled prefix.

**Visit summary (`visit-summary-v1`).** `archipelago_noderuntime/summary.py`; wire format, size bounds (32 B bitmap at 16x16, at most 8 KiB at 256x256, payload <= 16 KiB), cadence, authentication, staleness, episode matching and the partition behaviour are specified in `live-runtime.md` section 15. Full-state bitmap per message (a lost or cut message is repaired by the next one). Sender thread per peer, never in the act path. Gated on send (node's own schedule) and on receive (`GatedPeerServer.accept` before the message class is looked at, and again inside the handler). Own counters (`summaries_*`); no offer counter, inbox, window or `LearningEvent` is touched.

**Plans and compose.** `infra/demo/plans/{smoke,demo}.json` carry `reward_id: rew-v1` and `node_config {learner_schedule_id: sched-t37-v1, encoder_id: grid-flat-v2-visits-shared}`; `battery_scale` stays 4. `compose.yml` `x-node-env` gains `ENCODER_FAMILY`, `REWARD_ID`, `LEARNER_SCHEDULE_ID` (T37 defaults, overridable by `DEMO_*`). `tests/infra/test_plans.py` checks plans, resolution and that the compose env is itself a valid node configuration.

## Validation

Working directory: the worktree. In this sandbox torch lives only in the main checkout venv, so the worktree venv has a `.pth` to it (`.venv/lib/python3.13/site-packages/zz_main_torch.pth`); with a normal `uv sync --group torch` nothing differs. Commands use `uv run --no-sync`.

| command | result |
|---|---|
| `uv run pytest -q -m "not docker" --ignore=tests/e2e` | `772 passed, 3 skipped, 12 deselected` in 312 s (baseline before T38: 696 passed + 1 pre-existing flaky failure) |
| `uv run pytest tests/e2e -q` | `24 passed` in 93 s (real coordinator + 4 real node processes; 16 pre-existing tests now run under the T37 ids, 8 new ones in `tests/e2e/test_live_t37.py` and `test_live_faults.py`) |
| `uv run ruff check packages services tests infra/vultr experiments agents/controller.py agents/launch.py` and `ruff format --check` (same paths) | clean |
| `uv run mypy` | Success: no issues found in 34 source files |
| `CHECK_PART=lint SKIP_DOCKER=1 scripts/check.sh` | foundation, ledger validate, ruff, format, mypy, contract drift export check: all pass (web slice not run) |

Baseline before my changes (origin/main + T37, same venv): `1 failed, 696 passed, 3 skipped` where the one failure, `tests/infra/test_compose.py::test_dev_values_live_only_in_local_env_and_are_distinct_and_long`, is pre-existing (it passed in the full run on my branch and in an isolated run, so it is order/environment dependent) and unrelated to T38.

Parity evidence in numbers: the 82-vector from `NodeMemory` + `GridFlatV2` is bit-equal (`np.testing.assert_array_equal`) to `experiments/protocol_harness.flat` for seeds 3, 11, 42, 77, 123, both ids, every tick of a 70-tick random-action episode with 2 drones in the T37 world (16x16, 8 targets); the shared fixtures contain non-trivial peer flags, own counts above 1 and fractional frontiers (guard test against a vacuous pass). The peer flags go through the real summary codec in that test.

Learner regression (T37 numbers: idle -39.0, untrained about -180 on selection worlds, 400-episode learner +34.9): with 200 episodes, validation seeds 100-104, I measured seeds 0-3 (outside pytest, no RNG draws before training): +51.7, +7.7, -13.0, +45.8; untrained -237 to -323; coverage gain 0.65-0.71; targets after spawn 5.8-6.6. The test (seed 0) asserts learned > idle + 15, learned > untrained + 100, coverage gain > 0.5, targets > 3. 100 episodes was too noisy (one stream gave -41), so the budget is 200 (about 60 s).

## Decisions and deviations (reversible, documented)

1. **No map merge.** The study's InfoBus also merged peers' MAP cells into each drone's buffer. The live world has no such merge and the assignment names visited-cell summaries only, so crop and frontier see the node's own sensing. Parity is therefore with the harness run with the visit half of the bus only. Whether the merge mattered for the +35 return is not ablated (T37 limit); a follow-up could add map cells to the summary.
2. **Timing of the flags.** The study's flags include the peers' current-tick position; live they come from the latest received summary (asynchronous, typically one or a few ticks old). This is the design the assignment asked for; parity is on the state, not on the arrival time.
3. **Plan reward overrides RunConfig.** `infra/demo/run_demo.py` (outside my scope) still builds RunConfigs with `rew-v0`; `Plan.reward_id` replaces that legacy default and records `reward_source: plan`. A non-default, different id is refused.
4. **Summary = full state, not delta**, keyed per sender; flags persist after a cut within the episode (information already obtained), nothing new crosses.
5. **Epsilon span** = `ceil(0.5 * training episodes)` (study: `0.5 * 400 = 200`). Epsilon is constant within an episode; eval episodes do not count.
6. **Telemetry ids** ride in a metric name because the ingest `Context` is `extra=forbid` and the canonical records have no field; no API change.
7. **Replay checkpoint prefix**: 50000 rows of float32[82] would otherwise be written (and compressed) as full-capacity arrays under the learner lock at every checkpoint. The A17 bound is unchanged; old full-ring files still load.
8. `tests/noderuntime/support.py::MiniCoordinator` and `tests/coordinator/coord_harness.py::CONFIGURE_KEYS` were extended (reward id parameter; new configure key).

## Limits and what was NOT run

- Docker / Compose path (`docker`-marked tests, `make check-full`, `make demo`): not run (no daemon). The compose env change is covered only by offline tests. Node `mem_limit: 1g` is unchanged and unmeasured for the new replay (about 33 MB of float32 replay per node on top of the torch baseline); `infra/demo/measure_mem.sh` was not run.
- `make check-integration` web slice (npm gen:check/lint/typecheck/test/build): not run (no node_modules). The Python slices above were run.
- No new learning study: live 4-node learning curves under partitions were not measured. The T37 verdict stands (learning beats idle/random/untrained; does not beat the rule explorer on return).
- Summaries are tested with 2 and 4 real node processes and hand-made envelopes; no load test beyond the e2e (3 sender threads per node, one POST per tick per peer).
- The validation world's visit swap is lag-free (study-like); live it is asynchronous. Model-selection scores are therefore slightly optimistic about the flags.
- `NodeMemory` counts only ticks that reached the node; after a missed deadline gap the skipped tick leaves no count.
- `experiments/` untouched.

## Next steps

1. Integrator: merge `t38-live-variant` (it contains the unpushed T37 merge commit; push `t37-variant-study` first if T37 is merged separately).
2. Measure node RSS with the 50000-row replay (`infra/demo/measure_mem.sh`) and update the compose limit per A16.
3. Run the compose smoke plan (`make demo`) once a daemon exists.
4. Optional study: add peer map cells to the summary and ablate it; run live curves for `sched-t37-v1` over 400 training episodes.
