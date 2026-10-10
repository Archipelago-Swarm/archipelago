# Validation tiers (agents/PROTOCOL.md section 11). Run from the repository root.
.PHONY: check-fast check-integration check-full

# Seconds: docs/ledger, lint, format, controller tests.
check-fast:
	python3 tools/check_foundation.py
	uv run python agents/controller.py validate
	uv run ruff check packages services tests infra/vultr experiments agents/controller.py agents/launch.py
	uv run ruff format --check packages services tests infra/vultr experiments agents/controller.py agents/launch.py
	uv run pytest -q tests/agents

# Minutes, no Docker daemon needed: types, contract drift, full non-Docker pytest, web lint/test/build.
check-integration:
	SKIP_DOCKER=1 scripts/check.sh

# Expensive: everything including Docker-marked tests; CI runs this on main.
check-full:
	scripts/check.sh
	docker build -f infra/docker/ci.Dockerfile -t archipelago-ci .
	docker run --rm archipelago-ci
