"""PreToolUse hook (Bash): refuse commands known to hang on this machine, so agents fail fast instead of stalling.

Blocks: pytest without a `timeout N` prefix; pytest on suites that spawn node processes/Docker; vitest in watch
mode; Docker/compose/make demo targets; starting the node runtime. Exit 2 = block, message goes back to the agent.
Override for a human: ARCH_ALLOW_SLOW=1 in the command's environment (not for agents).
"""

import json
import re
import sys

SLOW_DIRS = (
    "tests/infra",
    "tests/e2e",
    "tests/swarm",
    "tests/noderuntime",
    "tests/experiments",
    "tests/web",
)
cmd = (json.load(sys.stdin).get("tool_input") or {}).get("command", "")


def block(why: str) -> None:
    sys.stderr.write(f"BLOCKED by scripts/hook_no_hang.py: {why}\n")
    sys.exit(2)


if "ARCH_ALLOW_SLOW=1" in cmd:
    sys.exit(0)
if re.search(r"\bpytest\b", cmd) and not re.search(
    r"\becho\b|\bgrep\b|--version", cmd.split("pytest")[0][-12:]
):
    if not re.search(r"\btimeout\s+\d+", cmd):
        block(
            "prefix every pytest run with `timeout 240` (e.g. `timeout 240 uv run --frozen --group torch python -m pytest tests/sim -q`)."
        )
    bad = [d for d in SLOW_DIRS if d in cmd]
    if bad:
        block(
            f"{bad} spawn node processes/Docker and hang here. Test the logic in-process under tests/sim, tests/learning, tests/api, tests/contracts, tests/coordinator instead."
        )
if re.search(r"\bvitest\b", cmd) and not re.search(r"\bvitest\s+run\b|--run\b", cmd):
    block("use `npx vitest run` (watch mode never exits).")
if re.search(
    r"\bdocker(-compose)?\b|\bmake\s+(demo|check-full|check-integration|check-docker)\b|archipelago_noderuntime|run_demo\.py\s+up",
    cmd,
):
    block(
        "Docker, `make demo/check-full/check-integration` and starting node processes hang or need services unavailable here."
    )
sys.exit(0)
