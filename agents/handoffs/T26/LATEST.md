# Handoff: T26

- State: CLAIMED (dispatched by the integrator in session; worker starts from this commit)
- Branch: see agents/TASKS.yaml
- Interface: agents/architecture/live-runtime.md (authoritative), ADR-0008
- Acceptance: agents/TASKS.yaml entry T26 (commands and assertions)
- Reserved paths: the task's owned_paths only

Worker: replace this file with plan, progress, evidence, attempts, files modified and next steps as you go.

## Worker plan (cloud/w1)
1. Read live-runtime.md sections 4 and 7, dqn.py, peer.py.
2. Add `torch_learner.py` (TorchLearner), checkpoint module, tests in tests/learning.
3. Run `uv run pytest tests/learning -q`.
