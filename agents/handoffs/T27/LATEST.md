# Handoff: T27 node runtime process (act / feedback / control / peer / telemetry)

- State: implemented; all T27 acceptance assertions covered by passing tests; awaiting integrator review. Not pushed (worker rule).
- Base: d30d299 plus merge of T26's reviewed commit 252232429cab1a7e7d6bc6452b80b71cc928facd (TorchLearner, generation checkpoints, peer compat).
- Interface: agents/architecture/live-runtime.md sections 3, 5, 7, 8; ADR 0008. Package README: packages/node/runtime/README.md.

## Plan / what was done

`packages/node/runtime/archipelago_noderuntime/` (`python -m archipelago_noderuntime`):

- `config.py` env-only configuration (token >= 16 chars enforced, validation/test seed overlap refused, config hash excludes secrets).
- `protocol.py` Pydantic internal protocol (act, feedback, control discriminated union); embedded Observation/Action are the canonical contract records.
- `encoder.py` grid-flat-v1 (float32[28]); equality with `GridParallelEnv._flat` + `_norm` is tested for sizes 8/10/16 over a rollout, and against `archipelago_learning.rollout._norm` itself for size 8.
- `node.py` the core: owns a `TorchLearner`, trains inline in `feedback`, idempotency per step key, 409 on stale, eval mode freeze, pause/resume, exchange worker thread, checkpoint/restore, telemetry emission, status.
- `peering.py` immutable `Schedule` (half-open windows on the node's own tick, pairs cut in both directions) and `GatedPeerServer` (subclass of `archipelago_peer.PeerServer`, refuses cut senders with 403 on receive).
- `validation.py` `ValidationWorld`: private single-drone `GridWorld`, node's own world config, configured validation seeds only, greedy, no optimizer; yields the GIL each step.
- `telemetry.py` segmented durable JSONL `Spool` (bounded, drop-oldest with persisted dropped counter, cursor in `state.json`, torn-tail recovery) and background `Shipper` (batch POST, backoff, poison-batch skip).
- `server.py` stdlib `ThreadingHTTPServer` front (bearer auth with constant-time compare, 256 KiB cap, 413 drains a bounded amount so the client sees the status), `runtime.py` assembly, `__main__.py`.

## Decisions (and why)

- **Training is inline in `feedback`, not a worker thread.** Bounded (`TRAIN_STEPS_PER_FEEDBACK`, default 1, about 1 ms); keeps "N feedbacks -> N steps" exact and reproducible; acting is isolated because `act` takes only the tiny `amu` lock and reads the immutable published snapshot with its own exploration RNG. Lock order fbl -> mu -> amu; `act`/`reset` only take amu. Tested with a stalled peer, a stalled sink and a long validation.
- **Exchange runs on one worker thread, `episode_end` is async** (`wait:true` optional, bounded). Concurrent requests coalesce (latest wins). While candidates are being validated optimizer steps are deferred (counter `train_deferred`) so the judged parameters are the parameters replaced; transitions are still stored. A pre-computed score cache feeds `peer.offer` so the real validation cost is recorded (`validation_seconds`, `evaluations`) and `offer` is a short critical section.
- **Window rule**: candidates tried best-first (ties by node id, so sorted order never changes the outcome); at most one accepted per window, others logged `window limit`; latest candidate per sender only; dedupe on `(sender, version, sha256)` persisted in the checkpoint.
- **`LearnerNode` is not used** (agreement said "adapt"). Its `poll` lacks per-window limit/ordering/lock discipline and its event ids lack the boot id. The runtime composes the same pieces directly (`PeerServer`, `post`, `Envelope`, `encode/decode/offer`). Flagging for the integrator.
- Envelope `seq` = policy version (monotone across restarts via the checkpoint). Unchanged policies are not re-offered (`offers_unchanged`); no backlog is ever replayed.
- A higher episode of the same run advances the node implicitly (counted) so a restarted container recovers without a `reset`; a different run_id is 409 `wrong_run` until `reset`.
- Sequence on restore = `max(checkpoint, highest spooled sequence) + 1`; `event_id = node-boot-seq`. Action records also consume the node sequence (so telemetry sequences have gaps by design; they are unique and monotonic).
- Fault pairs are treated as undirected. The exchange happens only at `episode_end`, so a window must cover the tick at which `episode_end` is issued (documented in the README; T30 run config must account for it: with the 900-tick episode and a 300-600 window, `episode_end` at tick ~899 will see an OPEN link and exchange normally).
- Telemetry wire format (T29 ingest must match): `POST` JSON `{node_id, host, commit, config_hash, seed, records:[{event_id, phase, record:<canonical LearningEvent|MetricSample>}]}`, optional bearer; 2xx acks; sink must dedupe on `event_id`; 400/413/422 skip the batch.
- Added unauthenticated `GET /healthz` (`{"ok": true}`) for container health checks; not in the agreement.
- No new third-party runtime dependencies (stdlib + numpy/torch/pydantic already required by the learner and contracts).

## Evidence (this worktree, torch 2.14.1+cu130 PyPI wheel, Python 3.13 venv)

- `uv run pytest tests/noderuntime -q` -> 52 passed (about 73 s)
- `uv run pytest -q -m "not docker" --ignore=tests/e2e` -> 383 passed, 5 skipped (pre-existing), 10 deselected (run before the last two small tests were added; the later `tests/noderuntime` run covers them)
- `uv run ruff check packages services tests` -> clean; `uv run ruff format --check packages services tests` -> clean; `uv run mypy` -> Success, no issues (mypy's configured file list does not include the new package, as before)
- Acceptance mapping:
  - idempotent act/feedback, stale 409, auth, oversize: `tests/noderuntime/test_http.py`
  - in-process training counts, eval freeze, pause: `test_http.py` (`replay_size == n`, `train_steps == n - batch + 1`, eval leaves steps/replay/version/policy hash/loss unchanged, epsilon 0, feedback 409)
  - stalled peer / stalled sink / long validation: `test_nonblocking.py` (p95 < 100 ms and max < 500 ms per call while a genuinely stuck peer connection / stuck sink request / 80-evaluation validation is in progress; the tests assert the stall was really in effect)
  - schedule cuts, zero offers while cut, accepted + rejected decisions with reasons, receive-side and send-side enforcement, incompatible reason, one-accept-per-window, mixing, information_only: `test_peers.py` (two or three real runtimes over localhost HTTP; donor `mover_policy` scores 20.8 vs `stay_policy` 4.6 in the validation world, asserted before use)
  - kill during every checkpoint write step then restart: `test_checkpoint.py::test_kill_at_every_checkpoint_write_step_restores_last_complete_generation` (injects a kill before each filesystem primitive of generation 2; restores gen 1 or complete gen 2, exploration schedule/steps/policy hash restored, sequence strictly greater than anything spooled, no event_id collision), plus a real `SIGKILL` of `python -m archipelago_noderuntime`, restart, continued sequences and graceful SIGTERM final checkpoint
  - spool bounded + counted drops + idempotent catch-up: `test_telemetry.py`
- **Measurements** (`PYTHONPATH=... uv run python tests/noderuntime/measure_node.py`, one real node process, 28-32-5 MLP, replay 5000, batch 32, 1 thread, 16x16 world, 900-tick validation with 3 seeds, 4-core box, PyPI **cu130** wheel):

| quantity | value |
|---|---|
| idle RSS (VmRSS) | 665.5 MiB (anonymous 360.0, file-backed 305.5) |
| RSS after 3000 feedbacks / 2969 optimizer steps | 680.0 MiB (anonymous 363.1, file-backed 316.9) |
| RSS after a full-size validation + checkpoint | 686.1 MiB (peak VmHWM 686.1) |
| act latency while training (HTTP loopback, n=2800) | p50 1.49 ms, p95 2.12 ms, p99 2.80 ms |
| feedback latency incl. one optimizer step | p50 3.49 ms, p95 4.97 ms, p99 6.29 ms |
| act latency during validation (n=115, 0.73 s window) | p50 1.85 ms, p95 2.36 ms, p99 2.80 ms |
| checkpoint write (`checkpoint` control) | 35 ms |

  These latencies include the measuring client's own urllib/connection overhead.
- **Compose memory limit proposal**: `mem_limit: 768m` per node (`mem_reservation: 512m`) as the value the current evidence supports on the PyPI wheel (peak 686 MiB, 12 percent headroom); **512 MB is not supported by measurement on this wheel**. About 317 MiB of the RSS is file-backed (shared-library pages, reclaimable under cgroup pressure) and 369 MiB is anonymous. The deployed image uses the CPU wheel, which I could NOT measure (download.pytorch.org is blocked), and which is expected to be much smaller, but that is an unverified expectation. Integrator action: run `tests/noderuntime/measure_node.py` inside the CPU-wheel image; if peak VmHWM is at most about 400 MiB, 512m is justified, otherwise keep 768m. Four nodes at the measured size need about 2.7 GiB on this wheel.

## Not run / limits

- CPU-wheel RSS (blocked), Docker/Compose, the 4-node localhost smoke and the 900-tick demonstration (T29/T30 own those). Multi-process peer exchange is covered by the in-process two/three-runtime tests plus a real subprocess receiving a candidate (`test_nonblocking.py`), not by four separate processes.
- Telemetry shipping was tested against a fake in-test sink only; the real API ingest does not exist yet.
- The exchange only runs at `episode_end` (per agreement); no periodic or reconnect-triggered exchange, and `PeerServer`'s `/catchup` endpoint is intentionally not wired (no backlog replay).
- `time.sleep(0)` GIL yield and `sys.setswitchinterval(0.001)` (set in `__main__` only) are what keep acting responsive during a pure-Python validation next to torch training; without the yield, feedback latency rose to hundreds of ms in my first attempt.
- Event sequences: Action records consume sequence numbers that are never spooled, so spooled sequences have gaps; after a kill, sequence numbers handed to Actions after the last checkpoint are not recoverable, but uniqueness of `event_id` is guaranteed by the boot id.

## Files modified

packages/node/runtime/README.md; packages/node/runtime/archipelago_noderuntime/{__init__,__main__,config,encoder,node,peering,protocol,runtime,server,telemetry,validation}.py; tests/noderuntime/{conftest,support,procs,measure_node,test_encoder,test_http,test_peers,test_nonblocking,test_checkpoint,test_telemetry}.py; this handoff. No shared files were edited. Shared-file requests: none required. (Integrator note: `pyproject.toml` mypy `files` and any Docker image PYTHONPATH need to learn about `packages/node/runtime`; I did not touch them.)

## Next steps

- T28/T29: coordinator must send `reset` with `fault_schedule`, issue `episode_end` with the right tick, and the API ingest must accept the telemetry batch format above and dedupe on `event_id`.
- Integrator: decide on the `LearnerNode` deviation; measure CPU-wheel RSS and fix the memory limit; T30 must check that `episode_end` ticks fall inside the cut windows if a cut exchange is to be demonstrated.
