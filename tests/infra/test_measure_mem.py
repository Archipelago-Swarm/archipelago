# ruff: noqa: E501  (long prose and SVG/f-string lines)
"""The memory-limit rule of amendment A16 (infra/demo/measure_mem.sh --rule) and the provisional node limit."""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/demo/measure_mem.sh"


def rule(peak):
    return int(
        subprocess.run(
            ["bash", str(SCRIPT), "--rule", str(peak)], capture_output=True, text=True, check=True
        ).stdout
    )


@pytest.mark.parametrize(
    ("peak", "limit"),
    [(686, 1088), (640, 960), (1, 64), (100, 192), (426, 640), (428, 704)],
)
def test_limit_is_one_and_a_half_times_peak_rounded_up_to_64_mib(peak, limit):
    assert rule(peak) == limit
    assert limit % 64 == 0 and limit >= peak * 1.5 and limit - 64 < peak * 1.5


def test_script_has_valid_bash_syntax():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_node_limit_is_marked_provisional_in_compose():
    text = (ROOT / "infra/compose/compose.yml").read_text()
    assert (
        re.search(r"PROVISIONAL limits: mem_limit 1g", text)
        and "686 MiB" in text
        and "1.5 x peak" in text
    )
