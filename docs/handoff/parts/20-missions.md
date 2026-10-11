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
