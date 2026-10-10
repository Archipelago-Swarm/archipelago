# Historical experiment artifacts (T09)

These files predate the T32 repair and describe code that differs from the current harness.
They are preserved unchanged (apart from the banner on `REPORT_T09.md`) so earlier claims can be
audited; do not cite them as current evidence.

- `REPORT_T09.md`: the original hand-written report (banner added).
- `out/`: the earlier 3-seed x 20-episode smoke bundle that sat in `experiments/out`. Its manifest
  hashes do NOT verify (it was already stale and inconsistent with its own manifest before the repair);
  treat it as unverified.
- `run_t09.py`: the original `experiments/run.py` (not importable as the current harness).
- The verifiable T09 bundle (12 seeds x 150 episodes) is `agents/handoffs/T09/evidence/` (outside
  T32's paths, untouched); its hashes are re-checked by `tests/experiments/test_run.py`.

Known defects it contains are listed in `experiments/diagnosis/idle_vs_learners.md`.
