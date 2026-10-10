# ADR-0005: Tiered validation and CI concurrency

## Evidence

445 workflow runs in about 3 hours of the sampled window; `Foundation checks` ran on every push to every branch (70 of the latest 100 runs); `ci` had no `concurrency`, no path filters and mixed Docker tests into `check.sh`; 4 of 6 sampled `ci` PR runs failed; Docker tests failed first on a clean runner (`--no-build`) and had to be skipped, un-skipped and fixed over four commits.

## Problem

Every intermediate agent commit paid for the full suite; machines without Docker could not pass the gate.

## Root Cause

One gate for all purposes and no cancellation of superseded runs.

## Existing Mechanism

`scripts/check.sh`, `.github/workflows/ci.yml`, `foundation.yml`.

## Proposed Change

`make check-fast | check-integration | check-full` (PROTOCOL section 11). One workflow: `concurrency` cancels in-progress runs per ref; `fast` on every PR push; `integration` on PRs; `full` (Docker tests, container build) on main and manual dispatch; `foundation.yml` folded in. No deploy on agent branches (none exists yet).

## Expected Benefit

Fewer, cheaper runs; Docker-less machines can pass check-fast and check-integration.

## Risks

Docker-dependent regressions surface after merge to main rather than on the PR. Mitigation: `needs: docker` acceptance commands are verified by the verifier in CI before INTEGRATION.

## Rollback

Restore the previous workflow files from history.

## Status

ACCEPTED
