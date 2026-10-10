# Task board

This is the dependency plan. T01 is complete and the initial T02 runner is integrated; a live A/B trial remains before the first eight-hour run. The remote `agent-coordination` plan owns live assignments; task branches own detailed progress/handoffs. Only the integrator updates this summary on main after integration. Do not have every worker edit this file.

| Task | Planned computer | Depends on | Initial state | Scope |
|---|---|---|---|---|
| [T01](T01.md) | A | none | done (PR #1) | Bootstrap the executable workspace and freeze shared contracts |
| [T02](T02.md) | A | T01 | done | Implement durable coordination and the bounded overnight supervisor |
| [T03](T03.md) | A | T01 | done | Implement the seeded 2D environment and adapter |
| [T04](T04.md) | B | T01 | done | Build run lifecycle API and live/replay streaming |
| [T05](T05.md) | A | T01 | done | Implement peer transport and seeded network faults |
| [T06](T06.md) | B | T01 | in_progress | Build the 2D dashboard and replay controls |
| [T07](T07.md) | A | T03, T05 | done | Implement independent learners and validated peer learning |
| [T08](T08.md) | B | T01 | blocked: needs Docker; code unverified on agent/A/T08/fanout | Add TigerData persistence and Grafana observability |
| [T09](T09.md) | A | T07, T08 | waiting | Run fair baselines and reproducible partition experiments |
| [T10](T10.md) | B | T03, T04, T05, T06, T08 | waiting | Package and deploy the working stack to Vultr |
| [T11](T11.md) | B | T09, T10 | waiting | Create the measured demo narrative and optional Remotion video |
| [T12](T12.md) | A | T07 | in_progress | Prove the open-source 3D adapter path |

## Dispatch rules

At initialization T01 is ready for A. B owns T04 and may begin it provisionally once T01 has a pushed, locally validated review commit. B branches from that exact T01 commit, records it, and does not merge T04 until T01 passes CI and merges. This lets B build against the actual contracts while A finishes review. When T01 merges, A can run T02 and T03 while B continues T04 and takes T08 by separate assignment, within local slot limits. T05 follows an available A slot; T06 can start on B with fixtures after T01, then waits for real integration evidence. Do not mistake provisional fixtures for completed end-to-end work. T04/T06 final checks require T03/T04 integration even though their implementation can start earlier.

T07 depends on the environment and transport. T09 needs learning and persistence. T10 needs the real integrated demo; T11 follows usable evidence and deployment. T12 is lower priority than G1-G3. Reserve shared files explicitly; the lane table does not grant blanket ownership of contracts/lockfiles/CI.

Every interrupted task remains discoverable by branch, generation and latest remote handoff. Proposed extra tasks require the integrator to add an ID, owner lane, dependency and acceptance check before dispatch.
