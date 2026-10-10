# Handoff: T14 / 2026-10-10

- State: review
- Run / machine / worker: cloud/w3
- Branch / base commit: agent/T14-persist-run-events-so-replay-sur / origin/main e1d7c4e
- Last good commit: none yet
- Reserved paths: services/api/**, tests/api/**, tests/infra/test_smoke_and_replay.py

## Intended outcome and acceptance

Replay of a finished run equals the pre-restart replay after an api restart. `uv run pytest tests/api -q` (fast) and `tests/infra/test_smoke_and_replay.py` (docker, integration).

## Completed and verified

No code change needed: origin/main already contains the persistence (7fd67aa "Persist run events as per-run JSON Lines"): `services/api/.../eventlog.py` (append-only JSONL, torn-tail repair) wired in `runs.py`; `tests/api/test_event_replay.py` covers replay equality across restart, sequence continuation, corrupt tails, path safety. `tests/infra/test_smoke_and_replay.py` already asserts replay == before (no pinned-empty behaviour remains; grep for "empty" finds nothing).

## Validation

- `uv run pytest tests/api -q`: 43 passed.
- `make check-fast`: exit 0.
- `make check-integration` (after `npm ci`): exit 0.
- NOT RUN: `uv run pytest tests/infra/test_smoke_and_replay.py -q` (needs docker): this container has the docker CLI but no daemon (`failed to connect to the docker API at /var/run/docker.sock`), so the test errors in the fixture at `compose up`. Needs CI or a docker-capable verifier.
