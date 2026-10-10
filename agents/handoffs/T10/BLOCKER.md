# T10 blocker report

## Failing command

None. Local packaging and checks pass. The blocked acceptance items need resources an agent does not hold: acceptance check 3 (real Vultr URL and TigerData connection evidence) and the spend inventory in check 5.

## Error

No Vultr host, DNS name/HTTPS plan, TigerData connection string or spend cap exists in the repository or the agents' environment. `agents/CONTRACT.md` reserves cloud spend and credentials for the operator.

## Hypotheses attempted

1. Provide everything agents can without credentials: images, compose profiles, smoke script, rollback script, runbooks (`infra/runbooks/*`). Done, integrated in PR #5 and #6.
2. Run Docker-dependent checks in CI instead of locally. Done; CI ran them green on PR #5 (145 passed, 3 skipped).

## Files changed

`infra/**`, `tests/infra/**`, `services/api/**` (cookie, persister). See `agents/handoffs/T10/LATEST.md`.

## Last known-good commit

`fdee33e` (main after PR #6).

## Reproduction

`uv run pytest tests/infra -q` on a Docker host; `infra/scripts/smoke.sh` against a deployed host (not available).

## Recommended next action

Human supplies: Vultr instance or project and region, domain for HTTPS, TigerData service URL (via secret store, not Git), a spend cap. Then unblock with `python agents/controller.py unblock T10`. Independent code gaps that do not need credentials are tracked as T14 and T15; do them first.
