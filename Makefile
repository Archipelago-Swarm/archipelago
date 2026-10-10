# Validation tiers (agents/PROTOCOL.md section 11). Run from the repository root.
.PHONY: check-fast check-affected check-integration check-full

# Seconds: docs/ledger, lint, format, controller tests.
check-fast:
	python3 tools/check_foundation.py
	uv run python agents/controller.py validate
	uv run ruff check packages services tests infra/vultr experiments agents/controller.py agents/launch.py
	uv run ruff format --check packages services tests infra/vultr experiments agents/controller.py agents/launch.py
	uv run pytest -q tests/agents

# Lint plus only the tests touched by this branch (pre-push gate; CI runs everything, in parallel slices).
check-affected:
	scripts/check-affected.sh

# Minutes, no Docker daemon needed: types, contract drift, full non-Docker pytest, web lint/test/build.
check-integration:
	SKIP_DOCKER=1 scripts/check.sh

# Expensive: everything including Docker-marked tests; CI runs this on main.
check-full:
	scripts/check.sh
	docker build -f infra/docker/ci.Dockerfile -t archipelago-ci .
	docker run --rm archipelago-ci

# One-command demo (infra/demo/README.md). PLAN=smoke (150 ticks, default) or PLAN=demo (900 ticks, cut 300, rejoin 600).
# Artifacts land in artifacts/demo/<run_id>/. Needs a Docker daemon; CI runs the smoke plan.
.PHONY: demo demo-build demo-up demo-run demo-down
PLAN ?= smoke
demo-build:
	python3 infra/demo/run_demo.py build --plan $(PLAN)
demo-up:
	python3 infra/demo/run_demo.py up --plan $(PLAN)
demo-run:
	python3 infra/demo/run_demo.py run --plan $(PLAN)
demo-down:
	python3 infra/demo/run_demo.py down --plan $(PLAN)
# up, run, down (down always runs; compose logs are saved on failure). Leaves artifacts/demo/.
demo:
	python3 infra/demo/run_demo.py all --plan $(PLAN)
