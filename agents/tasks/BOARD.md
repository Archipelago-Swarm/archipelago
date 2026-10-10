# Task board

This is the initial dependency plan. The remote `agent-coordination` ledger owns live assignments; task branches own detailed progress/handoffs. Only the integrator updates this summary on main after integration. Do not have every worker edit this file.

| Task | Planned computer | Depends on | Initial state | Scope |
|---|---|---|---|---|
| [T01](T01.md) | A | none | ready | Bootstrap the executable workspace and freeze shared contracts |
| [T02](T02.md) | A | T01 | waiting | Implement durable coordination and the bounded overnight supervisor |
| [T03](T03.md) | A | T01 | waiting | Implement the seeded 2D environment and adapter |
| [T04](T04.md) | B | T01 | waiting | Build run lifecycle API and live/replay streaming |
| [T05](T05.md) | A | T01 | waiting | Implement peer transport and seeded network faults |
| [T06](T06.md) | B | T01 | waiting | Build the 2D dashboard and replay controls |
| [T07](T07.md) | A | T03, T05 | waiting | Implement independent learners and validated peer learning |
| [T08](T08.md) | B | T01 | waiting | Add TigerData persistence and Grafana observability |
| [T09](T09.md) | A | T07, T08 | waiting | Run fair baselines and reproducible partition experiments |
| [T10](T10.md) | B | T03, T04, T05, T06, T08 | waiting | Package and deploy the working stack to Vultr |
| [T11](T11.md) | B | T09, T10 | waiting | Create the measured demo narrative and optional Remotion video |
| [T12](T12.md) | A | T07 | waiting | Prove the open-source 3D adapter path |

## Dispatch rules

Only T01 is ready at initialization. When T01 merges, A can run T02 and T03 while B runs T04 and T08, within local slot limits. T05 follows an available A slot; T06 can start on B with fixtures after T01, then waits for real integration evidence. Do not mistake provisional fixtures for completed end-to-end work. T04/T06 final checks require T03/T04 integration even though their implementation can start earlier.

T07 depends on the environment and transport. T09 needs learning and persistence. T10 needs the real integrated demo; T11 follows usable evidence and deployment. T12 is lower priority than G1-G3. Reserve shared files explicitly; the lane table does not grant blanket ownership of contracts/lockfiles/CI.

Every interrupted task remains discoverable by branch, generation and latest remote handoff. Proposed extra tasks require the integrator to add an ID, owner lane, dependency and acceptance check before dispatch.
