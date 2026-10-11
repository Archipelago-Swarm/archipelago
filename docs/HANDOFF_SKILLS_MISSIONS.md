# Handoff: skills, missions and the learning pipeline -> frontend

Branch: `handoff/skills-missions-pipeline` (= `origin/main` at PR #45 + the skills branch + the missions branch + hang protection). Date: 2026-10-11.

**Scope.** We built and wired the backend: engines, contracts, telemetry, API and the web *data layer*. **We are NOT building the UI.** The frontend owner implements everything visible, and this document is the complete spec for doing it. The target is the landing page's **"Example snapshot"** (`apps/web/src/App.tsx`, shown when there is no `?run=`): a frozen frame of the finished engine, i.e. a **3D terrain simulation, scaled up** (400 x 500 km mission world), with mission, skill and learning panels around it.

## What exists after merging this branch

| Area | State | Where to read |
|---|---|---|
| Skill AI (grid pipeline): 4 measured skills per node (explore, avoid, acquire, energy), versions, source node, peer transfer gated on measured skill gain, checkpointed, `GET /v1/runs/{id}/skills`, web reducer + `SkillList.tsx` | Built, tested (Python 409 pass, web 108 pass) | Part 10 |
| Missions + dynamic map: per-episode map from `(run_seed, episode)`, `MissionSpec` (search_rescue, coverage), moving/appearing targets, shifting obstacles, `WorldSnapshot.mission`, `map_seed`/`mission_complete`/`mission_failed` metrics, plan + POST `mission`, `startRun`, `MissionHUD` | Built, tested | Part 20 |
| Standalone engines already on main: `packages/swarm` (decentralized DQN + skill artifacts over RF), `packages/mission` (400x500 km, 6 UAVs, RF, one P2P skill, SSE server) | Real, **not joined** to the grid pipeline or to `WorldSnapshot` | Parts 10, 20, 30 |
| Hang protection for agents on this Windows machine | Built | Part 30 section on Windows |

## Read this before starting (verified gaps that decide your work)

1. **Two engines, not one.** The pipeline (`services/coordinator` + 4 nodes + API -> `WorldSnapshot`) is what `apps/web` consumes. The 400x500 km mission engine emits its own camelCase frames and no terrain grid; nothing converts it to `WorldSnapshot`. Someone must either bridge it (frames -> poses/links + a `TerrainGrid`; grid 40x50 at 10 km fits the 256x256 contract limit) or render its frames directly (`MissionApp`/`MissionViewer` on main already do the latter).
2. **The Example snapshot today is fake.** It is the 150th synthetic `world_snapshot` from `startDemo()` (`apps/web/src/demo.ts`): 10x6 km, no mission, no metrics, no skills. App.tsx also discards every other demo record and passes `panels=undefined`, so no panel can render there. Parts 10/20/30 list exactly what the generator must additionally emit and which gates to relax.
3. **Not in any public contract:** active moving/appearing targets (only `targets_found`), skill adoption detail in the web model, a typed client for `/skills`.
4. **Learning honesty:** the T37 result is that learning beats idle/random/untrained but **not the rule explorer**; fleet-vs-isolated exchange benefit is unproven (`agents/STATUS.yaml`). The learner does not use the mission or shifting obstacles.
5. **Open verifier findings:** duplicate test basename `tests/sim/test_mission.py` vs `tests/mission/test_mission.py` breaks full `pytest tests` collection; `relocate` mission type missing; `MissionHUD` hides the map seed when no mission is set; `test_t30` seed changed 7 -> 1.
6. **Unrun here:** node runtime, infra, e2e, swarm and experiment suites hang on Windows and are skipped by `conftest.py`. Run them on Linux/CI before trusting the merge. Docs below were fact-checked by reading code, not by executing it; each part marks UNVERIFIED items.

## Decisions the frontend/pipeline owners must make

- Bridge the mission engine into `WorldSnapshot`, or give the viewer two data sources? (Part 30)
- Add a contract field for active targets? (Part 20)
- Which skill system drives the Example snapshot: the four measured pipeline skills (recommended, the only one wired to canonical events) or the swarm/mission skills? (Part 10)
- Who produces the frozen frame at 400x500 km: extend `demo.ts`, or record a fixture? (Part 30)

---

# 10. Skill AI and learning pipeline

Scope: everything about "skills" (named, measured, versioned capabilities a node has learned) that exists in the
`handoff/skills-missions-pipeline` worktree. Paths are relative to the repo root. Nothing here was executed
(the test suites hang on Windows); every statement is from reading code and tests. Where I could not verify
something it is marked **UNVERIFIED**.

## 0. Read this first: three skill systems, one is wired

| # | System | Where | Status | Reaches the web UI? |
|---|---|---|---|---|
| A | **Pipeline skills** (4 measured proficiencies per node) | `packages/learning/archipelago_learning/skills.py`, `packages/node/runtime/archipelago_noderuntime/node.py`, `services/api/src/archipelago_api/skills.py`, `apps/web/src/live.ts` | New (branch `skills`). Wired end to end: node -> spool -> canonical events -> API -> web reducer -> `SkillList.tsx` | Yes, but only in a live/replay run (`?run=<id>`), never in the landing "Example snapshot" |
| B | **Swarm skills** (frozen DQN weights as a hashed artifact, RF-gated transfer) | `packages/swarm/archipelago_swarm/` (`skills.py`, `node.py`, `store.py`), `docs/LEARNING_BACKEND_HANDOFF.md` | On main, standalone, **not wired** into coordinator/noderuntime (stated in the handoff doc section 30) | No. No JSON endpoint, no web code reads it |
| C | **Mission skill** (one scripted-behaviour skill `adaptive_search_spacing`) | `packages/mission/archipelago_mission/sim.py` (`Skill`, `Skill.to_dict`), `serve.py`, `FRONTEND_INTEGRATION.md` | On main, standalone pure-Python sim, own server on `127.0.0.1:8765`, own JSON shape | No web code reads it. `apps/web/public/mission/seed-1002.json` is its offline fallback file (nothing in `apps/web/src` imports it: **UNVERIFIED**, grep for `skill` in `apps/web/src` hits only `live.ts`, `Panels.tsx`, `SkillList.tsx`, `skills.test.tsx`) |

The three share the word "skill" and nothing else: different data models, different events, different id spaces.
Section 8 says how they relate and what must be unified. Section 9 is the field -> UI mapping. Section 10 is
what `demo.ts` must emit.

---

## 1. System A: the four skills

Source: `packages/learning/archipelago_learning/skills.py` (59 lines).

`SKILL_SPEC = 1` (line 11): bump when a metric below changes meaning. Nothing in the pipeline transmits it
(**not wired**: not in any event or endpoint).

| Skill name (the `<name>` in `skill.<name>`) | Meaning | Formula in `world_skills()` (lines 20-31) | Unit / range |
|---|---|---|---|
| `explore` | search coverage | `min(1, len(world.visited - world.obstacles) / max(1, free))`, `free = size*height - len(obstacles)` | 0..1 |
| `avoid` | obstacle and drone avoidance | `max(0, 1 - (wall_collisions + agent_collisions) / max(1, agent_ticks))` | 0..1 |
| `acquire` | target acquisition | `len(found_targets) / max(1, len(targets))` | 0..1 |
| `energy` | return-to-base / energy economy | mean over drones of `max(0, battery)` at episode end | 0..1 (battery is a 0..1 fraction) |

Order is fixed: `explore, avoid, acquire, energy` (dict order of `SKILLS`, used for tie-break in `best_gain`).
The names are free-form strings on the wire (`Id` pattern `^[A-Za-z0-9_.:-]+$`, max 128, `models.py:15`); the UI
must not hardcode only four. Note a name containing a dot would break `live.ts` (`split(".", 2)`), and the four
real names have none.

### 1.1 How proficiency is measured

* A skill's proficiency is **measured, not self-reported**: greedy (argmax over Q, no exploration, no learning)
  rollouts of the node's current policy parameters over fixed seeds, from the world's own counters.
  Property of the parameters only (docstring `skills.py:3-4`).
* Node side: `packages/node/runtime/archipelago_noderuntime/validation.py` `Validator.run(params, cancel)`
  (lines 54-97) returns `(mean_return, mean_skills)`. It runs one `GridWorld` episode per seed in
  `cfg.validation_seeds` (default `(9001, 9002, 9003)`, `config.py:74`; test seeds must not overlap, `config.py:119`),
  appends `world_skills(self.world)` per seed, then `mean_skills(...)` (arithmetic mean per skill, `skills.py:34`).
  Same call also yields the scalar score that gates peer adoption, so skills cost no extra episodes.
* Learning package (offline): `packages/learning/archipelago_learning/rollout.py:106` `eval_skills(params, seeds)`.
* Proficiency is **per node** (each node holds its own `learner.skills`); there is no fleet-wide aggregate anywhere
  in the backend.

### 1.2 Record shape and versioning

`learner.skills` = `{name: {"proficiency": float, "version": int, "source": str}}` (`skills.py:5-7`, `record()` lines 38-52).

| Field | Type | Meaning |
|---|---|---|
| `proficiency` | float 0..1 | last measurement |
| `version` | int >= 1 | count of measured changes: starts at 1 on first measurement; +1 only when `abs(old - new) > 1e-9` |
| `source` | node id string | node the *current* proficiency came from: itself after local training, the sender after a peer adoption. Unchanged if the proficiency did not move |

`best_gain(before, after)` (lines 55-59) returns `(skill_name, gain)`: the skill the candidate improved most,
ties broken by `SKILLS` order. Gain may be <= 0.

Real fixture of the shape (from `tests/api/test_skills_endpoint.py`, section 4): `{"proficiency": 0.5, "version": 2, "source": "node-02"}`.

---

## 2. Node emission

All in `packages/node/runtime/archipelago_noderuntime/node.py`.

### 2.1 When skills are measured and emitted

| Moment | Code | What happens |
|---|---|---|
| Each exchange window (`_exchange`, ~line 960-990) | `self._emit_skills(tick)` at line 989 | Emits metrics for whatever `learner.skills` holds right now. Runs when `not w.skip_exchange` (skipped in eval mode: `res["skipped"]="eval_mode"`) |
| Window has peer candidates (`_decide`, ~1070-1125) | `timed(own)` once per window, then `skills.record(L, skill_cache[digest(own)], cfg.node_id)` (line 1113) | The node's own current policy is validated; its proficiencies are recorded with `source = own node id` so training progress is versioned *before* any adoption |
| Window has no candidates and `w.final` (episode end) | `_measure_own_skills(w)` (lines 997-1003) | Runs `validator.run(own)`, `skills.record(learner, measured, node_id)` |
| Peer candidate accepted | `offer()` in `peer.py:329-330` | `skills.record(learner, ev["skills_after"], source=meta["node"])`: all four proficiencies replaced by the candidate's measured values, `source` = sender, `version+1` for those that moved |
| Window has candidates, none validated, not final | nothing | No new measurement; `_emit_skills` re-emits the old values |

Cadence: exchange windows are every `exchange_every_ticks` node ticks (default 50, `config.py:63`, env
`EXCHANGE_EVERY_TICKS`); episode-end windows have `w.final`. So a skill metric appears **at most once per window
per skill, not per tick**. Before the first window completes, a node has **no skill data** (`learner.skills` is
`{}` initially: `getattr(self.learner, "skills", None) or {}`, line 1006).

### 2.2 Metric samples (the only continuous channel)

`_emit_skills` (lines 1005-1009) for each skill in `learner.skills` emits two canonical `metric_sample` records:

| `metric` | `value` | `unit` | `phase` | Notes |
|---|---|---|---|---|
| `skill.<name>` | proficiency, float 0..1 | literal `"score"` | `"eval"` (hardcoded in `_metric(..., "eval")`) | one per skill per window |
| `skill_version.<name>` | version, int stored as float | `"source:<node_id>"` | `"eval"` | the unit carries the provenance; this is a convention, not a schema field |

Constraints that apply (all from `models.py`):
`metric` and `unit` are `Id` (1..128 chars, `[A-Za-z0-9_.:-]`), so `source:node-02` is valid; `value` is `Finite`
(non-finite values are dropped by `_metric`, `node.py:316-318`); `phase` is one of `train|eval|partition|recovery|other`;
`source_node_id` is the emitting node (the skills are attributed to the **node that holds them**, not the sender).

Example of one pair as produced by `rec.model_dump(mode="json")` (envelope fields from `Event`, `models.py:48-55`;
values illustrative, built from the code path, not copied from a captured run):

```json
{"schema_version":"0.1.0","event_id":"node-01-b3f2-e41","run_id":"run-1","source_node_id":"node-01",
 "sim_tick":150,"emitted_at_utc":"2026-10-11T12:00:00Z","sequence":212,
 "kind":"metric_sample","metric":"skill.explore","value":0.5,"unit":"score","phase":"eval"}
{"schema_version":"0.1.0","event_id":"node-01-b3f2-e42","run_id":"run-1","source_node_id":"node-01",
 "sim_tick":150,"emitted_at_utc":"2026-10-11T12:00:00Z","sequence":213,
 "kind":"metric_sample","metric":"skill_version.explore","value":2.0,"unit":"source:node-02","phase":"eval"}
```

The real contract fixture for a metric_sample (no skills) is `packages/contracts/fixtures/good/metric_sample.json`.

### 2.3 Learning events on peer decisions

`_emit_decision` (lines 791-826) emits one `learning_event` per validated offer, with
`skill=ev.get("skill"), skill_gain=ev.get("skill_gain")` (line 814). Fields and when they are non-null:

| Field | Type | When |
|---|---|---|
| `skill` | `Id` or null | Set only if `offer()` reached the skills check (after the score gate) i.e. the candidate got to `skills_fn`. Null for: peer flagged, window_limit, information_only, malformed payload, sender mismatch, safety fail, severe drop, `candidate not better than current policy`, nonfinite score |
| `skill_gain` | float or null | Same condition. Can be <= 0 on a rejection with reason `no skill improved` |
| `transfer` | `"accepted"` or `"rejected"` | `"none"` is used for plain training updates elsewhere; those carry no skill |
| `reason` | string | Accepted: `"source=node-02 v=1 sha256=<hex> margin=0.0123 required=0.0 cur=.. cand=.."`. Rejected: `"<reason text> (source=<id> v=<n> sha256=<hex>)"`. **Free text, not an enum**; do not switch on it, show it as is |

Example (field values from `tests/api/test_skills_endpoint.py`; the envelope and `reason` are illustrative):

```json
{"schema_version":"0.1.0","event_id":"ev-9","run_id":"run-1","source_node_id":"node-01","sim_tick":150,
 "emitted_at_utc":"2026-10-11T12:00:00Z","sequence":106,"kind":"learning_event",
 "update_count":10,"loss":null,"previous_version":1,"new_version":2,
 "transfer":"accepted","reason":"source=node-02 v=1 sha256=ab12.. margin=0.0500 required=0.0 cur=0.1000 cand=0.1500",
 "candidate_score":0.15,"bytes":2048,"wall_seconds":0.4,
 "policy_id":"p2","parent_ids":["root-node-01","root-node-02"],"origin_node":"node-02","generation_count":1,
 "flagged_peer":null,"skill":"explore","skill_gain":0.25}
```

Also emitted next to it (`node.py:818-826`): metric samples `peer_validation_seconds` (unit `s`),
`peer_validation_evaluations` (`count`), `peer_candidate_margin` (`score`).

---

## 3. Peer exchange gating

Source: `packages/learning/archipelago_learning/peer.py` `offer(...)` (lines 218-345). One call per candidate, at
most one acceptance per exchange window (`OfferWindow`; later candidates are rejected `window_limit` without being
evaluated).

Gate order (first failure rejects; every rejection produces `accepted=False, reason=...`):

| # | Check | Line | `reason` text (exact) |
|---|---|---|---|
| 1 | sender previously flagged | 258 | `peer flagged` |
| 2 | window already accepted one | 262 | `window_limit` (const `WINDOW_LIMIT`, line 198) |
| 3 | learner mode `information_only` | 264 | `information_only mode never loads parameters` |
| 4 | decode/format/shape/finite checks | 150-169 | `malformed payload: ..`, `incompatible format: ..`, `incompatible <field>: ..`, `bad tensor ..`, `nonfinite tensor ..`, `unknown base checkpoint`, `payload too large`, `bad lineage` |
| 5 | payload node != transport sender | 272 | `claimed node '<a>' != sender '<b>'` |
| 6 | mixing mode without alpha | 274, 279 | `mixing mode needs 0<alpha<=0.5`, `mixing needs mode=mixing and 0<alpha<=0.5` |
| 7 | safety check (`safety_fn`) fails | 283 | the safety reason; **flags the sender** (`learner.flagged`, event `flagged`) |
| 8 | non-finite scores | 292 | `nonfinite eval score` |
| 9 | candidate more than `max_drop` worse | 296 | `severe performance drop`; **flags the sender** |
| 10 | scalar gate: `new > cur + margin` | 298 | `candidate not better than current policy` (margin = `cfg.peer_margin`, default 0.0, env `PEER_MARGIN`) |
| 11 | **skill gate (new)**: best per-skill gain `> skill_margin` | 299-303 | `no skill improved` (`skill_margin` default 0.0; **the node does not pass it, so it is always 0.0**: `node.py:1121` passes only `skills_fn`) |

So a candidate is accepted only if it beats the current policy on the scalar validation score **and** improves at
least one skill measurably (test `test_candidate_without_skill_gain_is_rejected_even_if_score_improves`,
`tests/learning/test_skills.py`).

On acceptance (lines 304-338): weights replaced (or blended by `alpha` in mixing mode), `version += 1`, optimizer
reset, a new lineage DAG node is created (parents = candidate policy + own previous policy, `generation_count =
max(parents)+1`), then `skills.record(learner, skills_after, source=meta["node"])`. The receiver's four
proficiencies become exactly the candidate's measured ones (asserted: `prof(got) == prof(want)` in
`tests/noderuntime/test_skills_node.py`).

`reason` on the wire is the composite string from 2.3. The `LearningEvent` has **no `accept_reason` enum**; the
UI's Offers table shows the string verbatim (`Panels.tsx:74`).

---

## 4. API: `GET /v1/runs/{run_id}/skills`

* Route: `services/api/src/archipelago_api/app.py:252-255`, auth dependency `Depends(auth)` (same bearer auth as
  the other `/v1/runs/*` routes). Handler: `{"run_id": run_id, **skills_view(mgr.get(run_id).events)}`.
* Unknown run: 404 (`mgr.get` raises; asserted in the test: `c.get("/v1/runs/nope/skills").status_code == 404`).
* Fold: `services/api/src/archipelago_api/skills.py` `skills_view(events)` (lines 14-43). It reads **the canonical
  event list** of the run, in order, and keeps the last value seen:
  * `metric_sample` with `source_node_id` set and `metric` starting `skill.` or `skill_version.`: proficiency /
    version; `source` is parsed from `unit` prefix `source:`.
  * `learning_event` with `transfer == "accepted"` and truthy `skill`: appended to `adoptions`. Rejected events
    are **not** listed (even if they carry `skill`).
* There is no pagination, no per-skill history/time series, no filter parameter. Only the latest value per node
  per skill. A history would have to be rebuilt client-side from the event stream.

Response schema (**not** in `packages/contracts`: no pydantic model, no JSON schema, not in `generated/types.ts`;
the shape exists only in `skills.py` and the test):

| Path | Type | Meaning |
|---|---|---|
| `run_id` | string | echo |
| `nodes` | `{node_id: {skill_name: {proficiency, version, source}}}` | latest per node |
| `nodes.*.*.proficiency` | float 0..1 or **null** (if only `skill_version.*` arrived) | |
| `nodes.*.*.version` | int (0 if only a proficiency arrived) | |
| `nodes.*.*.source` | string or **null** (until a `skill_version` sample with `source:` unit arrives) | node id |
| `adoptions[]` | `{node, skill, gain, sequence}` | one per accepted peer adoption that named a skill |
| `adoptions[].node` | string | receiver (`source_node_id` of the learning_event) |
| `adoptions[].gain` | float or null | `skill_gain` |
| `adoptions[].sequence` | int | the learning_event's canonical sequence number |

Note `adoptions[]` does **not** name the sender. The sender is only recoverable from `nodes.<receiver>.<skill>.source`
(which is the sender at the time of that adoption, overwritten by later measurements) or from the `peer_envelope`
record, which the web reducer pairs with offers.

Real JSON, derived from the assertions in `tests/api/test_skills_endpoint.py` (that test injects events straight
into `mgr(c).get(rid).events`: it proves the fold, not that a live node produced them):

Events injected (sequence order): `skill.explore=0.25 (score)`, `skill_version.explore=1 (source:node-01)`,
`skill.explore=0.5`, `skill_version.explore=2 (source:node-02)`, `node-02 reward=1.0` (ignored),
a learning_event `accepted/explore/0.25` and one `rejected/avoid/0.0` (ignored).

```json
GET /v1/runs/<run_id>/skills
{
  "run_id": "<run_id>",
  "nodes": {
    "node-01": {
      "explore": { "proficiency": 0.5, "version": 2, "source": "node-02" }
    }
  },
  "adoptions": [
    { "node": "node-01", "skill": "explore", "gain": 0.25, "sequence": 106 }
  ]
}
```

A full four-skill, multi-node response would have the same shape with `avoid`, `acquire`, `energy` entries per node
(only `explore` is in the test). The web app does **not** call this endpoint (`apps/web/src/client.ts` has no
skills function; `grep skill apps/web/src` shows only `live.ts`/`Panels.tsx`/`SkillList.tsx`/test). The reducer
(next section) derives the same data from the event stream, which is what the page already receives. Use the
endpoint for a cold-start/backfill only; it is optional.

---

## 5. Checkpoint persistence

* Node state dict `Node._node_state()` (`node.py` ~1181) includes `"skills": getattr(self.learner, "skills", {})`.
  It is JSON and written with the weights as one transactional checkpoint generation by
  `Node.checkpoint()` (lines ~1184-1194) via `archipelago_learning.checkpoint.save`
  (generation dirs `gen-<n>`, `MANIFEST.json`, `CURRENT`, sha256-verified, keep-N GC:
  `checkpoint.py:100-135`). A checkpoint is taken at every episode end (`res["checkpoint"] = ...` when `w.final`,
  line ~992).
* Restore: `Node._restore()` (~lines 1196-1230) sets `self.learner.skills = n.get("skills", {})` (line 1221).
  A node restarted mid-run therefore keeps proficiency, version and source and keeps emitting the same
  `skill_version` numbers (test `test_skills_survive_checkpoint_restore`).
* `Node.status()` (~line 1291) exposes `"skills": {...}` in the node's own status dict. That is the node HTTP
  status, not the run API; the coordinator/API do not use it for the web (**UNVERIFIED** whether the coordinator
  polls it; the web path uses only the spooled events).
* A checkpoint written before this feature loads with `skills = {}` (default), no migration needed.

---

## 6. Contract types

`packages/contracts/src/archipelago_contracts/models.py`:

```python
class LearningEvent(Event):
    ...
    # Peer decisions: the skill the candidate improved most and its measured proficiency gain.
    skill: Id | None = None
    skill_gain: Finite | None = None
```

(lines 222-224). Generated schema `packages/contracts/schemas/learning_event.schema.json:158-183` (`skill`: string
`^[A-Za-z0-9_.:-]+$` 1..128 or null; `skill_gain`: number or null; both default null). Generated TS
`packages/contracts/generated/types.ts`:

```ts
export type Skill = string | null;       // line 144 (name collides with live.ts Skill: import types by name carefully)
export type SkillGain = number | null;   // line 145
export interface LearningEvent { ... skill?: Skill; skill_gain?: SkillGain; ... }  // lines 375-376
```

There is **no contract type for a skill record, for the `/skills` response, or for the skill metrics**. Skill
metrics are plain `MetricSample` records with a naming convention. The web-local `Skill`/`Skills` interfaces in
`live.ts:44-45` are not generated (and do not clash: `@archipelago/contracts` exports its own `Skill` alias, a
string; do not import both unqualified).

Related contract context needed by the same frozen frame: `WorldSnapshot.mission: MissionStatus | None`
(`models.py:187`, fields `id,type,map_seed,status,objectives[],time_budget_ticks,energy_budget,energy_spent,completed_tick,dynamics`).
That is the *pipeline's* mission model (part 20 of this handoff presumably), unrelated to system C's mission sim.

---

## 7. Web data model

### 7.1 `apps/web/src/live.ts`

```ts
export interface Skill { proficiency: number; version: number; source: string | null }   // line 44
export type Skills = Record<string, Record<string, Skill>>;                               // line 45  node -> skill -> Skill
export interface Panels { ... skills: Skills; ... }                                       // line 49
emptyPanels(): skills: {}                                                                 // line 64
```

Reducer `panelsReducer(s, {t:"record", record, at})` (line 158) accepts records with numeric `sequence` and string
`run_id`, ignores duplicates/out-of-order (`sequence <= lastSequence`), and routes `metric_sample` to
`applyMetric` (line 93). Skill handling is the `default:` branch (lines 117-123):

```ts
const [kind, name] = r.metric.split(".", 2);
if (!id || !name || (kind !== "skill" && kind !== "skill_version")) return node({});
const prev = s.skills[id]?.[name] ?? { proficiency: 0, version: 0, source: null };
const skill = kind === "skill"
  ? { ...prev, proficiency: v }
  : { ...prev, version: v, source: r.unit.startsWith("source:") ? r.unit.slice(7) : prev.source };
return { ...node({}), skills: { ...s.skills, [id]: { ...s.skills[id], [name]: skill } } };
```

Behaviours to know:
* Skill state exists only for nodes that emitted `skill.*`/`skill_version.*` with `source_node_id`.
* A node row appears in `panels.nodes` (touch) as a side effect.
* A `skill.*` sample alone yields `{proficiency: v, version: 0, source: null}` (renders `v0`, "not reported").
* **`learning_event.skill` / `skill_gain` are not read by the web reducer at all** (`applyLearning`, lines 147-155,
  uses only transfer/lineage fields). `Offer` (line 23) has no skill fields. So "which skill improved and by how
  much" is available on the wire but not in `Panels`. See gaps.
* `panelsAtFrame(records, frame)` (line 194) replays skill samples up to the selected snapshot, so scrubbing is
  correct for skills.
* State is bounded only by node x skill count; there is no history of proficiency (no sparkline source).

### 7.2 `apps/web/src/SkillList.tsx` (26 lines, rendered from `Panels.tsx:79`)

`<SkillList skills={p.skills} />`. Renders `<section aria-label="Skills"><h2>Skills learned</h2>` then a
`<table aria-label="Node skills">` or `<p>No skills measured yet.</p>`. One row per `node/skill`, sorted by node
then skill name, `data-skill="<node>/<skill>"`:

| Column | Source | Rendering |
|---|---|---|
| Node | key of `Skills` | text |
| Skill | inner key | text |
| Proficiency | `proficiency` | `<progress max=1 value=…>` plus `${(p*100).toFixed(0)}%` |
| Version | `version` | `v${version}` |
| Learned from | `source` | `null` -> "not reported"; `source === node` -> "own training"; else the source node id |

Tested by `apps/web/src/skills.test.tsx` (fold + render + empty state).

### 7.3 `apps/web/src/Panels.tsx`

`LivePanels` (line 41) composes `MissionHUD`, fault phase, per-node table, peer-offer table, **`<SkillList>`**,
`LineagePanel`, `Curves`, resources. Skills sit between "Policy candidate offers" and "Lineage".

### 7.4 Where this renders today (critical)

`apps/web/src/View.tsx:69`: `{details && panels && source !== "fixture" && ...<LivePanels .../>}`. And
`App.tsx:125`: `details={details && !landing}` and `panels={source === "fixture" ? undefined : shownPanels}`.
So on the landing page (`source === "fixture"`, no `?run`) **`LivePanels`, and therefore `SkillList`, are never
rendered**. The Example snapshot is currently just: status label, the "Run: ... tick ... coverage" line, and
`<FlightMap snap={preview ?? fixture} panels={undefined}>`.

Additionally `App.tsx:42-51` consumes the demo stream only to capture the 150th `world_snapshot`
(`setPreview(r); stop()`); every other event (learning_event, metric_sample, peer_envelope) is discarded. No
reducer runs on the landing path, so even with a metric emitted by `demo.ts`, nothing would reach `Panels`.

---

## 8. System B (swarm) and system C (mission), and how the three relate

### 8.1 System B: `packages/swarm/archipelago_swarm` (standalone)

Source of truth: `docs/LEARNING_BACKEND_HANDOFF.md` (sections 13-22, 27-30) and `packages/swarm/archipelago_swarm/skills.py`.
Verified by reading only; I did not run `scripts/swarm_experiment.py`.

* A **skill is a frozen policy artifact**: weights `w1,b1,w2,b2` (param-map-v1, float32) + manifest, immutable,
  `content_hash` = sha256(manifest + weights), 4-byte length-prefixed JSON manifest + npz, max 1 MiB.
  `skill_id` = `terrain-nav-v<ver>@<node>`; `skill_type` is always `"terrain-nav"` (`SKILL_TYPE`, line 31);
  `version` is a string ("1", "1.1", "1.1.1").
* Proficiency is **one success rate**: `evaluate_params()` (skills.py:224-248) returns
  `{success_rate, mean_return, mean_steps, episodes, max_steps}` from greedy rollouts on the node's own held-out
  (start, goal) set. `Skill.confidence = round(evaluation["success_rate"], 3)`. There are no per-capability
  proficiencies and no explore/avoid/acquire/energy.
* Qualification (`node.py _skills_phase`): first skill needs success >= `max(0.5, baseline+0.3)`; later >=
  `max(0.5, best held + 0.1)`.
* Provenance: `SELF_LEARNED | PEER_RECEIVED | LOCALLY_DERIVED` (`skills.py:30`); `RegistryEntry{skill, local_state,
  source_peer, installed_step, local_eval}`; `SkillRegistry.advertisement()` and `counts()`.
* Transfer: `SKILL_ADVERT -> SKILL_REQUEST -> SKILL_CHUNK* -> SKILL_ACK` over an RF-gated `Network`; chunks only on
  UP links, bandwidth-budgeted; adoption only if the received policy beats the receiver's own on the receiver's own
  eval set by `act_margin` 0.1. Failure causes: `link_not_up`, `ack_timeout`, `no_data_received`, `validation: ...`.
* Observable output (all offline files, no HTTP): `events.jsonl` (types listed in handoff section 22, e.g.
  `SKILL_CREATED`, `SKILL_ACTIVATED`, `SKILL_DERIVED`, `SKILL_ADVERTISED`, `SKILL_REQUESTED`,
  `SKILL_TRANSFER_STARTED/COMPLETED/FAILED`, `SKILL_INSTALLED`, `RF_LINK_UP/DEGRADED/DOWN`), `decisions`,
  `policy_updates`, `skills/*.skill`, and `Swarm.metrics()` -> `metrics.json` with
  `skills[]: {skill_id, version, origin_node, provenance, parent, derived_from_node, evaluation, content_hash,
  current_holders[{node, local_state, source_peer, active}]}` and per-node `self_learned_skills / received_skills /
  derived_skills / active_skill_id / success_rate`. `Store.get_skill_lineage(skill_id)` gives ancestors + holders.
* **No snapshot/endpoint/contract**: it does not produce `world_snapshot`, `metric_sample`, `learning_event` or
  any canonical `Event`. Its world is a 24x24 grid, 100 m cells (handoff section 27), not the 400x500 km mission
  world, and its tick loop is in-process synchronous.
* Claims the doc itself refutes (section 30): the web demo's "capability" lineage is scripted from the *old*
  parameter-exchange stack, not from this backend.

### 8.2 System C: `packages/mission/archipelago_mission` (standalone)

Source: `packages/mission/archipelago_mission/sim.py` (`Skill` lines 68-97, `_exchange_and_links` from 611, `_skill_lifecycle` from 667),
`serve.py`, `FRONTEND_INTEGRATION.md` (sections 7, 8, 15). Live server `python -m archipelago_mission.serve`
(`127.0.0.1:8765`): `GET /api/mission/run?seed=N[&skills=0]` (full replay JSON) and `/api/mission/stream` (SSE).
Offline fallback `apps/web/public/mission/seed-1002.json`.

Exactly **one** skill exists: `adaptive_search_spacing` (`SKILL`, sim.py:44), `behaviorType: SEARCH_REGION_SELECTION`,
`metadata.spacing_m = 80000`. It is learned when a UAV re-searches cells peers already covered (`redundancy_hits >=
learn_threshold`), transferred peer-to-peer over RF links paced by `bandwidthFactor` (60 s of full bandwidth),
then validated and adopted by a fixed rule (`utility >= 0.5 and confidence >= 0.5`).

`Skill.to_dict()` (sim.py:86), camelCase, exactly:

```json
{"id":"adaptive_search_spacing_v1","name":"adaptive_search_spacing","version":1,"sourceNodeId":"UAV-02",
 "createdAt":1590.0,"receivedAt":2010.0,"receivedFrom":"UAV-05","confidence":0.8,"utilityScore":1.0,
 "behaviorType":"SEARCH_REGION_SELECTION","status":"ADOPTED",
 "metadata":{"spacing_m":80000.0,"excludes_peer_covered_cells":true,"excludes_peer_claimed_cells":true,
             "trigger":"11 redundant search selections"}}
```

(copied from `FRONTEND_INTEGRATION.md` line 382; `status` in `LOCAL|RECEIVED|VALIDATING|ADOPTED|REJECTED`,
`receivedFrom` null for the creator). It rides inside each frame's `uavs[].skills[]` plus `uavs[].activeSkill`
(skill id or null; non-null only for LOCAL/ADOPTED). Events (`events[]`, flag `demo`): `SKILL_LEARNED`,
`SKILL_TRANSFERRED` (with `rfQuality`, `bandwidthFactor`), `SKILL_RECEIVED` (demo=false), `SKILL_ADOPTED`,
`SKILL_REJECTED`, `SKILL_USED`; stats `skillsLearned/skillTransfers/skillAdoptions/skillRejections/finalSkillHolders`.
Example event: `{"id":"E-0007","type":"SKILL_LEARNED","timestamp":1590.0,"demo":true,"nodeId":"UAV-02","skillId":"adaptive_search_spacing_v1","version":1,"utilityScore":1.0,"reason":"Re-searched 11 cells ..."}`.

System C is **not a learned model**: the skill is a hard-coded behaviour switch that the sim creates by rule. It
**is** the only system with a meaningful end-to-end narrative (skills on: seed 1002 succeeds at 8520 s; skills
off: fails at 28800 s; `FRONTEND_INTEGRATION.md` lines 326-335), and it uses its own world (400x500 km, 6 UAVs,
30 s ticks) and its own server, not the coordinator/API.

### 8.3 Comparison

| Aspect | A pipeline | B swarm | C mission |
|---|---|---|---|
| What a "skill" is | 4 named measured proficiencies of a node's DQN | immutable policy artifact (weights + manifest) | one hard-coded behaviour with `status` |
| Proficiency | 4 floats 0..1 per node | success_rate (single) | `confidence`, `utilityScore` (set by rule) |
| Learned by | real DQN training in `noderuntime` | real DQN training in `swarm` | rule (redundancy counter), no learning |
| Transfer | whole-policy peer offer (`peer.offer`), gated by score and per-skill gain | skill artifact over RF-gated chunk protocol | skill copy over RF graph, bandwidth-paced |
| Provenance | `source` node per skill, DAG lineage (`policy_id`, `parent_ids`) | `origin_type`, `parent_skill_id`, `source_peer`, lineage query | `sourceNodeId`, `receivedFrom` |
| Wire format | canonical `Event` records (`metric_sample`, `learning_event`) | own JSONL events, none canonical | own frame JSON (camelCase) |
| Transport to UI | coordinator -> API stream / events / `/skills` | none | own HTTP/SSE server (:8765), JSON file |
| World | `GridWorld` (packages/sim) | `NavWorld` 24x24 | 400x500 km mission world |
| Terrain/RF aware | no (all-pairs minus faults in the coordinator) | yes (own RF model) | yes (own RF engine) |
| Consumed by web | yes (`live.ts`) | no | no |

### 8.4 Which one the Example snapshot should be driven by

**System A**, in its wire form (`metric_sample` `skill.*`/`skill_version.*` + `learning_event.skill/skill_gain`).
Reasons: it is the only one that already has canonical contract records, a web reducer, a component and an
endpoint, and the Example snapshot is a `world_snapshot` + canonical-event frame produced by `demo.ts`. B and C
have no path into that frame without a bridge (below). Take the *vocabulary* and *visuals* from C for the story
(a skill spreading hop by hop over RF links with a rfQuality/bandwidth label) and the *provenance concepts* from B
(origin vs source peer, lineage), but emit them through A's records.

### 8.5 Unification work remaining (not done anywhere)

1. **Bridge C or B into A's records (backend).** Either (a) have the mission sim emit `metric_sample`
   `skill.<name>` / `skill_version.<name>` and `learning_event{skill,skill_gain}` into the canonical event stream
   (it currently emits only its own camelCase frames), or (b) run the pipeline on the mission world so A's four
   proficiencies are measured there. Neither exists. `world_skills()` reads `GridWorld` counters
   (`wall_collisions, agent_collisions, agent_ticks, visited, found_targets, battery`); the mission sim does not
   have these.
2. **Add the missing contract.** No pydantic/JSON-schema/TS type for the skill metrics or `/skills` response; add
   one if the frontend wants typed access. The metric naming convention (`skill.<n>`, `skill_version.<n>`,
   `source:<node>` unit) is undocumented in `docs/` (**UNVERIFIED**: I did not search `docs/` for it).
3. **Web reducer does not read `learning_event.skill/skill_gain`.** Add to `Offer` or a new `SkillAdoption` list.
4. **Swarm skills (B) are unreachable from the UI**; to show "skill artifact: hash, version 1.1, derived from X,
   holders" a producer must convert `Swarm.metrics()` / `events.jsonl` to canonical records (no `Event` subclass
   exists for artifact lifecycle; new kinds need the contract generator).
5. **Single id space.** A uses node ids `node-01`; C uses `UAV-01`; B uses `node-0`. The UI keys everything by
   `source_node_id`, so pick one convention for the demo frame (the demo uses `node-01..node-04`).
6. `SKILL_SPEC` and `skill_margin` are not exposed (config/contract).

---

## 9. Backend field -> UI element in the Example snapshot

Present state: none of the skill data is shown in the Example snapshot (section 7.4). The table is the target
mapping for the finished frame. "Existing" means the component already renders it; the frontend must make it
reachable on the landing page.

| Backend field | Source record | UI element (target in Example snapshot) | Existing component |
|---|---|---|---|
| `metric_sample.metric="skill.<name>"`, `value` 0..1 | per node, per window | Per-node skill bar + percent label in the skills table / per-drone card; one bar per `explore, avoid, acquire, energy` | `SkillList.tsx` `<progress>` + `%`, from `Panels.skills[node][name].proficiency` |
| `metric_sample.metric="skill_version.<name>"`, `value` | same | "v2" badge | `SkillList.tsx` Version column |
| `metric_sample.unit="source:<node>"` | same | "Learned from": own training vs `<node>`; use to draw an arrow sender -> receiver on the map / lineage | `SkillList.tsx` last column |
| `source_node_id` of the sample | | the drone/row the skills belong to; select a drone in `FlightMap` to show its four skills in the selected-drone card (`FlightMap.tsx:370` `card = panels?.nodes[selected]`; skills are not in `NodeCard` yet) | **not wired** |
| `learning_event.transfer="accepted"` + `skill` + `skill_gain` | peer decision | Toast/feed line "node-01 adopted `explore` +25% from node-02"; highlight of the `source` cell in the table | **not wired**: reducer ignores `skill`/`skill_gain` (section 7.1) |
| `learning_event.transfer="rejected"`, `reason` | | "Rejected: candidate not better than current policy" / "no skill improved" in the offers feed | exists as a string in the Offers table (`Panels.tsx:74`), not skill-aware |
| `learning_event.flagged_peer` | | flagged sender marker | `Lineage.tsx` / `Offer` (existing, not skill-specific) |
| `adoptions[]` of `GET /skills` | API | optional list "who adopted which skill, gain" | **no client**; derive from events instead |
| `world_snapshot.poses[node]`, `.topology.links` | snapshot | where the skill-carrying drones are and which pairs can exchange | existing `FlightMap` |
| `world_snapshot.mission.objectives[].progress` | snapshot | what the skills are *for* (target found fraction / coverage) | `MissionHUD.tsx` (exists; demo does not emit `mission`) |

Skill-to-visual semantics for a frontend dev (no new backend field needed): `explore` is the same quantity as the
snapshot's `coverage`, but measured on the validator's private `GridWorld`, not on the live world, so the two
numbers will not match and must not be bound to each other.

---

## 10. `demo.ts` must additionally emit (so the frozen frame contains skills)

Facts about the current demo (`apps/web/src/demo.ts`, 60 lines): `startDemo(dispatch, intervalMs, ctl?)` with `ids =
["node-01".."node-04"]`, one `world_snapshot` per interval (`sim_tick = tick`), and, only when `!ctl && tick % 6 ===
0`, a `peer_envelope` + `learning_event` (accepted 2 of 3, `reason: "output outside safety envelope"` on rejects). It
emits **no `metric_sample` at all**: no skills, no coverage metric, no train curves. It emits no `mission`. The
landing page uses `startDemo(cb, 1)` with no `ctl` and freezes the 150th `world_snapshot` (tick 150; events seen
before it: 25 peer exchanges at ticks 6, 12, ..., 150).

To get skills into the frozen frame, `demo.ts` must emit, before the 150th snapshot, using the existing `send()`
helper (it already adds `run_id`, `sequence`, `schema_version`, `emitted_at_utc`, `event_id`):

1. For every node, at least one measurement, then a refresh every exchange (e.g. every 6 ticks, aligned with the
   existing learning events), as `metric_sample` records with `phase: "eval"`, `sim_tick` = current tick,
   `source_node_id` = node id:
   * `skill.explore`, `skill.avoid`, `skill.acquire`, `skill.energy`: `value` in 0..1, `unit: "score"`.
   * `skill_version.explore|avoid|acquire|energy`: integer `value` >= 1, `unit: "source:<node>"`.
   Emit the skill sample before its `skill_version` sample (the reducer is order-tolerant but a lone `skill.*`
   renders `v0`).
2. On each `accepted` demo `learning_event` add `skill: "<one of the four>"` and `skill_gain: <positive float>`,
   and make the *receiver's* subsequent `skill.<skill>` value rise by exactly that gain and its
   `skill_version.<skill>` unit become `source:<sender>` with `version + 1` (this is what the real node does,
   `peer.py:329`). On `rejected` events either omit them or set `skill_gain <= 0` with `reason: "no skill improved"`
   to match the real gate; never put them on a rejected event with a positive gain.
3. A deterministic function of (node, skill, tick) for proficiencies, monotone non-decreasing per node except for
   adoption jumps, so the frame at tick 150 looks like a mid-run swarm: e.g. node-01 `explore` 0.5 / v2 /
   `source:node-02`, others at different values. Values must be finite and in [0,1].
4. Keep the record `sequence` strictly increasing across all kinds (the reducer drops `sequence <= lastSequence`);
   `send()` already does this.

Emitting is not enough; the **landing path must consume it** (this is UI work, listed here because it is a
precondition):

* `App.tsx:42-51` must keep every record it receives (not just snapshots) and, when the 150th snapshot arrives,
  fold the records through `panelsReducer` (or `panelsAtFrame`) and keep the resulting `Panels` for the preview.
* `App.tsx:125` passes `panels={source === "fixture" ? undefined : shownPanels}` and `details={details && !landing}`;
  `View.tsx:69` requires `source !== "fixture"` for `LivePanels`. The frontend must either relax those conditions
  for the Example snapshot or render `SkillList` (or an embedded variant) from a dedicated prop.
* If the 150th-snapshot constant changes, the skill history before it changes with it; the freeze is by snapshot
  count (`n === 150`), not by tick.

---

## 11. Not wired / gaps (summary)

* Example snapshot shows no skills today (section 7.4); `demo.ts` emits no skill data (section 10).
* Web reducer ignores `learning_event.skill` and `skill_gain`; `Offer` and `NodeCard` have no skill fields.
* No history: `Skills` keeps only the latest proficiency; `GET /skills` also only the latest. Any sparkline or
  "improved over time" visual needs the frontend to accumulate samples or a new endpoint.
* `GET /v1/runs/{id}/skills` has no contract type, and the web client has no function for it.
* No fleet-level skill aggregate; no "skill spreads across the swarm" series. Compute client-side if wanted.
* `skill_margin` is never passed by the node (always 0.0); `SKILL_SPEC` is never transmitted.
* The skill `source` is a naming convention inside `unit`; a pre-feature checkpoint or run has no skill data and the
  UI must tolerate `skills = {}` (it does: "No skills measured yet.").
* Systems B and C are standalone; no bridge from either into canonical events. C has a real JSON shape and
  narrative but is a rule-based sim, not learning. B is real learning but offline-only and 24x24 grid.
* Checkpoint line numbers in section 5 (`node.py` ~1181-1230, ~1291) are approximate (from partial reads);
  restore and save of `"skills"` themselves are verified (`node.py:1181`, `1221`).
* I did not run any code or tests; the example JSON in sections 2.2 and 2.3 is built from the code path and the
  test fixtures (values from `tests/api/test_skills_endpoint.py`), not captured from a live run.


---

# 20. Missions and the dynamic map pipeline

Audience: the frontend implementer of the landing page "Example snapshot" (`apps/web/src/App.tsx:40-50,122-125`). Paths are relative to the repo root, on branch `handoff/skills-missions-pipeline`. "Verified" means read in code or in a test; nothing here was executed (suites hang on Windows). Items I could not verify are marked `UNVERIFIED`.

There are TWO mission engines. Do not mix them up.

| | Grid mission (section 1-7) | Mission engine "packages/mission" (section 8) |
|---|---|---|
| Code | `packages/sim/archipelago_sim/{mission,env,flight}.py`, adapter `packages/adapters/sim2d/archipelago_sim2d/adapter.py` | `packages/mission/archipelago_mission/{sim,rf,serve}.py` |
| Consumer | coordinator -> API -> `/v1/runs/{id}/stream` -> `live.ts` -> `View`/`FlightMap`/`MissionHUD` | standalone SSE server on :8765 (`/api/mission/*`) |
| World | 80x45 cells of 625 m = 50 x 28 km (compose default), polygons + terrain raster | 400 x 500 km, 40x50 terrain cells of 10 km, 6 UAVs, 6 POIs |
| Learning | real peer DQN nodes (separate section) | none; rule-based agents + one scripted-behaviour "skill" |
| In this branch's web app | wired (`live.ts`, `MissionHUD.tsx`) | NOT wired here; UI exists only on `main` (section 8.4) |

---------------------------------------------------------------------------------------------------

## 1. Map seed: `derive_map_seed` and per-episode maps

`packages/sim/archipelago_sim/mission.py:28-33`

```python
def derive_map_seed(run_seed: int, episode: int) -> int:
    h = hashlib.sha256(f"archipelago-map:{int(run_seed)}:{int(episode)}".encode()).digest()
    return int.from_bytes(h[:4], "big") & 0x7FFFFFFF      # 31 bit, 0..2147483647
```

Chain from the UI to the map (all verified):

1. UI `startRun(base, mapSeed, f, mission?)` (`apps/web/src/client.ts:21-26`) POSTs `{...run_config, run_id, map_offset: mapSeed, mission?}` with header `Idempotency-Key: <run_id>`.
2. API `LiveBridge.map_offset(body)` (`services/api/src/archipelago_api/live.py:173-178`) accepts an int `0..1_000_000` else `422 "map_offset must be an integer in 0..1000000"`. `mission(body)` (`live.py:181-186`) requires a JSON object else `422`. Both are stripped from the RunConfig (`live.py:193-194`) and forwarded (`live.py:245-246`) only when truthy. Both are part of the idempotency fingerprint (`live.py:230-233`). Route: `services/api/src/archipelago_api/app.py:200-217` (`POST /v1/runs`).
3. Coordinator `CreateRun` (`services/coordinator/archipelago_coordinator/models.py:134-140`): `map_offset: int 0..1_000_000`, `mission: MissionPlan | None`. `service.py:209-214` adds `map_offset` to every plan episode `seed` and replaces `plan.mission` with the request's.
4. Per episode the runner builds a derived RunConfig with `seeds.env = ep.seed` and `run_id = "<run_id>-e<index>"` (`services/coordinator/archipelago_coordinator/runner.py:489-499`), then `adapter.reset(cfg, episode=ep.index)`.
5. Adapter (`adapter.py:73-104`): `self.map_seed = derive_map_seed(config.seeds["env"], episode)`; if the world has a terrain, `world.terrain_seed = map_seed` (so terrain is regenerated per episode); `world.reset(seed=map_seed, starts=...)`.

Everything random derives from `map_seed`: obstacles (`env.py:109`, `_gen_obstacles`), free-cell shuffle and drone/target placement (`env.py:121-128`), the dynamics schedule (`env.py:162-165`, `random.Random(f"{map_seed}:appear:{i}")`, `:move:{t}`, `:shift:{t}`), terrain (`terrain_seed`).

Consequences the frontend must know:

| Fact | Detail |
|---|---|
| Episode count / seeds | come from the server plan file, NOT from the UI. Demo plan `infra/demo/plans/demo.json`: 2 train (seed 1000,1001), validation 2000, 2 train (1002,1003), validation 2001, 2 train (1004,1005), validation 2002, 3 test (3000-3002) = 12 episodes. `map_offset` adds to all. |
| Global tick | snapshot `sim_tick = episode * max_ticks + episode_tick` (`adapter.py:57,93`, `runner.py:301-303`). Demo `max_ticks` = 900 (`apps/web/src/live_run_config.json:57-59`, `infra/demo/run_demo.py:49`). |
| Episode boundary signal | none explicit in `WorldSnapshot`. Detect it by `mission.map_seed` changing, or by `floor(sim_tick / max_ticks)`. `live.ts:109` uses `target_found.value === 1` as "new episode" for the finds list. |
| Terrain collisions | `Terrain.generate` uses `seed & 0xFFFF` (`packages/sim/archipelago_sim/terrain.py:87`), so two map seeds equal mod 65536 give the same terrain. Obstacles/targets still differ. |
| `MissionStatus.map_seed` | the 31-bit derived value, not the user's number. The HUD shows this derived number (`MissionHUD.tsx:26`), so it will not equal the "Map seed" the user typed. |

---------------------------------------------------------------------------------------------------

## 2. MissionSpec / Objective / Dynamics (source of truth: `packages/sim/archipelago_sim/mission.py`)

The coordinator re-declares the same shape as pydantic `MissionPlan` / `MissionObjective` / `MissionDynamics` (`services/coordinator/archipelago_coordinator/models.py:70-96`, `extra="forbid"`) because the coordinator image does not ship the sim. The sim re-validates cross-field rules when the world is built (`env.py:80-84`). A bad mission therefore fails either at `POST /v1/runs` (422, pydantic) or when the first episode builds the world (UNVERIFIED: how a late `ValueError` surfaces to the run status).

### MissionSpec (`mission.py:53-114`)

| Field | Type | Default | Constraint (pydantic / sim) |
|---|---|---|---|
| `id` | str | `"mission-1"` | `^[A-Za-z0-9_.:-]{1,64}$` |
| `type` | str | `"search_rescue"` | `"search_rescue"` or `"coverage"` (no "relocate" yet, `mission.py:19-22`) |
| `n_targets` | int | `5` | `0..200` (`MAX_TARGETS`); targets present at tick 0 |
| `objectives` | list[Objective] | `[]` | empty means the type default (below); ids unique |
| `time_budget_ticks` | int or null | null | `>= 1`; null means episode `max_ticks`. Effective budget = `min(max_ticks, time_budget_ticks)` (`env.py:147-150`) |
| `energy_budget` | float or null | null | `0 < x <= 1`; max fraction of fleet battery that may be spent |
| `dynamics` | Dynamics | all off | below |

Cross-field rules (`mission.py:80-97`): `search_rescue` needs `n_targets + targets_appear >= 1`. `find_targets` objective `target` must be in `1..(n_targets + targets_appear)`. `cover_fraction` `target` in `(0, 1]`. Unknown keys raise `ValueError("invalid mission: ...")` (`from_dict`, `mission.py:99-114`).

Default objective when `objectives` is empty (`mission.py:82-88`):
- `search_rescue`: `{id:"find_targets", kind:"find_targets", target: n_targets + targets_appear}`
- `coverage`: `{id:"cover_fraction", kind:"cover_fraction", target: 0.6}`

### Objective (`mission.py:36-40`)

| Field | Type | Meaning |
|---|---|---|
| `id` | str (same regex) | unique within the mission |
| `kind` | `find_targets` or `cover_fraction` | `find_targets`: `target` = count; `cover_fraction`: `target` = fraction of free cells visited |
| `target` | float `> 0` | see above |

### Dynamics (`mission.py:43-50`; pydantic caps in `models.py:76-84`)

| Field | Type | Default | Range | Effect |
|---|---|---|---|---|
| `targets_move_every` | int | 0 (off) | `0..100000` | every N episode ticks each UNDISCOVERED target steps to a free 4-neighbour |
| `targets_appear` | int | 0 | `0..200` | extra targets added at seeded ticks (not counted in `n_targets`) |
| `appear_window` | [float, float] | `[0.2, 0.7]` | `0 <= a <= b <= 1` | appearance tick = `round(uniform(a,b) * time_budget)`, min 1 |
| `obstacles_shift_every` | int | 0 | `0..100000` | every N ticks ONE obstacle (grid) or ONE terrain feature polygon (flight) moves by one cell |

### Real plan example (`infra/demo/plans/demo.json:36-41`)

```json
"mission": {
  "id": "sar-demo",
  "type": "search_rescue",
  "n_targets": 6,
  "dynamics": {"targets_move_every": 20, "targets_appear": 2, "obstacles_shift_every": 50}
}
```
Resulting default objective: `find_targets`, target 8 (6 + 2). Time budget = 900 (max_ticks). Plan mission is replaced wholesale by a `mission` in the POST body, not merged (`service.py:213-214`).

Safe-defaults test: `tests/sim/test_dynamic_missions.py:179` (no dynamics, default objective). Validation cases: `:174`.

---------------------------------------------------------------------------------------------------

## 3. What the world does each tick (what is observable)

Which world class runs: coordinator compose sets `COORDINATOR_WORLD_KWARGS` with `environment_mode` default `continuous_flight`, `size` 80, `height` 45, `terrain_seed` 1, `terrain_style` `alpine`, `n_targets` 0 (`infra/compose/compose.yml:141`). With a plan `mission`, `n_targets` is overridden by `mission.n_targets` (`env.py:83-84`). So the live demo is `FlightWorld` (`packages/sim/archipelago_sim/flight.py`) with terrain; `legacy_grid` is the 20x20 canvas fallback in `View.tsx`.

Order inside `GridWorld.step` (`env.py:392-484`): `tick += 1` -> `_apply_dynamics()` (before anyone senses) -> move/collide -> sense (`_sense`/`_detect`) -> `_update_mission()` -> episode ends if mission result is not `active`.

### 3.1 Dynamics, exactly (`env.py:179-223`)

| Change | When | What happens | Event appended to `world.events` |
|---|---|---|---|
| Targets move | `tick % targets_move_every == 0` | each target NOT yet found by any drone takes one random free 4-neighbour step (not onto a drone, other target, wall, or found target). Found targets never move. | `{"tick":T,"event":"target_moved","from":[x,y],"to":[x,y]}` |
| Targets appear | first tick `>= sp.tick` where a free fallback cell is unoccupied; else retried next tick | new target appended to `world.targets` | `{"tick":T,"event":"target_appeared","at":[x,y]}` |
| Obstacles shift (grid) | `tick % obstacles_shift_every == 0` | one of up to 5 sampled obstacle cells moves to a free neighbour (never onto drone/target/start); count of obstacles preserved | `{"tick":T,"event":"obstacle_shifted","from":[x,y],"to":[x,y]}` |
| Obstacles shift (flight) | same | one whole polygon `shapes[id]` translates by +-1 cell (625 m); refused if it leaves the map or covers a drone/target/start; raster `obstacles` recomputed | `{"tick":T,"event":"obstacle_shifted","shape":"s3","dx":1,"dy":0}` (`flight.py:92-109`) |

These events go ONLY into `adapter.replay[].events` and `ep-NNNN/replay.jsonl` (`adapter.py:113-120,214-234`). `grep` finds no emitter of them to telemetry: they are NOT canonical events, NOT in the WebSocket stream, NOT in `/v1/runs/{id}/events`.

### 3.2 What a frontend client actually sees per tick (public `world_snapshot`)

| Thing | Visible? | Where / how it changes |
|---|---|---|
| Terrain raster `biome`, `elev_m`, `veg_pct` | yes, full map from tick 0 | constant within an episode. Changes ONLY at the next episode (new `terrain_seed = map_seed`). The three raster fields never change per tick. |
| Terrain `observed` | yes | one char per cell `"1"/"0"`; grows monotonically as drones sense (fog of war). Built from the union of every drone's `known` plus cells known to killed drones (`flight.py:226-239`, `adapter.py:143-147`). |
| Obstacle polygons `world.shapes` | only REVEALED ones | a shape is listed iff one of its raster cells is in the discovered set (`flight.py:219-224`). When a feature shifts, the SAME `id` appears with different `points` (and may newly appear/disappear from the list as discovery changes). Cache by `id:points.length` in `FlightMap.tsx:277` would NOT notice a shifted polygon with equal point count: see Gaps. |
| `obstacles` (cell list) | `[]` in flight mode (`adapter.py:184`); discovered cells only in legacy mode | |
| `world.targets_found` | yes: FOUND targets only | `[{x,y,radius}]` in metres, centre of cell, `radius = cell_m/2` (`adapter.py:178-181`). Monotonic (found targets never move or vanish). |
| Unfound targets (the moving/appearing ones) | NO | `world.targets` is hidden state. Only reachable by the admin snapshot `privileged` block (section 5.4). A moving or newly appeared target is invisible to the UI until a drone senses it. |
| Mission progress | yes | `snapshot.mission` (section 4) |
| Poses | yes | metres, `heading_rad`, `speed_mps` in flight mode |
| Coverage | yes | `snapshot.coverage` 0..1 = visited / free cells |

Detection (`env.py:299-341`): with terrain, a target is `found` by a drone iff line of sight is blocked-free then `random(f"{terrain_seed}:{tick}:{drone}:{cell}") < terrain.detect_p(...)` (vegetation + distance). So finds are stochastic-but-seeded.

### 3.3 Completion and failure (`env.py:225-240`)

Evaluated each tick after sensing. `succeeded` when all objectives are done (each objective latches its first-done tick in `_obj_done`). Otherwise `failed` when any of: `tick >= time_budget`; `energy_spent > energy_budget`; no drone alive. Result and `mission_end_tick` latch. The episode terminates (`done`) as soon as the mission result leaves `active` (`env.py:467-469`). Note: a failed/succeeded mission ends the episode early, so later ticks in `max_ticks` do not exist.

`energy_spent` = mean over drones of `1 - battery/battery_scale` (`env.py:242-246`). Demo plan `battery_scale: 4`.

---------------------------------------------------------------------------------------------------

## 4. `mission_status()` -> `MissionStatus` / `ObjectiveStatus` (WorldSnapshot.mission)

Produced by `GridWorld.mission_status()` (`env.py:248-283`), wrapped in `MissionStatus(**s["mission"])` by `adapter._snapshot` (`adapter.py:193`). Contract: `packages/contracts/src/archipelago_contracts/models.py:152-187`; generated TS: `packages/contracts/generated/types.ts:272` (`MissionStatus`), JSON schema `packages/contracts/schemas/world_snapshot.schema.json`. All models are `extra="forbid"` (`models.py:34-35`): a frame with an unknown field is rejected by contract validation.

### MissionStatus

| Field | JSON type | Unit / range | Emitted | Notes |
|---|---|---|---|---|
| `id` | string | mission id | every snapshot | = `MissionSpec.id` |
| `type` | string | `search_rescue` / `coverage` | every | |
| `map_seed` | int | `0..2^31-1` | every | the derived per-episode seed (section 1) |
| `status` | `"active"` / `"succeeded"` / `"failed"` | | every | latches; once non-active it stays so until the next episode |
| `objectives` | ObjectiveStatus[] | 1+ | every | order = spec order |
| `time_budget_ticks` | int >= 1 | episode ticks (1 tick = 7.5 s, `replay.ts:7`) | every | `min(max_ticks, spec budget)` |
| `energy_budget` | float or null | `(0,1]` | every | null when unset |
| `energy_spent` | float | `0..1` | every | rounded to 4 dp; clamped `>= 0` |
| `completed_tick` | int or null | EPISODE tick (not global) | null while active/failed | tick the last objective completed |
| `dynamics` | string[] | subset of `targets_move`, `targets_appear`, `obstacles_shift` (order fixed) | every | which dynamics have a non-zero setting. Default `[]`. |

### ObjectiveStatus

| Field | Type | Notes |
|---|---|---|
| `id` | string | |
| `kind` | `find_targets` / `cover_fraction` | |
| `target` | float `> 0` | count (find) or fraction (cover). Serialised as a float: `8.0` |
| `progress` | float `0..1` | `min(1, value/target)`, 4 dp. value = `len(found_targets)` or `coverage` |
| `done` | bool | latched |

### When emitted

`mission` is present in EVERY `world_snapshot` of a run that has a mission, `null`/absent otherwise (`tests/coordinator/test_mission_run.py:56-62`). The coordinator emits one snapshot right after each episode reset (tick 0, `runner.py:518`, status `active`) and one after every tick (`runner.py:657`). Terminal status appears in the snapshot of the tick that ended the episode. Deterministic: same `(env seed, episode)` gives the same `map_seed` and trajectory (`test_mission_run.py:38-54`).

### Real example (matches `apps/web/src/mission.test.tsx:27-31` shape; numbers for the demo plan are computed by hand from the code)

```json
{
  "id": "sar-demo", "type": "search_rescue", "map_seed": 123456789, "status": "active",
  "objectives": [
    {"id": "find_targets", "kind": "find_targets", "target": 8.0, "progress": 0.375, "done": false}
  ],
  "time_budget_ticks": 900, "energy_budget": null, "energy_spent": 0.0481,
  "completed_tick": null,
  "dynamics": ["targets_move", "targets_appear", "obstacles_shift"]
}
```
Succeeded variant: `"status":"succeeded", "completed_tick": 412`, objective `"progress":1.0,"done":true`.

---------------------------------------------------------------------------------------------------

## 5. Coordinator emission and API surfaces

### 5.1 Metrics (all `kind:"metric_sample"`, fields `metric, value, unit, phase` + base Event fields; `models.py:227-232`)

Emitted in `Runner._record_tick` (`runner.py:621-657`) and `_finish_episode`. `phase` = episode mode (`train`/`eval`). `sim_tick` is the GLOBAL tick of the tick that was just executed (`t+1`).

| `metric` | `value` | `unit` | `source_node_id` | When |
|---|---|---|---|---|
| `map_seed` | the 31-bit map seed as a float | `seed` | null | once per episode, in the record of the first tick (global tick `episode*max_ticks + 1`) (`runner.py:644-645`) |
| `targets_total` | `len(world.targets)` (grows when targets appear: 6 -> 8 in the demo plan) | `count` | null | every tick |
| `target_found` | cumulative finds this episode (1 = first find of a new episode) | `count` | the discovering node (lowest id on ties, `mission.py:120-127`) | once per newly found target |
| `coverage` | coverage 0..1 | `fraction` | null | every tick and at episode end |
| `mission_complete` | `completed_tick` (episode tick) | `ticks` | null | once per episode when status becomes `succeeded` (`runner.py:646-656`) |
| `mission_failed` | `t+1` (episode tick) | `ticks` | null | once per episode when status becomes `failed` |
| `episode_return` | per-node return | `reward` | node | episode end |

Example record (base fields from `spool.py:158-166`; values illustrative):

```json
{"schema_version":"0.1.0","kind":"metric_sample","event_id":"run-x-ab12cd-481","run_id":"run-x","source_node_id":"node-02","sim_tick":912,"emitted_at_utc":"2026-10-11T12:00:00Z","sequence":481,"metric":"target_found","value":2.0,"unit":"count","phase":"train"}
```

`MissionHUD` / `live.ts` consume `targets_total` and `target_found` (`live.ts:108-110`); they ignore `map_seed`, `mission_complete`, `mission_failed` (map seed comes from `snapshot.mission.map_seed`). `MetricSample.metric` is `Id` pattern, so any new metric name must match `^[A-Za-z0-9_.:-]+$`.

### 5.2 Episode summaries (`runner.py:696-740`)

`Runner.summaries[]` is exposed in run status (`status_dict`, `episodes_done`). Per episode:

```json
{"episode":3,"kind":"train","seed":1002,"map_seed":987654321,
 "mission":{ ...MissionStatus dict at episode end... },
 "ticks":412,"final_state_hash":"<sha256>","coverage":0.61,
 "returns":{"node-01":3.2},"replay_manifest":"…/ep-0003/manifest.json",
 "episode_end_sent":["node-01"],"episode_end_failed":[],"window_ids":{}}
```
`mission` is the same dict as section 4 (so `episodes_done[i].mission.status` / `.completed_tick` give per-episode success and time-to-complete). `mission` is `null` for runs without one. Source of per-episode comparison across maps. UI use today: none (`PastRuns` does not read it, UNVERIFIED).

### 5.3 Replay manifest (`adapter.py:219-233`)

`manifest.json` contains `seed`, `episode`, `map_seed`, `world_kwargs`, `run_config`, `final_state_hash`. `replay.jsonl` records `{"tick","actions","events","state_hash"}` with the dynamics events of section 3.1. Replaying with the same `(config, episode)` reproduces the hash (`tests/sim/test_dynamic_missions.py:89`).

### 5.4 API / transport surface the frontend can use

| Endpoint | Carries mission data? |
|---|---|
| `POST /v1/runs` | request: `mission`, `map_offset` (section 1). Response is `RunView` `{run_id,status,revision,completion_reason,tick}` (`client.ts:7`), no mission info. |
| `GET /v1/runs/{id}/stream` (WebSocket) | canonical records incl. `world_snapshot.mission` and the metrics of 5.1 |
| `GET /v1/runs/{id}/events?after_sequence&limit` | same records as history (`client.ts:44-55`, `loadReplayRecords`) -> replay mode `panelsAtFrame` |
| coordinator `GET /v1/runs/{id}/snapshot` (admin token) | privileged: full snapshot + `"privileged": {"targets":[[x,y],...],"found":[[x,y],...],"battery":{...}}` in GRID CELLS (`adapter.py:205-212`, `runner.py:333-352`). The API does NOT expose it on any route (`live.py:93`). |
| status/summary view | `episodes_done` with mission per episode (5.2) |

Per-run status shape beyond `RunView` (`episode_kind`, `episodes_done`) is in `Runner.status_dict` (`runner.py:175-209`); not re-documented here.

---------------------------------------------------------------------------------------------------

## 6. Frontend code that already consumes the grid mission (this branch)

| File | What it does |
|---|---|
| `apps/web/src/client.ts:21-26` | `startRun(base, mapSeed, f, mission?)` -> `map_offset: mapSeed` plus optional `mission` object. App's form passes none (`App.tsx:86`), so the server plan's mission is used. |
| `apps/web/src/live.ts:33,47-48,62-63,90,108-110` | `Mission {total, finds[], adoptTick}` from metrics; `missionStatus: MissionStatus \| null` copied from the newest `world_snapshot.mission` (kept if a later snapshot lacks it: `r.mission ?? s.missionStatus`). |
| `apps/web/src/MissionHUD.tsx` | Renders only when `p.mission.total !== null` or `p.missionStatus` is set. Contents below. |
| `apps/web/src/Panels.tsx:50` | mounts `<MissionHUD p={p}/>` inside `LivePanels`. |
| `apps/web/src/mission.test.tsx` | tests with the snapshot shape of section 4. |

MissionHUD elements (strings are exact, tests depend on them):

| Element | Source field |
|---|---|
| `<h2>Mission: {search & rescue / area coverage}</h2>` | `missionStatus.type` via `LABEL` |
| `<div aria-label="Active mission" data-status>` | `missionStatus.status` |
| `<strong>{id}</strong>`, `<span data-testid="mission-status">`, `<span data-testid="map-seed">` | `id`, `status`, `map_seed` |
| ` · completed in mm:ss` (when succeeded) else ` · time budget mm:ss` | `completed_tick * 7.5` / `time_budget_ticks * 7.5` |
| ` · energy X% of Y% budget` (only if `energy_budget != null`) | `energy_spent`, `energy_budget` |
| ` · dynamic: targets move, targets appear, obstacles shift` | `dynamics[]` via `DYNAMICS` |
| `<ul aria-label="Mission objectives">` `[done]/[open] Find targets (8): 38%` | `objectives[].done/kind/target/progress` |
| `N / M objectives complete` | count of `done` |
| `<progress aria-label="Targets found">` and `F / T Targets Found` | `mission.finds.length` / `mission.total` (metrics, NOT `objectives`) |
| `Mission time: mm:ss · coverage: x%` | `p.tick * 7.5`, `p.coverage` |

Known inconsistencies in this UI: `p.tick` is the GLOBAL `sim_tick` while `time_budget_ticks`/`completed_tick` are EPISODE ticks, so "Mission time" is wrong after episode 0; `targets_total` (grows 6 -> 8) and the objective target (8 from tick 0) disagree on the denominator until all targets appeared; `TICK_S = 7.5` is hardcoded (`replay.ts:7`).

IMPORTANT for the landing page: in `App.tsx:125` the landing passes `panels={source === "fixture" ? undefined : shownPanels}` and `details={details && !landing}` (false), and `View.tsx:69` shows `LivePanels` only when `source !== "fixture"`. So `MissionHUD` is NOT rendered in the Example snapshot today. The landing frame renders only the status line, `Run: ... tick: ... coverage: ...` line, and `<FlightMap snap=...>` (`View.tsx:51-60`). Showing mission status there needs a HUD driven by `snap.mission` (the snapshot itself), not by `Panels`.

---------------------------------------------------------------------------------------------------

## 7. What is NOT wired / gaps (grid mission)

1. No UI to choose a mission or dynamics: `startRun` supports `mission` but `App.tsx:86` never passes it; there is no form field.
2. Moving / appearing / unfound targets are invisible: no public field carries them (`WorldGeometry.targets_found` only). `target_moved`, `target_appeared`, `obstacle_shifted` are not telemetry events. To animate targets in the UI the contract must change (e.g. new `WorldGeometry` field for active targets, or an event kind). Contract models are `extra="forbid"`, so adding a field requires `packages/contracts` changes + regenerated `generated/types.ts` + schemas.
3. `FlightMap` shape cache key `sh.id + ":" + sh.points.length` (`FlightMap.tsx:277`) hides a shifted polygon whose point count is unchanged (bbox and elevation samples cached stale). Fix on the UI side (include a points hash).
4. No `episode` / episode count field in `MissionStatus` or `WorldSnapshot`; derive from `map_seed` change or `sim_tick / max_ticks`.
5. `completed_tick` is episode-relative, `sim_tick` global (see section 6).
6. `coverage` mission objective `target` default 0.6 appears only for `type:"coverage"`; the demo plan uses `search_rescue` so a coverage example is only from tests (`tests/sim/test_dynamic_missions.py:139`).
7. Only goals `find_targets` and `cover_fraction` exist; no relocate/goal-zone (`mission.py:19-22`).
8. Terrain 3D (`terrain3d.ts`, `TerrainGL`) draws the static raster; nothing in the grid pipeline moves the raster during an episode, so "terrain changes" during a frozen frame are only fog (`observed`) and shifting polygons.
9. Compose flight world is 50 x 28 km (80x45 cells x 625 m), NOT 400 x 500 km (section 8).
10. How a late `ValueError` from `MissionSpec` (sim-side cross-field rule) surfaces as a run failure: UNVERIFIED.

---------------------------------------------------------------------------------------------------

## 8. The second engine: `packages/mission` (MissionSim, serve.py, FRONTEND_INTEGRATION.md)

Detailed contract: `FRONTEND_INTEGRATION.md` at repo root (846 lines, sections 0-20, TypeScript interfaces in 19.a). Do not duplicate; read it. This section states what matters for the handoff.

### 8.1 What it is

`MissionSim` (`packages/mission/archipelago_mission/sim.py:173`): a deterministic discrete simulation for a seed: 6 UAVs search a 400 x 500 km world (`TILE_M = 100_000`, `TILES_X, TILES_Y = 4, 5`, `sim.py:22-24`), discover and verify 6 POIs under an RF link model (`rf.py`), with 3 scheduled disruptions (communication degradation, navigation degradation, platform failure), one behavioural "skill" (`adaptive_search_spacing`) that spreads over connected links. `dt = 30 s`, `time_limit = 28800 s` (`MissionConfig`, `sim.py:48-65`). Terrain is generated internally: `Terrain.generate(int(W / CELL_M), CELL_M, seed, height=int(H / CELL_M), style="alpine")` = 40 x 50 cells of 10 km (`sim.py:35,178-180`) and is NOT sent to clients (frames carry no terrain; grep of `sim.py` finds it used only for LOS/detection).

### 8.2 Frame JSON (live stream and `/run`) - camelCase, metres

Each frame (`sim.py:797-846`): `{tick, time, mission, uavs[6], pois[6], links[], disruptions[3], eventCount, decisionCount}`.

```json
{"seed":1002,"status":"SUCCESS","elapsedTime":8520.0,"timeLimit":28800.0,"totalPois":6,"requiredPois":6,"discoveredPois":6,"verifiedPois":6,"fleetKnowledgeCoverage":0.972,"knowledgeThreshold":0.8,"operationalNodes":6,"totalNodes":6}
```
(`frame.mission`, copied from `FRONTEND_INTEGRATION.md` section 15; status `RUNNING|SUCCESS|FAILED`.)

| Frame key | Fields (see doc section) |
|---|---|
| `uavs[]` | `id` (`UAV-01`..), `status`, `position{x,y}` m, `heading` rad, `speed`, `altitudeMeters`, `sensorRadius`, `commRadius`, `currentObjective`, `currentAction`, `sensorState`, `communicationState`, `neighbors`, `networkComponent`, `activeSkill`, `skills[]`, `knownPois`, `verifiedPois`, `lastSync` (doc section 2) |
| `pois[]` | `id`, `position`, `trueType` (ground truth: hide until `state=="VERIFIED"`), `state` UNKNOWN/DISCOVERED/VERIFIED, `classification`, `confidence`, `knownBy`, `verifiedBy` (doc section 3) |
| `links[]` | RFLink: `id` "UAV-02~UAV-03", `distanceMeters`, `lineOfSight`, `rfQuality`, `bandwidthFactor`, `state`, `connected`, `debug{...}` (doc section 4) |
| `disruptions[]` | `id`, `type`, `active`, `startTime`, `endTime`, `position{x,y}` or null, `radius` m, `velocity`, `severity`, `nodeId` (doc section 5) |

Result object (`sim.py:889-911`): `{meta{seed,dt,skillsEnabled,world{width,height,tileMeters,tilesX,tilesY,units},searchGrid{nx,ny},uavSpec,rfModel,missionRules,config}, frames[], events[], decisions[], stats}`.

### 8.3 Transport (`packages/mission/archipelago_mission/serve.py`; stdlib HTTP, default `127.0.0.1:8765`, CORS `*`)

Start: `PYTHONPATH="packages/mission;packages/sim" python -m archipelago_mission.serve --port 8765` (Windows `;`).

| Endpoint | Returns |
|---|---|
| `GET /api/mission/health` | `{"ok":true}` |
| `GET /api/mission/run?seed=N[&skills=0]` (`&uavs=1..24` exists on `main` only; `serve.py` here has no `uavs` param) | full result JSON, ~1-2 s, 3 dp floats |
| `GET /api/mission/summary?seed=N[&uavs=]` | `{seed,uavs,on:{mission,stats},off:{mission,stats}}` (on `main` only; not in this branch's `serve.py`) |
| `GET /api/mission/stream?seed=N[&tps=4][&skills=0]` (`&uavs=` on `main` only) | SSE: `event: meta` (once), `event: tick` `{frame,events,decisions}` (new items only), `event: end` `{stats}`. Client must `close()` on `end`. |

`apps/web/public/mission/seed-1002.json` is an offline fallback (same shape as `/run`). Seed 1002 outcome: SUCCESS at 8520 s, 285 frames (verified in the fallback file's last `frame.mission` and frame count).

### 8.4 Where the UI for it lives

NOT in this worktree. On `main` (commit `fe75ecd`, PR #44) only: `apps/web/src/MissionApp.tsx` (setup + aggregate results), `MissionViewer.tsx` (SSE buffer, offline fallback, HUD, inspectors, feed), `MissionMap.tsx` (SVG 2D map, 640 px wide), `missionReplay.ts` (types of doc 19.a, `worldTransform`, loaders), routed by `?mission` or `?seed` in `App.tsx` and a `/api/mission` proxy in `apps/web/vite.config.ts`. `main` has meanwhile removed this branch's `MissionHUD` mission-status block, `live.ts missionStatus` and `startRun(... mission)` (git diff `HEAD main`), so merging both will conflict in `MissionHUD.tsx`, `live.ts`, `client.ts`, `Panels.tsx`, `App.tsx`. Expect to keep this branch's mission status code when merging.

### 8.5 How the two relate (and what feeds the 3D scaled-up world)

| Aspect | Grid mission | packages/mission |
|---|---|---|
| Scale | 50 x 28 km (compose), cells 625 m | 400 x 500 km, cells 10 km terrain, 25 km search cells |
| Transport | coordinator WS + `/events` | SSE (:8765), separate process, no auth |
| Contracts | `WorldSnapshot`/`MissionStatus` (pydantic + generated TS, `extra=forbid`) | ad hoc camelCase JSON, TS types hand-copied in `missionReplay.ts` |
| Terrain to client | yes: `world.terrain` (`TerrainGrid`: size<=256, `biome`, `observed`, `elev_m`, `veg_pct`) | NO terrain in frames |
| Dynamics | targets move/appear, obstacles shift (seeded) | disruptions (comm/nav zones moving, UAV failure) |
| Mission result | `MissionStatus` | `frame.mission.status` RUNNING/SUCCESS/FAILED |
| Learning | real DQN peers | scripted skill |
| Renderer | `FlightMap` canvas + `Terrain3D` WebGL (`terrain3d.ts`, `terrainTexture.ts`) | `MissionMap` SVG, no 3D |

The "finished engine" the Example snapshot should imitate (3D terrain, 400 x 500 km, moving targets, mission status) is the UNION of both and does not exist as one pipeline: the 3D renderer consumes `WorldSnapshot.world.terrain` (grid pipeline), while the 400 x 500 km scale, disruptions and RF links exist only in `packages/mission`.

Unification still missing (decisions, not implemented):
1. `MissionSim` has no adapter to the `SimulatorAdapter` contract or the coordinator; it does not emit `WorldSnapshot`.
2. Its terrain (40x50 cells, 10 km, alpine, seed & 0xFFFF) is never emitted; to feed `Terrain3D` it must be sent as `TerrainGrid` (fits `size<=256`; `veg_pct` and `elev_m` come from the same `Terrain` object `sim.py:178`) or generated client-side from the seed (not possible: Python).
3. `WorldSnapshot.poses` has `x,y,z,heading_rad,speed_mps` but `z` is constrained to 0 (`models.py:38-45`): UAV altitude (`altitudeMeters`, 400-2000 m AGL) has no slot.
4. POIs, links with RF quality, disruptions have no contract equivalent; `topology.links` is only pairs.
5. `FlightMap` assumes `world.cell_m` and a width/height from `WorldGeometry` (works at 400 x 500 km in principle: `width_m=400000, height_m=500000`) but zoom, LOD, trail and sensor-ring constants were tuned for 10-50 km (`FlightMap.tsx:115` `fitZoom`); UNVERIFIED at 400 km.
6. Seed models differ: grid uses `derive_map_seed(run_seed, episode)`; MissionSim uses the raw `seed` for everything (`random.Random(f"{s}:pois")`, etc.) and has no episodes.

---------------------------------------------------------------------------------------------------

## 9. Backend field -> UI element in the Example snapshot

Landing = `App.tsx:40-50` (`startDemo(..., 1)` until the 150th `world_snapshot`, then frozen), rendered by `<View snap={preview} panels={undefined} details={false} source="fixture">` -> `FlightMap` (because `snap.world` is set). Column "Today" = what `demo.ts` emits now (`apps/web/src/demo.ts:53-57`). "Target" = what the finished engine would put there.

| Backend field | Real source | UI element in Example snapshot | Today in demo.ts |
|---|---|---|---|
| `snap.mission.status` / `id` / `type` | `mission_status()` | mission banner (new): `{type label} · {id} · {status}` | absent |
| `snap.mission.map_seed` | `derive_map_seed` | seed chip next to the banner | absent |
| `snap.mission.objectives[]` (`kind,target,progress,done`) | `_update_mission` | objective list + progress bars (`Find targets (8): 38%`) | absent |
| `snap.mission.time_budget_ticks`, `sim_tick` | | countdown/progress; clock = ticks * 7.5 s | `TICK_S` 7.5 only in `replay.ts` |
| `snap.mission.energy_budget/energy_spent` | | optional energy chip | absent |
| `snap.mission.dynamics[]` | | "dynamic: targets move, ..." tags | absent |
| `snap.mission.completed_tick` | | "completed in mm:ss" when succeeded | absent |
| `snap.world.targets_found[]` `{x,y,radius}` | `adapter._snapshot` | orange rings on the map (`FlightMap.tsx:285-288`) | `[]` always (`demo.ts:56`) |
| `snap.world.terrain.biome/elev_m/veg_pct` | `FlightWorld.terrain_grid` | terrain base texture and 3D mesh | synthetic, constant, 40x24 cells |
| `snap.world.terrain.observed` | known-cells union | fog of war overlay | synthetic: cells near flight paths |
| `snap.world.shapes[]` | `revealed_shapes` | obstacle polygons (revealed only) | `[]` always |
| `snap.coverage` | `world.coverage` | coverage % in the status line | `min(1, tick/800)` = 0.1875 at frame 150 |
| `snap.poses` | `poses_m` | aircraft markers, heading, speed | scripted orbits |
| `snap.topology.links` | `_allowed_links` | link lines | two fixed pairs |
| metric `target_found` / `targets_total` | `_record_tick` | optional `F / T Targets Found` bar | absent |
| metric `map_seed` | `_record_tick` | redundant with `snap.mission.map_seed` | absent |
| metric `mission_complete` / `mission_failed` | `_record_tick` | one-shot toast | absent |

### `demo.ts` must additionally emit (so the frozen frame 150 shows mission status, objectives, seed, moving targets)

Constraints: `world_snapshot` records must satisfy `MissionStatus` exactly (no extra keys). Frame 150 is `tick = 150` => `sim_tick: 150`, `t = 1125 s`.

1. `mission` on every `world_snapshot`, e.g. (all ticks deterministic from `tick`):
   ```ts
   mission: { id: "sar-demo", type: "search_rescue", map_seed: 1186539221, status: "active",
     objectives: [{ id: "find_targets", kind: "find_targets", target: 8, progress: found / 8, done: found >= 8 }],
     time_budget_ticks: 900, energy_budget: null, energy_spent: round4(tick * 0.0002),
     completed_tick: null, dynamics: ["targets_move", "targets_appear", "obstacles_shift"] }
   ```
   Pick a fixed `map_seed` (any int `0..2^31-1`; `1186539221` is arbitrary, not a real derived value). Optionally flip to `succeeded` + `completed_tick` at a later tick to show both states (must still be false at tick 150 for an "active" example).
2. `world.targets_found`: grow with time, e.g. a scripted list of `{x,y,radius:125}` (radius = `cell_m/2` = 125 m at `cell_m` 250) revealed when a drone pose comes within `sensor_radius_m` (400 m). Keep centres on cell centres `(i+0.5)*250`. Found targets must not move.
3. `world.shapes`: at least 2-3 polygons `{id:"s1", points:[[x,y],...>=3]}` inside the 10000 x 6000 m world, revealed when a drone gets near; to show "obstacles shift" move one polygon by +-250 m (one cell) every 50 ticks (`obstacles_shift_every`). Change `points` but keep `id`; bump the point-hash caching issue (gap 3, `FlightMap.tsx:277`).
4. Moving targets: the real pipeline cannot show unfound targets (section 3.2). Decision needed before building: either (a) show only found targets (faithful to the backend; "moving" is then visible only as `targets_total` growing 6 -> 8 and `progress` changing), or (b) extend the contract with an explicit field for active/unfound targets (and make the backend emit it). `demo.ts` cannot emit a non-contract field without breaking validation tests; do (b) in `packages/contracts` first.
5. Metrics, only if the landing keeps using panels: `targets_total` (6, growing to 8 around ticks 180-630 = `appear_window` 0.2-0.7 of 900), `target_found` (cumulative count, `source_node_id` = finder), once `map_seed`. Not needed if the HUD reads `snap.mission`.
6. A landing HUD component fed by `snap.mission` (new, since `MissionHUD` takes `Panels`). Reuse labels from `MissionHUD.tsx:5-7` (`LABEL`, `OBJECTIVE`, `DYNAMICS`) and `clock()`.
7. Optional scale-up (per the stated goal of a 400 x 500 km 3D world): `world.width_m/height_m` 400000/500000 with `cell_m` 10000 and terrain 40x50 (limit `size,height <= 256`); then `sensor_radius_m` ~40000, pose speeds ~140 m/s, `TICK_S`-based clock must become 30 s per tick for that engine (section 8: `dt = 30`). UNVERIFIED that `FlightMap`/`Terrain3D` frame and fit that scale.

---------------------------------------------------------------------------------------------------

## 10. Quick reference: test files that pin behaviour

| Behaviour | Test |
|---|---|
| map seed deterministic/distinct, terrain follows map seed | `tests/sim/test_dynamic_missions.py:36,44` |
| dynamics schedule (move/appear/shift ticks) | `tests/sim/test_dynamic_missions.py:57` |
| flight shapes shift consistently with raster | `tests/sim/test_dynamic_missions.py:77` |
| replay hash reproducibility | `tests/sim/test_dynamic_missions.py:89` |
| completion, time-to-complete, budgets | `tests/sim/test_dynamic_missions.py:99,120,139` |
| validation rejects bad specs | `tests/sim/test_dynamic_missions.py:174` |
| per-episode `map_seed` metric + summary | `tests/coordinator/test_mission_run.py:21` |
| snapshot mission shape, determinism | `tests/coordinator/test_mission_run.py:38` |
| mission failure reported once | `tests/coordinator/test_mission_run.py:64` |
| request `mission` overrides plan, validated | `tests/coordinator/test_mission_run.py:75` |
| HUD rendering | `apps/web/src/mission.test.tsx` |
| mission engine SSE == batch run | `tests/mission/test_serve.py` |


---

# 30. Engine overview, the "Example snapshot", and 3D terrain scale-up

Audience: the frontend implementer. Backend, pipeline and connectors are ours; the UI is yours.
All paths are relative to the repo root (worktree `handoff`, branch `handoff/skills-missions-pipeline`).
`file:line` references were read from this tree. Anything marked **[UNVERIFIED]** I could not confirm by reading code (nothing was executed: the suites hang on Windows).

## 0. Read this first (the three facts that shape everything)

1. **There are two engines and they are not joined.**
   - **Pipeline engine** (what the web app consumes today): `services/coordinator` runs `packages/adapters/sim2d` over `packages/sim` (`FlightWorld`), 4 node processes, telemetry to `services/api`, WebSocket to `apps/web`. Records are the canonical contract records (`snake_case`, `node-01..04`). World in the compose demo: **80 x 45 cells x 625 m = 50 x 28 km** (`infra/compose/compose.yml:66,141`).
   - **Mission engine** (`packages/mission/archipelago_mission`): standalone, pure Python, **400 km x 500 km**, 6 UAVs `UAV-01..06`, RF links, POIs, one P2P skill. Output is its **own camelCase frame format** (documented in `FRONTEND_INTEGRATION.md`, 846 lines), served by `python -m archipelago_mission.serve` over SSE, or as the static file `apps/web/public/mission/seed-1002.json`. **Nothing in `apps/web/src` imports or fetches it** (grep for `mission/seed` and `archipelago_mission` in `apps/web/src` is empty). It never produces a `WorldSnapshot` and never sends a terrain grid (`serve.py:62-78`, `sim.py:889-901`, `meta` has no `terrain`).
2. **The landing "Example snapshot" is not a recorded or live frame.** It is the 150th `world_snapshot` of the in-browser synthetic generator `startDemo()` (`apps/web/src/demo.ts`), a **10 x 6 km** fake world with fake terrain, no `mission`, no skills, no lineage. The finished product ("3D terrain simulation, scaled up") means: the same `<View>`/`FlightMap`/`Terrain3D` renderer fed by a world of 400 x 500 km, plus mission/skills/lineage panels. Section 6 and 7 specify the change set.
3. **The renderer is already metre-based and reads size from `snap.world`**, but several constants and one contract limit are tuned to a ~10-50 km world (section 7). The contract allows terrain up to 256 x 256 cells; the mission engine's 400 x 500 km at 10 km cells is 40 x 50 cells, so it fits.

## 1. End-to-end pipeline (as implemented)

```
 PIPELINE ENGINE (live today)                                     MISSION ENGINE (standalone, not bridged)
 --------------------------------------------------------         ----------------------------------------
 coordinator (services/coordinator, runner.py)                     MissionSim.step() every dt=30 s of sim time
   Sim2DAdapter -> FlightWorld (packages/sim)                        frame() -> camelCase {mission,uavs,pois,
   per tick: ask nodes /v1/act (deadline), world.step,                          links,disruptions}
   _emit_snapshot() = adapter.public_snapshot(links)               serve.py  GET /api/mission/stream (SSE)
        |  WorldSnapshot (world+terrain+mission)                             GET /api/mission/run   (full JSON)
        |  + MetricSample (coverage, target_found, map_seed, ...)  file  apps/web/public/mission/seed-1002.json
        v   spool (spool.py) -> POST /v1/telemetry                            (NO consumer in apps/web/src)
 node x4 (packages/node/runtime, Torch learner)
   LearningEvent, MetricSample (train_loss, skill.<n>, ...),
   PeerEnvelope  --- peer exchange node<->node (validated) ---
        |  POST /v1/telemetry  {source, boot_id, events[], context?}  (Bearer TELEMETRY_TOKEN)
        v
 api (services/api, FastAPI)  telemetry.py TelemetryIngest.admit()
   validate vs contract model -> dedupe (run_id,event_id)
   RE-SEQUENCE: event.sequence = run.seq (API counter), source_sequence = original
   add type=kind, tick=sim_tick, status=run.status, context
   run.events (ring, 5000)  +  run.last_world (newest world_snapshot)  +  Persister (TimescaleDB)
        |-- GET  /v1/runs/{id}/events?after_sequence&limit<=500   (paged replay)
        |-- GET  /v1/runs/{id}/skills                            (folded skill view)
        |-- WS   /v1/runs/{id}/stream                            (live; NO SSE in this API)
        v
 apps/web
   connectStream (status.ts) -> liveReducer -> {snap, learning, status}      => View props
   same raw message   -> recordOf() -> panelsReducer (live.ts) -> Panels     => LivePanels/MissionHUD/...
   usePlayback (replay.ts) buffers snaps, interpolates poses by TICK_S       => FlightMap getPoses
   replay mode: loadReplayRecords() pages /events; panelsAtFrame(records, frame)
        v
   <View> (View.tsx) -> <FlightMap> (FlightMap.tsx) -> Terrain3D (WebGL2) | 2D canvas fallback
```

Sources of truth: `services/api/src/archipelago_api/telemetry.py:164-229` (admit/re-sequence), `app.py:252-293` (routes), `services/coordinator/archipelago_coordinator/runner.py:313-331` (`_emit_snapshot`), `packages/adapters/sim2d/archipelago_sim2d/adapter.py:157-195` (snapshot build).

## 2. Channels and event kinds

### 2.1 Transport

| Channel | Direction | Shape | Notes |
|---|---|---|---|
| `POST /v1/telemetry` | node/coordinator -> API | `{source, boot_id, events:[record...], context?}` | Bearer `TELEMETRY_TOKEN`; max body/events limits `telemetry.py` (`MAX_BYTES`, `MAX_EVENTS`); 503 `Retry-After: 1` when overloaded |
| `WS /v1/runs/{id}/stream` | API -> web | text JSON | Cookie `COOKIE` or Bearer; origin must match host or `allowed_origins`; close code 1008 on bad origin/auth/unknown run (`app.py:260-293`) |
| `GET /v1/runs/{id}/events` | API -> web | `{events[], oldest_sequence, latest_sequence}` | `after_sequence>=0`, `limit` 1..500; ring of `event_log_size` = 5000 (`settings.py:29`) |
| `GET /v1/runs/{id}/skills` | API -> web | `{run_id, nodes{node{skill{proficiency,version,source}}}, adoptions[]}` | `skills.py`; the web folds the same events itself (`live.ts:117-122`), so this endpoint is optional for the UI |
| `POST /v1/runs` (+ `/commands`) | web -> API | run config + `map_offset` + optional `mission` | `client.ts:startRun`; commands `resume|pause|step|stop` with `expected_revision` |
| SSE | n/a | n/a | **Does not exist in the API.** SSE exists only in the standalone mission server `serve.py` (`event: meta|tick|end`). |
| "replay" | n/a | n/a | No replay endpoint: replay = paging `/events` (`client.ts:loadReplayRecords`) then `panelsAtFrame`. Offline: `apps/web/src/fixtures/partition_run.json` (27 records: 16 metric_sample, 5 world_snapshot, 3 peer_envelope, 3 learning_event) |

### 2.2 WebSocket message framing (what `liveReducer` and `recordOf` accept)

First message after accept, then raw events. `recordOf(m) = m.snapshot ?? m.event ?? m` (`live.ts:174`).

```json
{"sequence": 412, "type": "snapshot", "tick": 150, "status": "running", "snapshot": { "...WorldSnapshot..." }}
```
(`runs.py:156-175`). Subsequent messages are the admitted event dict itself (a contract record plus `type`, `tick`, `status`, `source_sequence`, `context`). On slow consumer the server sends `{"type":"resnapshot","reason":"slow_consumer"}` then a fresh `snapshot` message (`app.py:279-285`). Messages carrying `status` (string) update `live.status` (`status.ts:26`). Status-change messages come from `RunManager._emit` (`runs.py:138-153`): `{sequence,type,tick,status,...extra}`.

### 2.3 Base `Event` (all four kinds below extend it) `packages/contracts/src/archipelago_contracts/models.py:48-55`

| Field | Type | Notes |
|---|---|---|
| `schema_version` | str `^0\.\d+\.\d+$` | currently `"0.1.0"` |
| `event_id` | Id (1..128, `[A-Za-z0-9_.:-]`) | dedupe key with `run_id` |
| `run_id` | Id | |
| `source_node_id` | Id or null | null for coordinator-level records (snapshot) |
| `sim_tick` | int >= 0 | GLOBAL tick = `episode * max_ticks + tick` (`runner.py:_global_tick`) |
| `emitted_at_utc` | UTC datetime string | |
| `sequence` | int >= 0 | **overwritten by the API** with its own counter; original in `source_sequence` |

### 2.4 `world_snapshot` (`WorldSnapshot`, models.py:177-187)

| Field | Type / range | Notes |
|---|---|---|
| `kind` | `"world_snapshot"` | |
| `run_status` | `created|starting|running|paused|stopping|completed|failed|interrupted` | terminal = last three (`status.ts:6`) |
| `poses` | `{node_id: Pose}` | see 2.5 |
| `obstacles` | `[int,int][]` | legacy grid world only; **empty `[]` when `world` is present** (`adapter.py:184`) |
| `coverage` | float 0..1 | share of free cells sensed; UI prints `% of free cells` |
| `topology.links` | `[Id,Id][]` | undirected radio links currently allowed (fault windows cut them) |
| `world` | `WorldGeometry|null` | present only for `environment_mode=continuous_flight`; absent => legacy `<canvas>` path (`View.tsx:55-60`) |
| `mission` | `MissionStatus|null` | absent when the run has no mission; `applySnapshot` keeps the previous value (`live.ts:90`) |

Emitted: once per tick by the coordinator (`runner.py:_emit_snapshot`, called at the end of each tick step, `runner.py:~660`). Public view only: obstacles/shapes/`targets_found` are those some node has discovered (A10).

### 2.5 `Pose` (models.py:38-45)

| Field | Unit / range | Notes |
|---|---|---|
| `x`, `y` | **metres** in continuous worlds; legacy world: cell index + 0.5 | origin top-left, x east, y SOUTH (down) |
| `z` | `0 <= z <= 0` (contract forces 0) | altitude is NOT in the pose; UI derives it as `sampleElev + AGL_M` (80 m) |
| `heading_rad` | radians, `atan2(dy, dx)` in the y-down frame; 0 = east | UI compass bearing: `(deg + 90) mod 360` (`camera.ts bearingDeg`) |
| `speed_mps` | >= 0 | |

### 2.6 `WorldGeometry` (models.py:140-149)

| Field | Type | Unit | Used by |
|---|---|---|---|
| `width_m`, `height_m` | float > 0 | m | `fitZoom` (`FlightMap.tsx:115`), camera target, `exFor`, scale bar, `Terrain3D` extents |
| `cell_m` | float > 0 | m | terrain cell size; every `sampleElev(terr, x / cell_m, y / cell_m)` call |
| `sensor_radius_m` | float >= 0 | m | sensor ring, viewshed radius = `round(sensor_radius_m / cell_m)` cells (`FlightMap.tsx:251`), "Sensor radius" telemetry row |
| `shapes[]` | `{id, points:[x,y][>=3]}` | m | revealed obstacle polygons (`FlightMap.tsx:276`) |
| `targets_found[]` | `{x,y,radius}` | m | found-target markers |
| `terrain` | `TerrainGrid|null` | | absent => flat 2D map, no GL (`useGL` requires `world.terrain`, `FlightMap.tsx:152`) |

### 2.7 `TerrainGrid` (models.py:126-137; producer `flight.py:226-239`)

Row-major: `index = y * size + x`; `size` = columns (x), `height` = rows (y). Both `1..256`. Producer iterates `for y: for x:` so it matches (the sim's own arrays are `[x][y]`, converted at the producer).

| Field | Type | Meaning | Consumers |
|---|---|---|---|
| `size` | int 1..256 | width in cells | everything below |
| `height` | int 1..256 | height in cells | |
| `biome` | string, 1 digit/cell | `0` grass, `1` forest, `2` jungle | GPU `uB.r` (`terrain3d.ts:206`), fallback texture base colour (`terrainTexture.ts:5,96`) |
| `observed` | string, 1 char/cell, `"1"`/`"0"` | cell sensed by some node (fog of war) | `fogMask` (`terrain3d.ts:260`), `buildFogOverlay` (`terrainTexture.ts:179`), topo label visibility (`FlightMap.tsx:254`) |
| `elev_m` | float[], metres MSL, 1 decimal | ground elevation | `Float32Array` -> `uH` R32F texture (`terrain3d.ts:205`), `sampleElev` bicubic (`terrainTexture.ts:46`), mesh Z, LOS (`viewshed.ts`), altitude readout, `exFor`, ramp min/max (`terrain3d.ts:207`) |
| `veg_pct` | int[] 0..100 | vegetation density | `uB.g` (`terrain3d.ts:206`, default 50 if missing), speckle strength |

Display only: nodes never receive it. `observed` is the only part that changes over a run; `elev_m`, `biome`, `veg_pct` are constant within an episode but are re-sent in **every** snapshot (see payload note, section 8).

### 2.8 `MissionStatus` / `ObjectiveStatus` (models.py:152-174; producer `packages/sim/archipelago_sim/env.py:248-283`)

| Field | Type | Notes / UI |
|---|---|---|
| `id` | Id | `MissionHUD` bold id |
| `type` | Id | `search_rescue` | `coverage` (`mission.py:MISSION_TYPES`); `relocate` does NOT exist |
| `map_seed` | int >= 0 | `derive_map_seed(env_seed, episode)`; shown as "map seed" (HUD only renders it inside the mission block) |
| `status` | `active|succeeded|failed` | |
| `objectives[]` | `{id, kind: find_targets|cover_fraction, target: float>0, progress: 0..1, done: bool}` | `target` = count (find_targets) or fraction (cover_fraction) |
| `time_budget_ticks` | int >= 1 | HUD shows `clock(budget * TICK_S)` |
| `energy_budget` | float in (0,1] or null | |
| `energy_spent` | 0..1 | |
| `completed_tick` | int or null | set only when `succeeded`; HUD "completed in mm:ss" |
| `dynamics` | Id[] | any of `targets_move`, `targets_appear`, `obstacles_shift` |

Real example (shape used by `apps/web/src/mission.test.tsx:21-25`):
```json
{"id":"sr-demo","type":"search_rescue","map_seed":123456789,"status":"active",
 "objectives":[{"id":"find_targets","kind":"find_targets","target":4,"progress":0.75,"done":false}],
 "time_budget_ticks":120,"energy_budget":null,"energy_spent":0.25,"completed_tick":null,
 "dynamics":["targets_move","obstacles_shift"]}
```

### 2.9 `learning_event` (`LearningEvent`, models.py:205-224)

| Field | Type | UI use |
|---|---|---|
| `update_count` | int | node table "Updates" |
| `loss` | float or null | node table "Loss" |
| `previous_version`, `new_version` | int | node "Policy version" = `new_version` |
| `transfer` | `none|accepted|rejected` | `none` = local training only (no offer row, no lineage) |
| `reason` | str or null | rejection reason |
| `candidate_score` | float or null | offers table "Candidate score" |
| `bytes` | int | offers "Size" |
| `wall_seconds` | float | not displayed |
| `policy_id`, `parent_ids[]`, `origin_node`, `generation_count`, `flagged_peer` | lineage DAG node: candidate if rejected, adopted policy if accepted | `applyLineage` (`live.ts:133-145`): DAG capped at `MAX_DAG`=200; `flagged_peer` marks state `flagged` |
| `skill`, `skill_gain` | Id / float, set on peer decisions | contract + API `skills_view` use it (`skills.py`); **`apps/web` does not read them** (grep: no `skill_gain` in `apps/web/src`) |

Real fixture (`packages/contracts/fixtures/good/learning_event.json`): `transfer:"rejected"`, `reason:"score_below_tolerance"`, `candidate_score:-0.5`, `bytes:1024`, `new_version:2`, `source_node_id:"node-02"`.

Offer rows need the **sender**: it is not on the learning event. The UI joins the newest earlier `peer_envelope` with the same `recipient == source_node_id` and `model_version == new_version` and lower `sequence` (`live.ts:151-153`). If none was seen, `sender` is null.

### 2.10 `metric_sample` (`MetricSample`, models.py:227-232)

`{metric: Id, value: float, unit: Id, phase: train|eval|partition|recovery|other}` plus Event base. Metric names the web reducer acts on (`live.ts:97-123`):

| `metric` | `value` / `unit` | Folds into |
|---|---|---|
| `train_loss` | loss | `nodes[id].loss` |
| `replay_size` | transitions | `nodes[id].replaySize` |
| `rss_bytes` | bytes | `nodes[id].rssBytes` |
| `telemetry_backlog`, `telemetry_dropped` | events | node table |
| `deadline_missed`, `node_unavailable` | count | `counters` (no node) |
| `fault_phase` | phase `partition` => partitioned, `recovery` => recovering, else connected | `faultPhase` |
| `coverage` | fraction | `coverage` |
| `targets_total` | count | `mission.total` (enables the Targets Found bar) |
| `target_found` | value = cumulative found; **value 1 resets the list** (new episode) | `mission.finds[{tick,node}]` |
| `episode_return` | unit e.g. `reward`; phase `train` or `eval` only | `train`/`eval` curves, capped `MAX_CURVE_POINTS`=200 |
| `skill.<name>` | proficiency 0..1, unit `score`, phase `eval` | `skills[node][name].proficiency` (`node.py:1005-1009`) |
| `skill_version.<name>` | version int; **unit `source:<node>`** carries where it came from | `skills[node][name].version/source` |
| `map_seed`, `mission_complete`, `mission_failed` | emitted by coordinator (`runner.py:645-660`) | **not read by `live.ts`**; the HUD gets the seed from `mission.map_seed` in the snapshot |

Any other metric name: only touches the node's `lastEventAt`. Real fixture: `metric: "coverage_fraction"` (not consumed).

### 2.11 `peer_envelope` (`PeerEnvelope`, models.py:190-202)

`type: hello|model_offer|model_request|model_payload|ack`, `sender`, `recipient`, `message_id`, `model_version` (int), `architecture_hash`, `encoder_hash`, `reward_hash` (sha256 hex), `payload_length` (<= 4 MiB), `payload_sha256|null`, `ttl_ticks > 0`. The UI uses only `sender`, `recipient`, `model_version`, `sequence` (`live.ts:127-131`, bounded to 200 entries). It does not filter by `type`.

## 3. Units and coordinate conventions (single table)

| Quantity | Convention |
|---|---|
| Length | metres everywhere in continuous worlds (`Pose`, `WorldGeometry`, shapes, markers). Display in km via `km()` = `(m/1000).toFixed(2) km` |
| Frame | x east, y south (down), z up. Origin = top-left corner of the world. `(0,0)`..`(width_m,height_m)` |
| Cell of a point | `floor(x / cell_m)`, `floor(y / cell_m)`; grid index `y*size + x` |
| Heading | radians, 0 = east, increasing toward +y (south). Not normalised: the demo emits values like 15.1 rad; consumers must not assume (-pi, pi] |
| Time | `sim_tick` is a unit; seconds = `tick * TICK_S`, `TICK_S = 7.5` hard-coded (`replay.ts:7`, note says "add sim_time to the contract"). Mission engine uses `dt = 30 s` per tick |
| Elevation | metres above datum, `elev_m` per cell centre. Drone altitude shown = elevation + `AGL_M` (80 m, `viewshed.ts:3`, mirrors `Terrain.agl_m`) |
| 3D exaggeration | `exFor(width_m, terrain)` = clamp(`0.18 * width / maxElev`, 1..4), rounded to 0.1 (`FlightMap.tsx:20`) |
| Camera | `makeCam3`: FOV 40 deg, `tilt` = elevation above horizon (pi/2 = straight down, north up); pitch follows zoom 84 deg (far) to 22 deg (near) over `ZR_NEAR`=12x zoom (`FlightMap.tsx:23-26`) |
| Colours | brand: `#0A0A0A` bg, `#EDE7DF` stone, `#F47B3C` orange accent, `#8A8A8A` grey (`FlightMap.tsx:15`) |

## 4. Where each terrain field is consumed (renderer map)

| Stage | File:line | Reads |
|---|---|---|
| Mesh + textures upload (once per terrain key) | `terrain3d.ts:201-237` `setTerrain(t, cellM)` | `size,height,elev_m,biome,veg_pct`, `cell_m`. Mesh = `(size*3+1) x (height*3+1)` vertices (`SUB=3`) with 4 skirt walls to `-SKIRT_M` = 400 m |
| Re-upload trigger | `FlightMap.tsx:246-249` | key `terr.biome + w.cell_m` (note: keyed on biome string, NOT elevation; a new episode with identical biome but new elev would not re-upload) |
| Fog | `FlightMap.tsx:250` -> `fogMask` `terrain3d.ts:260` | `observed` (3x3 softened) -> `uFog` R8 |
| Line of sight | `FlightMap.tsx:251` -> `viewshed.ts buildViewshed/losClear` | `elev_m`, drone cells, radius in cells, `AGL_M`, `TARGET_H_M`=2 |
| Fragment shader | `terrain3d.ts:56-163` | `uCell` (=cell_m), `uGrid`, `uZmin/uZmax` (data min/max +-20 m), style topo/imagery, contour 50 m minor / 250 m index, 1 km graticule, `DETAIL`=45 m noise, fog + dashed orange frontier, hatch, distance haze |
| Fallback (no WebGL2) | `terrainTexture.ts:62-155` `buildTerrainBaseAsync`, `:179 buildFogOverlay` | same fields; texel/cell `upFor = clamp(floor(sqrt(1.1e6/(size*height))), 6..24)` |
| Altitude/camera ground | `FlightMap.tsx:156,218,229` | `sampleElev` (Catmull-Rom bicubic) |
| Topo labels | `topoLabels.ts` `contourLabels(terr, cell_m)` | elevation index contours |

Styles: `MapStyle = "natural" | "topo"` (`terrainTexture.ts:3`); toggles in FlightMap top-left (`Fit world`, `Imagery/Topo map`, `2D/2.5D`, `Follow`).

## 5. How the landing "Example snapshot" is built

`apps/web/src/App.tsx`:

| Line | Behaviour |
|---|---|
| 21-27 | `runId = params.get("run") ?? (demo ? "demo-run" : null)`; `source = "fixture"` when there is no `runId` (no `?run`, no `?demo`) |
| 40-51 | `useEffect` when `!runId`: `startDemo(cb, 1)` (interval 1 ms); counts `kind === "world_snapshot"` messages; at `++n === 150` -> `setPreview(r)` and `stop()`. All other kinds (`learning_event`, `peer_envelope`) are parsed and **dropped** here |
| 79 | `snap = source === "fixture" ? preview ?? fixture : ...` — until frame 150 arrives it renders the contract fixture `packages/contracts/fixtures/good/world_snapshot.json` (no `world`, so the legacy `<canvas>`, 2 drones) |
| 104-124 | landing page chrome; `<h2>Example snapshot</h2>` is the last element before `<View>` |
| 125 | `<View ... source="fixture" details={details && !landing} panels={source === "fixture" ? undefined : shownPanels} playback={undefined} spotlight={undefined} status={undefined} learning={live.learning} now={now}/>` — i.e. `details=false`, `panels=undefined` |

What this hides (`View.tsx`):

| Element | Condition | Result on landing |
|---|---|---|
| status line | always | `FIXTURE (not a live run)` (`status.ts sourceLabel`) |
| run summary `Run / status / tick / coverage` | `snap` | shown: `Run: demo-run · status: running · tick: 150 · coverage: 18.8% of free cells` |
| `FlightMap` | `snap.world` | shown, `instant=false`, height `66vh`, no `playback` => no `Timeline`, no `getPoses` (pose interpolation uses `PoseBuffer` fed once; a frozen frame therefore has static drones) |
| `Curves` | `present && panels` | hidden |
| drone list `<ul aria-label="Drones">` | `details` | hidden (details false) |
| `LivePanels` (`MissionHUD`, fault phase, node table, offers, `SkillList`, `LineagePanel`, curves, resources) | `details && panels && source !== "fixture"` | **hidden by three independent conditions** |
| FlightMap overlays driven by `panels` | `panels?.offers`, `panels?.nodes[selected]` | offer feed list empty, orange offer arcs none (`FlightMap.tsx:308`), node telemetry card shows "not reported" for policy fields |

### 5.1 What `startDemo` puts in frame 150 (`demo.ts`, `ctl` undefined)

Per tick (`tick++`, `t = tick*7.5`): 4 poses on tilted ellipses around (5000, 3000) m, `z:100` (violates the contract's `z==0`; the UI ignores it), heading `a ± pi/2` unwrapped, `speed_mps = |w|*r`. Frame 150 computed from the formulas:

| node | x (m) | y (m) | heading_rad | speed_mps |
|---|---|---|---|---|
| node-01 | 5892.4 | 3723.4 | 15.1 | 18.0 |
| node-02 | 3734.6 | 1920.2 | -16.3 | 30.8 |
| node-03 | 6183.4 | 4588.5 | 21.6 | 46.4 |
| node-04 | 4896.5 | 5159.1 | -18.8 | 64.8 |

Other frame-150 values: `sim_tick:150`, `run_status:"running"`, `source_node_id:null`, `obstacles:[]`, `coverage:0.1875` (`tick/800`), `topology.links:[["node-01","node-02"],["node-03","node-04"]]`, no `mission`. `observed`: union of 5x5 cell windows around each pose over ticks 1..150 = **636 of 960 cells**. Synthesised terrain: 40 x 24 cells x 250 m; `biome` from `sin(x/7)+cos(y/6)` (values 0..2); `elev_m` from warped ridges plus 3 Gaussian massifs (about 122..1602 m, rounded to integers); `veg_pct` all 50. Envelope fields added by `send()`: `run_id:"demo-run"`, `sequence`, `schema_version:"0.1.0"`, `emitted_at_utc`, `event_id:"ev-<seq>"`.

```json
{"kind":"world_snapshot","sim_tick":150,"source_node_id":null,"run_status":"running",
 "poses":{"node-01":{"x":5892.4,"y":3723.4,"z":100,"heading_rad":15.1,"speed_mps":18.0}, "...":"node-02..04"},
 "obstacles":[],"coverage":0.1875,
 "topology":{"links":[["node-01","node-02"],["node-03","node-04"]]},
 "world":{"width_m":10000,"height_m":6000,"cell_m":250,"sensor_radius_m":400,"shapes":[],"targets_found":[],
          "terrain":{"size":40,"height":24,"biome":"<960 digits>","observed":"<960 of 0/1>","elev_m":[ "...960 ints"],"veg_pct":[50,"...960"]}},
 "run_id":"demo-run","sequence":N,"schema_version":"0.1.0","emitted_at_utc":"...","event_id":"ev-N"}
```

Caveat: `demo.ts` fires `setInterval(…, 1)` which browsers clamp (~4 ms nested), so the preview appears after ~0.6-1 s; before that the legacy fixture canvas shows.

## 6. Change set so the frozen frame shows panels (requirements, not UI code)

Goal: the landing frame shows, under/over the 3D map, the same sections `LivePanels` shows in a live run: mission HUD with map seed, skills table, capability lineage tree, plus offers/curves as desired. Requirements:

R1. **Panel data must exist in the preview.** `App.tsx:46-48` currently discards every record except the 150th snapshot. Requirement: feed *every* record produced up to frame 150 through `panelsReducer` (same `recordOf` + `{t:"record", record, at}` path as `App.tsx:59`) and freeze the resulting `Panels` together with the snapshot. Note the reducer drops `sequence <= lastSequence` and records with a different `run_id`, so the preview must keep one `run_id` and monotonically increasing `sequence` (the generator already does).

R2. **The generator must emit what the panels fold.** `demo.ts` (no `ctl`) currently emits only: `world_snapshot` every tick; every 6th tick one `peer_envelope` + one `learning_event` (fields `policy_id, parent_ids, origin_node, generation_count, flagged_peer, transfer, reason, new_version, update_count, loss, bytes` — enough for lineage and offers). It emits **no** `metric_sample` and **no** `mission`. To populate the panels it must also produce: (a) `mission` object on snapshots (section 2.8 shape) with `map_seed`, objectives progressing with ticks, `time_budget_ticks`, `dynamics`; (b) `metric_sample` `targets_total` and `target_found` (value cumulative) so the Targets Found bar and the P2P boost pill work (`searchBoost` needs finds before and after the first accepted adoption, `live.ts:36-42`); (c) `skill.<name>` and `skill_version.<name>` (unit `source:<node>`) per node, with a cross-node source after an accepted offer; (d) optionally `episode_return` train/eval, `train_loss`, `replay_size`, `rss_bytes`, `fault_phase` for the node table, curves and network row. Today the node table, curves and skills would all read "not reported"/"No skills measured yet".

R3. **Frame selection.** The preview's frame 150 is `n === 150` on snapshots only. If the generator emits extra records, keep the counter on `world_snapshot`s, but build `Panels` from all records with `sequence <=` the 150th snapshot's.

R4. **View must be allowed to render panels for `source === "fixture"`.** Three gates must change for the landing: `App.tsx:125` (`panels={source === "fixture" ? undefined : ...}`), `App.tsx:125` (`details={details && !landing}`), and `View.tsx:69` (`source !== "fixture"`). Decide per gate; the label stays `FIXTURE (not a live run)` (`panelLabel/sourceLabel`) and freshness uses `recorded` (`Panels.tsx:47` `recorded` shows "recorded" instead of fresh/stale). Pass `recorded` semantics for fixture, not live freshness.

R5. **Frozen means static.** No `playback` => no Timeline; `FlightMap` interpolates from one pushed frame, so drones do not move. If an animated landing is wanted instead, use `usePlayback`-style buffering (`replay.ts`) which currently only runs when `source === "live"` (`App.tsx:36`).

R6. **Honest labelling.** The landing frame is synthetic. Keep `FIXTURE (not a live run)` or an equivalent "synthetic example" label; do not present it as measured data (`demoScriptController.ts:1-3` already states the scripted demo is synthetic).

R7. **Scale (see section 7).** For the "scaled up" 3D frame the generator (or its replacement) must emit `world.width_m/height_m/cell_m/sensor_radius_m` for the 400 x 500 km world and a terrain grid sized to it. Until the mission engine is bridged (section 8), the faithful option is a fixture with that geometry, not a live pipeline.

Test hooks that currently pin behaviour: `apps/web/src/view.test.tsx`, `mission.test.tsx`, `live.test.tsx`, `skills.test.tsx`, `lineage.test.tsx`, `terrain3d.test.ts`, `hygiene.test.ts` (read before changing gates) **[UNVERIFIED: whether hygiene.test.ts forbids synthetic data strings]**.

## 7. Scale-up: 10 x 6 km demo -> 50 x 28 km compose demo -> 400 x 500 km mission world

### 7.1 The three worlds

| World | Where | width x height | cell_m | grid | sensor | speed | tick |
|---|---|---|---|---|---|---|---|
| Landing synthetic | `demo.ts:30,56` | 10,000 x 6,000 m | 250 | 40 x 24 | 400 m | ~18-65 m/s | 7.5 s (assumed) |
| Pipeline default | `flight.py:60` `size=32, cell_m=625` | size*625 | 625 | 32 x 32 | `radius*cell_m` | 80 m/s | 7.5 s |
| Pipeline compose demo | `compose.yml:141` | 50,000 x 28,125 m | 625 | 80 x 45 | `radius*625` | 80 m/s | 7.5 s |
| Mission engine | `packages/mission/.../sim.py:22-41` | **400,000 x 500,000 m** (4 x 5 tiles of 100 km) | **10,000** (`CELL_M`) | **40 x 50** terrain cells (`Terrain.generate(40, 10000, seed, height=50, style="alpine")`, `sim.py:178-180`); separate 16 x 20 search grid of 25 km | 40,000 m (`UAV_SENSOR_M`) | 140 m/s | 30 s |

Mission-world constants: 6 UAVs, 6 POIs, cruise altitude 400 m AGL (max 2000), nominal link 40 km (extended 100 km, report range 150 km), time limit 28,800 s (8 h), terrain relief `500 * 2.8` = up to ~1400 m (alpine, `terrain.py:94`). Seed 1002 succeeds at 8520 s (285 frames) per `FRONTEND_INTEGRATION.md`.

### 7.2 Contract-level rules

- **Never hard-code the world.** `FRONTEND_INTEGRATION.md:21` says the mission frontend "must read it from `meta.world`". For the pipeline path the equivalent is `snap.world.{width_m,height_m,cell_m,sensor_radius_m}`; `FlightMap` already does (`FlightMap.tsx:115-117`).
- `TerrainGrid.size` and `.height` are capped **256** in the Pydantic model, JSON schema (`record.schema.json:1302,1312`) and generated TS. 40 x 50 fits. A finer grid (e.g. 2.5 km cells -> 160 x 200) also fits; 1 km cells (400 x 500) does not without a contract change.
- `WorldGeometry.cell_m` is "hidden perception/learning grid". In the mission engine the terrain cell (10 km), the search cell (25 km) and the sensor radius (40 km) differ; the contract has one `cell_m`. The renderer needs only the **terrain** cell size there.
- Mission-engine entity fields (UAVs, POIs, RF links, disruptions) have **no contract record**. To show them in `FlightMap` they must be mapped into `poses`, `topology.links` and (new) optional fields, or rendered from the camelCase frame directly. Decide and add to the contract if mapped (contract changes need `packages/contracts` regeneration; `make check-integration` includes contract drift).

### 7.3 Hard-coded constants that assume a small world (must become data-driven or be re-tuned)

| Constant | File:line | Value | Problem at 400 x 500 km (10 km cells) | Requirement |
|---|---|---|---|---|
| `TICK_S` | `replay.ts:7` | 7.5 s | mission engine ticks are 30 s; HUD clock and interpolation would be 4x too fast | read from mission `meta.dt` / add `sim_time` or `tick_s` to the contract |
| `AGL_M` | `viewshed.ts:3` | 80 m | engine LOS uses `Terrain.agl_m` 80 for detection but UAV cruise is 400 m AGL (RF) | decide which altitude the UI shows; read from data |
| `niceLen` scale bar | `FlightMap.tsx:69` | max 10,000 then 20,000 m | 400 km map needs 50/100/200 km steps | extend ladder / compute |
| `TRAIL_STEP_M` / `TRAIL_MAX` | `FlightMap.tsx:17` | 30 m / 600 pts | at 140 m/s and 30 s ticks one step is 4.2 km; 600 points = fine, but a 30 m threshold is meaningless | scale the step with world size |
| `SKIRT_M` | `terrain3d.ts:43` | 400 m | relief up to ~1400 m; skirt wall is shallow relative to 400 km extent | scale with relief |
| `DETAIL_M` shader noise | `terrain3d.ts:63`, `terrainTexture.ts:12` | 45 m amplitude, 3 cycles per cell | on 10 km cells this adds ~3 km-scale noise: harmless in amplitude, but contour levels (50 m) will be dense | tune; contour interval `CONTOUR_M`=50, `INDEX_EVERY`=5 |
| 1 km graticule | `terrain3d.ts:139`, `terrainTexture.ts:138-143` | 1 km grid + labels | fallback canvas draws 400 vertical lines every ~2.3 px (`step = 1000/cellM*UP`) and a number each: unusable | graticule spacing from world size (e.g. 25/50 km) |
| `Terrain3D.grid.cell` default | `terrain3d.ts:171` | 625 | overwritten by `setTerrain`; fine | none |
| Fallback texture size | `terrainTexture.ts:10` | `UP = clamp(floor(sqrt(1.1e6/(size*height))), 6, 24)` | 40 x 50 -> UP=23 -> 920 x 1150 px: OK | none |
| `exFor` | `FlightMap.tsx:20` | caps exaggeration at 4x | 400 km wide, 1.4 km relief => capped 4.0, relief reads as ~1% of width; mountains will look flat | allow higher cap or tilt/zoom-dependent exaggeration |
| `PITCH_*`, `ZR_NEAR` | `FlightMap.tsx:23` | 84 -> 22 deg over 12x zoom | zoom range from 400 km to ~km features needs > 12x (full range ~100x) | widen zoom/clip planes (`near = dist*0.05`, `far = dist*14`, `terrain3d.ts:20`) |
| Viewshed | `viewshed.ts` | radius = `round(sensor_radius_m/cell_m)` = 4 cells; each drone does (2r+1)^2 LOS rays | fine for 6 UAVs; `AGL_M` mismatch above | none |
| Re-upload key | `FlightMap.tsx:246` | `terr.biome + w.cell_m` | a new map with the same biome string keeps stale elevation | include a terrain hash/seed (needs `map_seed` or hash on the wire) |
| Demo generator | `demo.ts:30-56` | 40 x 24 @ 250 m, canyon at `CANYON` box in metres | all literals | parametrise from the target world |

Positions in the demo (z:100, headings unwrapped) are not representative of the engine; the mission engine heading is `atan2(dy,dx)` rad per frame.

### 7.4 Payload size (estimate, not measured)

Each `world_snapshot` re-sends the full terrain. By character count: 80 x 45 = 3,600 cells => `biome` 3.6 kB + `observed` 3.6 kB + `elev_m` ~4 digits+sep x 3,600 ~ 20 kB + `veg_pct` ~ 10 kB ~ 37 kB. 40 x 50 = 2,000 cells ~ 20 kB; 256 x 256 would be ~ 700 kB. The API rejects any `POST /v1/telemetry` body over 256 KiB (`MAX_BYTES`, `telemetry.py:34`; max 500 events per POST, `MAX_EVENTS`), so one snapshot must stay well below that: 256 x 256 (~700 kB) would be refused without a contract/transport change. (`MAX_PAYLOAD_BYTES` = 4 MiB, `models.py:12`, is the cap on a peer model payload, not on a telemetry record.) The API keeps 5000 events in memory (`event_log_size`), so a long run with one snapshot per tick is O(100 MB) at 80 x 45. **[UNVERIFIED: not measured]** A static-terrain-once + `observed` delta design would need a contract change; not implemented.

## 8. Not wired / gaps (explicit)

1. **No bridge mission-engine -> contract.** No code converts `MissionSim.frame()` to `WorldSnapshot`, and no process runs it inside the coordinator/API. `packages/mission` is a leaf package (`pyproject`/imports only from its own tests).
2. **No terrain in the mission engine output.** `serve.py` and `result()` do not emit `elev_m/biome/veg_pct/observed`. `MissionSim.terrain` exists in memory (`sim.py:178`) with the data the `TerrainGrid` needs (apply the `flight.py:226-239` conversion: sim arrays are `[x][y]`, wire is row-major). There is no "observed" notion at the fleet level in the mission sim except per-node `own_cells` (search-grid cells, 25 km) and `global_cells` (truth); mapping to the 10 km terrain grid is undefined.
3. **No frontend consumer** of `FRONTEND_INTEGRATION.md`'s camelCase frames. `apps/web/public/mission/seed-1002.json` (4.3 MB) and `apps/web/public/recon/*.json` (recon variants, summary.json) are static assets with no importer in `apps/web/src`.
4. **No SSE or replay endpoint in the API** (WebSocket + paged events only).
5. **Landing generator has no mission/metrics/skills** (R2). `DemoControls`/guided mode (`?demo=guided`) is a scripted 5-act story with `CANYON`-box terrain; separate from this.
6. **`learning_event.skill` / `skill_gain`** are on the wire and in `/skills`, but the web UI only folds `metric_sample skill.*`.
7. **Terrain is re-sent every snapshot**; no static-terrain message type.
8. **`TICK_S` is a constant**, not a wire field (`replay.ts:6-7`).
9. Pose `z` is always 0; altitude exists only as the derived `elevation + AGL_M` in the UI, while the mission engine has per-UAV `altitudeMeters` (400 m cruise, climbs to 2000 m when isolated).
10. Mission `relocate` type is not implemented (`mission.py:19-22` comment).

## 9. How to run things (docs only; I executed none of these)

| Goal | Command | Notes |
|---|---|---|
| Web dev server | `cd apps/web && npm run dev` | Vite; proxies `/v1` and the WS to `ARCHIPELAGO_URL` (default `http://127.0.0.1:8000`) (`vite.config.ts`) |
| Landing example | open `/` (no query) | the "Example snapshot" |
| Synthetic live demo | `/?demo=1` | `startDemo(onEvent, 100)`: no API; 1 snapshot per 100 ms = 75x realtime |
| Guided showcase | `/?demo=guided` | scripted 5-act story |
| Live run | `/?run=<id>` | WS `/v1/runs/<id>/stream` |
| Replay | `/?run=<id>&replay=1` | pages `/events`; frame slider |
| Presentation mode | add `&present=1` | adds curves + Details checkbox |
| Web tests / build | `cd apps/web && npm test` (vitest), `npm run typecheck`, `npm run build` | `test` = `vitest run` |
| Full stack (Docker) | `make demo` (plan `smoke`) or `make demo PLAN=demo`; `make demo-up PLAN=demo` to keep the stack | `infra/demo/README.md`; run config template `apps/web/src/live_run_config.json` |
| API only (fixture adapter) | `ARCHIPELAGO_ADAPTER=fixture` + `create_app_from_env` (`app.py:301`); adapters `fixture|sim2d|live` | exact uvicorn invocation **[UNVERIFIED]**: see `services/api/pyproject.toml` / compose |
| Mission engine CLI | `PYTHONPATH="packages/mission:packages/sim" python -m archipelago_mission --seed 1002 [--out FILE] [--no-skills] [--compare]` | Windows PowerShell: `$env:PYTHONPATH="packages/mission;packages/sim"` (`FRONTEND_INTEGRATION.md:631`) |
| Mission engine server | `python -m archipelago_mission.serve --port 8765` | `GET /api/mission/{health,run?seed=,stream?seed=&tps=&skills=0}` |
| Fixtures (valid records) | `packages/contracts/fixtures/good/*.json` (action, artifact_manifest, learning_event, metric_sample, observation, peer_envelope, run_config, world_snapshot); `fixtures/bad/` negative cases | the good `world_snapshot` has no `world`; web imports it directly (`App.tsx:5`, `view.test.tsx`) |
| Recorded run | `apps/web/src/fixtures/partition_run.json` | input shape for `infra/demo/artifacts.py` |
| Validation | `make check-fast` (gate), `make check-integration` (`SKIP_DOCKER=1 scripts/check.sh`), `make check-full` (Docker) | per `CLAUDE.md`; ledger via `python agents/controller.py status|next` |

## 10. Windows caveats and open verifier findings

Windows:
- Node-subprocess/Docker tests hang. `conftest.py:41-49` returns `pytest_ignore_collect=True` on `win32` for `tests/infra`, `tests/e2e`, `tests/swarm`, `tests/noderuntime`, `tests/experiments` unless `ARCH_ALLOW_SLOW=1`. Comment in file: "shortcut: whole dirs skipped incl. in-process tests there".
- Hang guard: per-test `ARCH_TEST_TIMEOUT` (default 120 s) and whole-session `ARCH_SESSION_TIMEOUT` (default 420 s); on expiry it dumps stacks and `taskkill /F /T` the pytest tree, exit 124 (`conftest.py:1-31`).
- Mission-engine regeneration uses `;` as `PYTHONPATH` separator on PowerShell (`FRONTEND_INTEGRATION.md:631`).
- This session ran no test suites for that reason.

Open verifier findings (as reported to me; each checked against the tree where possible):
1. **Duplicate test basename** `tests/sim/test_mission.py` and `tests/mission/test_mission.py` — both exist; neither directory has `__init__.py`, so pytest `rootdir`-style collection of the whole tree fails with an import-file-mismatch. **Confirmed present** (file listing); the collection error itself is **[UNVERIFIED: not run]**. Fix: rename one (e.g. `tests/sim/test_sim_mission_spec.py`) or add `__init__.py`.
2. **`relocate` mission type missing** — confirmed: `MISSION_TYPES = ("search_rescue", "coverage")` with a `shortcut:` comment (`packages/sim/archipelago_sim/mission.py:19-22`).
3. **HUD hides the map seed without a mission** — confirmed by reading: `MissionHUD` returns null when `m.total === null && !ms` (`MissionHUD.tsx:13`) and prints `map_seed` only inside `ms &&` (`:26`). The `map_seed` metric the coordinator emits (`runner.py:645`) is not consumed by `live.ts`.
4. **`test_t30` seed changed 7 -> 1** — `tests/experiments/test_t30.py:43,57` (`seed=1`, "maps are now derived from (seed, episode)"). Consistent with the claim; the old value 7 is **[UNVERIFIED: read via git history]**.
5. **Learner does not use the mission / shifting obstacles** — **[UNVERIFIED]**: not traced through `packages/learning` / `packages/node/learner`. Consistent with the observation encoder being a crop of the local grid (`Observation.crop`, `known_mask`, `visible_markers`; no mission field in `Observation`, models.py:92-99).
6. **Learner does not beat the rule explorer** — documented: `agents/STATUS.yaml` ("learner does not beat the rule explorer; fleet vs isolated nodes not shown to differ on validation curves"), `agents/handoffs/T37/LATEST.md:22` (return -15.8, CI [-24.7, -8.6], worse), `T30/LATEST.md:14`. Learning does beat idle/random/untrained on frozen test seeds (T37). **Do not claim the learner outperforms a baseline rule policy in the UI.**

## 11. Unverified / not read

- The 20+ line bodies of `FlightMap.tsx` render loop (lines 130-360) were read only at the cited anchors; interactions (drag/wheel/follow) not described here.
- `topoLabels.ts`, `camera.ts` internals, `Timeline.tsx`, `demoScriptController.ts` beyond its header were skimmed, not specified.
- Behaviour of `ctl` (guided) branch of `startDemo` is only referenced.
- Actual runtime appearance (no browser launched), real payload sizes, and whether `check-fast` passes on this branch (not run).
- `services/api` exact process entrypoint and `COOKIE` name; coordinator HTTP routes (`httpd.py`) are not documented in this part.


---

