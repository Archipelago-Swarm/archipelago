# 3D simulation infra (T12)

Heavy 3D dependencies live only in `packages/adapters/pybullet/requirements.txt`; core 2D CI and deployment never install them.

Build/run (see `packages/adapters/pybullet/README.md` for upstream SHA/license, evidence and retraining notes):

```
pip install -r packages/adapters/pybullet/requirements.txt
PYTHONPATH="packages/adapters/pybullet:packages/contracts/src" python -m archipelago_pybullet.smoke
python -m pytest tests/adapters3d -q
```

Headless only (`p.DIRECT`); a GUI viewer would not count as physics evidence.

`infra/3d/check.sh` is the dedicated 3D check (installs deps, fails on any skipped test); wire it into a separate CI job (CI files are outside T12 paths). Evidence: `packages/adapters/pybullet/evidence/` (`pytest-run.log` = 7 passed, 0 skipped).
