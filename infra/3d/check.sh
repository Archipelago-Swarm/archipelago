#!/bin/sh
# Real 3D check: installs deps, then fails if any adapters3d test is skipped. Log: evidence/pytest-run.log
set -eu
pip install -r packages/adapters/pybullet/requirements.txt pytest
PYTHONPATH="packages/adapters/pybullet:packages/contracts/src" python -m archipelago_pybullet.smoke
python -m pytest tests/adapters3d -q -rs 2>&1 | tee packages/adapters/pybullet/evidence/pytest-run.log
! grep -qi skipped packages/adapters/pybullet/evidence/pytest-run.log
