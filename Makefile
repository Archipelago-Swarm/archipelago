# Validation tiers (agents/PROTOCOL.md section 11). Run from the repository root.
.PHONY: check-fast format check-affected check-integration check-full

# PR gate, seconds: static checks (cheapest first) + fast torch-free tests. Same command CI runs.
check-fast:
	CHECK_PART=gate scripts/check.sh

# Auto-fix what check-fast would reject on lint/format. Run before pushing.
format:
	CHECK_PART=format scripts/check.sh

# Lint plus only the tests touched by this branch (pre-push gate; full suite runs on main/nightly).
check-affected:
	scripts/check-affected.sh

# Minutes, no Docker daemon needed: types, contract drift, full non-Docker pytest, web lint/test/build.
check-integration:
	SKIP_DOCKER=1 scripts/check.sh

# Expensive: everything including Docker-marked tests; the Full Regression workflow runs this.
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
