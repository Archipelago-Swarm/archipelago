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
