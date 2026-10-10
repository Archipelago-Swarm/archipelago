# Decisions needed from the operator (T10, T18, T23, T31)

Each has a proposed default. Answering "default" for all four unblocks everything except what needs your cloud accounts.

## T23 Cloud trial of the launcher: ledger-branch protection
Question: may agents push ledger-only commits (`agents/TASKS.yaml`) straight to `main`, or should the ledger live on a dedicated branch?
Why it matters: `controller.py --remote` already did this successfully on 2026-10-10 (claims, T29 split), so main currently allows it. If branch protection is added later, every claim, start and review fails.
Default: keep allowing ledger-only commits to `main` from the agents' identity; add a rule that only `agents/TASKS.yaml` may be changed this way. Alternative: create `ledger` branch and pass `--ledger-branch ledger` everywhere (small change, protects main).
Unblocks: T23, then T20 (retire legacy runner) and the launcher claim in PROTOCOL 13.

## T18 3D adapter: public contract change
Question: approve changing the shared `Pose` contract so `z` can be nonzero in 3D runs, and adding `takeoff`/`land` commands (supersedes ADR-0002's "z stays 0")?
Why it matters: contracts, fixtures, generated TypeScript and the dashboard change together; a worker may not do this alone.
Default: z is optional with default 0 and is rejected in 2D runs; `takeoff`/`land` are additive commands that 2D adapters reject with a named error; contract version bump (minor); CI runs `infra/3d/check.sh`. Alternative: defer T18 entirely; the live experiment (T26-T31) does not need 3D.
Unblocks: T18 only. Not on the critical path.

## T10 Package and deploy stack to Vultr (local packaging is done)
Needs: a Vultr instance (region, plan), DNS name and HTTPS plan, TigerData service URL, and a spend cap.
Default proposal: one CPU instance, region nearest to you, Caddy with Let's Encrypt on a name you own (or an IP-only basic-auth deployment if there is no domain), TigerData free/lowest tier, hard cap $100 total and $200/month, instance stopped after each run.
Unblocks: T10, T11 (demo needs the deployed run).

## T31 Vultr and TigerData deployment with operational evidence
Same accounts as T10, so answer once. Needs the Vultr and TigerData connections attached to the agent environment (secrets via environment secrets, never in Git), selected resources, and approval of the cost estimate the agents will write after T29/T30 finish. Maximum five instances. It is gated on T29 and T30, so this decision is needed only when those reach COMPLETE; the estimate comes from the agents.
Default: approve T10 and T31 together as one deployment with the T10 caps.

What I cannot decide for you: spend, credentials, domain ownership, and the public contract change.
