# Remotion video plan (PLAN ONLY, nothing installed, UNVERIFIED)

Scope: optional (T11 slice 3). Allowed path `apps/demo-video/`. No `npm install` was run and no Remotion version has been checked or pinned. Pinning an exact version, and checking lockfile impact (lockfiles need serialized ownership), is the first step once assigned.

## Inputs (generated, never hand-typed)
`metrics.json`, `events.json`, `topology.json`, result figures from the T09 export, plus a run manifest (run ID, commit, hashes). Exact export names and schemas: PENDING-T09 (evaluation.md names the files but T09 has produced none). Reuse `@archipelago/contracts` types so compositions fail to compile on schema drift.

## Structure
- `src/data/load.ts`: reads exports, validates against contract schemas, fails the render if run ID or commit is missing.
- Compositions mirroring storyboard shots 3-8: MapReplay (drawn from `world_snapshot` poses and topology), TransferLog (from `learning_event`), MetricChart (per-seed points visible), ProvenanceCard (run ID, commit, artifact hashes), LimitationsCard.
- Every frame has a REPLAY or ILLUSTRATIVE corner badge. All numbers computed in `load.ts`; a check greps compositions for numeric literals in text outside an allow-list.
- Three.js 3D segment only if T12 yields real exported 3D episode data; otherwise omitted.

## Render steps (to verify once assigned)
1. Pin Remotion, add package (disk-heavy Chromium download; serialized lockfile change).
2. Preview with Remotion Studio; render MP4 at 1080p/30fps, about 3:00.
3. Write a render manifest (input hashes, commit, Remotion version, command) beside the MP4; keep the MP4 out of Git.

## Risks
Disk space, lockfile ownership, render time, data not final. The video is optional; the live/replay walkthrough is the primary deliverable.
