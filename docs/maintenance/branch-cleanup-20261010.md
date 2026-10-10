# Branch cleanup — 2026-10-10

Two independent janitor audits identified 36 remote branches whose tips are strict ancestors of main `a73546c8de8632b20d54a6539e10660a512efa2e`. Git ancestry was checked again immediately before deletion. No open PRs targeted these branches.

All 36 deletions succeeded in one atomic push, each guarded by an exact-tip force-with-lease. Remote heads were queried afterward: only main, agent/B/idle-watcher, and claude/quirky-dirac-4eomw1 remained. No code, commits, or main history were deleted.

## Preserved

- `main`: integration history.
- `claude/quirky-dirac-4eomw1`: still named by T22 in REVIEW; retain until ledger reconciliation.
- `agent/B/idle-watcher`: retain as an operational recovery reference until T23 passes.
- Existing local branches, worktrees, and any unpublished work were preserved.
- Legacy runner/driver/watchdog and mailbox files remain until the T23 prerequisite for T20 is satisfied.

The existing cleanup_branches.py requires an agent-coordination ref that no longer exists, so it was not run. The board now points live assignment ownership to TASKS.yaml. Task states were not changed.

## Deleted refs and recovery commits

Every commit below remains reachable through the audited main history. To recreate a branch when necessary, run `git push origin <SHA>:refs/heads/<branch>` with the corresponding values.

| Deleted branch | Commit |
|---|---|
| `agent/A/20261010T154653Z/report` | `e04f6c93d38f9c92b0786664ac2c41d57cdc3f6b` |
| `agent/A/T02/overnight-loop` | `075d05d7f8b45e366908085be4fbfdc60574bc36` |
| `agent/A/T02/t03-deps` | `a0f315541eba4393c6221ac9e2b37af2521aa31f` |
| `agent/A/T02/t04-preflight-fix` | `a0017082ddf8bd991a4241a46b06b1198ae1ccf6` |
| `agent/A/T03/review-fixes` | `36fdb19874bd45f5082b6b9cfeef06f96c2f9a5c` |
| `agent/A/T05/review-fixes` | `348443329ee6fa897b0dd47cb6aeb6aad161d2e5` |
| `agent/A/T07/review-fixes` | `44abd142d9bcbb757fdf6528b11172eb250e09c2` |
| `agent/A/T08/fanout` | `b4b09fef933d203d11bf2bd5dbc15555f192f9ee` |
| `agent/A/integrate/review-fixes` | `fca621021fc2beb67a4991217fbb8d00aee9a4f1` |
| `agent/B/20261010T061419Z/T06` | `f98e1887f3bf0b8b3c0d7d778488e845641154a2` |
| `agent/B/20261010T063026Z/T06` | `74f3411fe647d46e1eaa263fe00f42161b735c51` |
| `agent/B/20261010T132342Z/T06` | `51e7ba50b16fdafe3edc152550ddda51b49a5fb6` |
| `agent/B/20261010T154653Z/T10` | `ba4e79cc5975d4b43462eb658dbefa457c53b45d` |
| `agent/B/20261010T154653Z/report` | `912384e94d9a4a60266ea3428116536dad41294e` |
| `agent/B/T04/run-api` | `eb261fc37274a33450d8d1cea077a219d4be9a98` |
| `agent/B/T06/carry1` | `74f3411fe647d46e1eaa263fe00f42161b735c51` |
| `agent/B/T06/carry2` | `74f3411fe647d46e1eaa263fe00f42161b735c51` |
| `agent/B/T06/carryover` | `f98e1887f3bf0b8b3c0d7d778488e845641154a2` |
| `agent/B/T06/playwright` | `49f9ac5db3ef3abd0b154fd307351c50e88bea9c` |
| `agent/B/T06/reconciled-20261010` | `32a833af1c49a64e0982beddfedc333fa0033a9f` |
| `agent/B/T08/verify` | `74e11337f95892b4e3e41ce7ed92b3f8a9dc086f` |
| `agent/B/T10/carry-20261010T153519Z` | `84e19570e732ed48f60923a4c8e44c06dfa49e8b` |
| `agent/B/T10/prep` | `84e19570e732ed48f60923a4c8e44c06dfa49e8b` |
| `agent/B/T11/prep` | `2ba7de075ac137619e58bc5075950f831e3773a9` |
| `agent/B/mail-20261010T065101Z` | `b63e8184fb0f13ca5ffc2342cab2b0be19a835a5` |
| `agent/B/mail-20261010T065126Z` | `b63e8184fb0f13ca5ffc2342cab2b0be19a835a5` |
| `agent/B/mail-20261010T070251Z` | `fca621021fc2beb67a4991217fbb8d00aee9a4f1` |
| `agent/B/mail-20261010T070731Z` | `49f9ac5db3ef3abd0b154fd307351c50e88bea9c` |
| `agent/B/mail-20261010T071242Z` | `50a8a557ea9781eb331d47450929a9cf59d85921` |
| `agent/B/mail-20261010T071356Z` | `50a8a557ea9781eb331d47450929a9cf59d85921` |
| `agent/B/mail-20261010T071837Z` | `bcaf770c794bc4010eed421e05905f6a44863bc1` |
| `agent/B/mail-20261010T072155Z` | `426574f48159dbca55859f4e7ab63077d9fdf8a5` |
| `agent/B/readiness/lane-prep` | `c8614d6b6abb3d5e7a662ef315984df355b7d50f` |
| `agent/B/transport-413-drain` | `1094f041b655b47dcce2707384cf55ad2e437c56` |
| `claude/elegant-pascal-a8a3hp` | `331e8fce5587b6126df59e76c493f470e79981a4` |
| `fix/b-provisional-t04` | `0d8691ac91a52b4c026bf3459c9a0f7aa4349e46` |
