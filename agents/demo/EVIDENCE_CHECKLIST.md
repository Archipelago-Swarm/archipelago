# Evidence the final demo needs from T03-T10

Status as of base 7999daf. States come from BOARD.md and handoffs, not independent verification.

| Task | Needed by T11 | Why | State now |
|---|---|---|---|
| T03 sim2d | Seeded run, recorded-action replay, 900-tick scenario with split@300 and rejoin@600 | Replay fallback, timeline | board: done; demo scenario config not checked |
| T04 API | Real-adapter run via `/v1/runs`, WS stream, event paging | Live shots 2-4 | board: done; workspace wiring of sim2d pending per handoff |
| T05 transport | Seeded two-island schedule; topology in `world_snapshot`; peer envelope trace | Shots 4-6 | board: done |
| T06 dashboard | Run ID, LIVE/REPLAY badge, topology, per-node policy versions, transfer decisions, replay controls, disconnect never shown as live | Whole storyboard | in_progress; main has scaffold only; browser smoke pending |
| T07 learners | Separate-state DQN nodes, accepted/rejected transfer events with version lineage, fixed-policy and sham controls | Shots 5-6; transfer claim honesty | board: done; not verified by me |
| T08 persistence | Run/metric rows, Grafana panels | Optional Grafana shot; metric provenance | blocked: needs Docker; code unverified |
| T09 experiments | Manifest (commit, image, seeds, hashes, commands); metrics/events/topology exports; paired results with CIs; all failed and negative runs; baseline modes (independent, info-sharing, Archipelago; central/CTDE optional); controlled transfer test with sham/random controls; recovery time | Every number in script beats 3-8 | waiting; nothing exists |
| T10 deployment | Entrypoint URL or one documented command; smoke-test evidence; image+commit record; rollback note | Fresh-browser acceptance; "deployed" claim | waiting |
| T12 | 3D adapter spike status | Shot 8 limitations line only | in_progress on A |

## Acceptance traceability (T11 card)
- Every displayed number maps to run ID, artifact path, field, hash. Keep `agents/demo/PROVENANCE.md` (create when data exists).
- Live/replay/illustrative labels on every shot (see narrative doc section 2).
- Review the final script against evaluation.md allowed claims before recording.
- Fresh-browser run-through of the documented entrypoint: PENDING-T10; record date and result.

## Human actions likely needed
Decide whether to produce narration/video; approve any spend or host for the final demo (T10); provide a Docker-capable machine for T08/T10 verification.
