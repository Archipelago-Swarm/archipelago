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
