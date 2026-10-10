# T34 handoff: Vultr and TigerData operations tooling

State: DONE locally (committed on the worktree branch, not pushed).

Delivered in `infra/vultr/`: `archipelago_ops/{vultr,guard,tigerdata,deploy,__main__}.py`, README with
operator commands and evidence files, tests in `infra/vultr/tests/`.

Verified: `uv run pytest infra/vultr/tests -q` (44 passed, 1 skipped = Docker-only integration test).
Boundary tests at, just under and just over each guard limit; API key absence asserted in repr,
exceptions and inventory; secret absence asserted in dry-run output, deploy-log and tigerdata report.

Not run: the real TimescaleDB role check (`test_tigerdata_integration.py`, CI-only, needs Docker); any
real Vultr or TigerData call; any ssh execution (tests use a recording runner).

Assumptions to verify on the first real run: the sign convention of the Vultr account `balance`
(guard uses the absolute delta, conservative); `TIGERDATA_READER_URL` and `TIGERDATA_ADMIN_URL` are
extra env vars (writer/reader roles are NOLOGIN groups, so the operator creates login roles that
are members of them); compose `--profile prod` and images named `archipelago/{api,web,node}`.

Shared changes wanted (not made): add `infra/vultr` to the mypy `files` and ruff scope in
`pyproject.toml` if desired; add `infra/vultr/tests` to the CI pytest paths.
