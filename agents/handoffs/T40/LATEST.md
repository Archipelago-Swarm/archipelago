# T40 handoff (status: INTEGRATION-ready)

Base 276c80a. Reserved paths only: `packages/learning/**`, `tests/learning/**`, this file.

## Done
- A6 `archipelago_learning/encoders.py`: ids `grid-flat-v1-s{size}-r{radius}`, canonical definition and
  sha256 (`GridFlatV1.sha256`), `encode_observation` (contract Observation, duck-typed, pose floored)
  and `encode_raw` (GridWorld dict). Vector = crop row-major, floor(x)/size, floor(y)/size, battery.
  `compat.encoder_sha256` derives the hash from the geometry id, so header id+hash change with geometry.
  Both learners already took `encoder=`; TorchLearner default is now `grid-flat-v1-s8-r2`
  (the geometry-free `grid-flat-v1` was removed). NumPy `Learner` default remains legacy `grid-flat-v0`.
  Mismatch is rejected as `incompatible encoder: <id>` (or `encoder_sha256`).
- A1 `peer.OfferWindow` + `offer(..., window=)`: after the first acceptance, later candidates get reason
  `window_limit` before decode/eval (no validation cost). The current-policy score is memoised per window
  (keyed on learner.version): evaluated once; `window.evaluations` counts eval calls.
- A3 `checkpoint.SequenceAllocator(state_path, io=DurableIO)`: ceiling reserved in blocks of
  `SEQUENCE_BLOCK`=1000 and persisted (tmp+fsync+rename+dir fsync) before any number in the block is used;
  a new process starts at the persisted ceiling. A3 also needs the peer client `seq` persisted the same way;
  T27 can reuse this allocator.
- A17 constants: `CHECKPOINT_FILES`, `CHECKPOINT_EVERY_FEEDBACK_STEPS`=200, `checkpoint_due`, `replay_max_bytes`.
  Note: existing `TorchLearner.save/load` still use their pre-A17 generation file names; switching them to the
  A17 names is not done (needs a decision on counters.json content; not requested here).

## Tests
`tests/learning/test_amendments.py` (14 tests): raw and contract entry points equal sim `_flat` (pose
normalised) at sizes 8 and 16; hash varies with geometry; cross-backend id mismatch; window limit; one
current-score evaluation per window; allocator restart and injected crashes at write_tmp/rename/fsync_dir.
Existing expectation changed: `tests/learning/torch_support.py` ENC `grid-flat-v1` -> `grid-flat-v1-s8-r2`
(amendment A6 ids include geometry).

## Not run / caveats
- No Docker, no e2e (excluded). Integrator must wire `OfferWindow` into the node exchange window (T27).
- `archipelago_learning` tests import `archipelago_contracts` / `archipelago_sim` via conftest sys.path.
