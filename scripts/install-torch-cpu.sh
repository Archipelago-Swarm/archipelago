#!/usr/bin/env bash
# Install the pinned CPU-only PyTorch wheel into the project environment (CI and container images).
# The PyPI Linux wheel bundles ~3 GB of CUDA packages; the CPU index wheel does not.
# Local development where download.pytorch.org is unreachable: `uv sync --frozen --group torch`.
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=$(python3 - <<'PY'
import re, tomllib
deps = tomllib.load(open("pyproject.toml", "rb"))["dependency-groups"]["torch"]
print(re.fullmatch(r"torch==([0-9][^\s;]*)", deps[0]).group(1))
PY
)
uv pip install --torch-backend cpu "torch==${VERSION}"
uv run python -c "import torch; assert not torch.cuda.is_available(); print('torch', torch.__version__)"
