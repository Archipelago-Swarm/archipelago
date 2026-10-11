# Decentralized Learning Backend (`archipelago_swarm`): Handoff

Written from the code as it exists (modules read in full; constants quoted from source, parameter count measured by instantiating `NodeLearner`). Package: `packages/swarm/archipelago_swarm/`. Runner: `scripts/swarm_experiment.py`. Verified on 2026-10-11 against the working tree: the commands below were run, the 35 tests in `tests/swarm` pass, and `experiment` exits 0 with every check true (section 23). Constants are quoted from source; re-check them if the code changes.

## 1. Executive summary

An in-process swarm of UAV nodes. Each node owns its own DQN learner, replay buffer, optimizer, skill registry, decision history and peer view. Nodes learn terrain-following goal navigation locally. When a node's policy passes an evaluation gate it freezes the weights as a **skill** (a hashed, versioned artifact with evidence). Skills move between nodes only as RF-gated messages over a terrain-aware link model (no routing, no shared memory). A receiver validates the artifact, evaluates it on its own eval set, activates it only if it beats its current policy, may keep training it, and may later derive a new skill with lineage. Every action is stored with a grounded decision trace. A deterministic 10-phase experiment (`experiment.py`) exercises spawn → terrain-induced fragmentation → isolated learning → skill → topology change → transfer → reuse → adaptation → derivation. This package is **separate from, and not wired into**, the live coordinator/noderuntime stack.

## 1a. Backend audit (what existed before this work)

Classification was made by reading the code, not the docs.

| Component | Class | Evidence / note |
|---|---|---|
| Per-node PyTorch DQN (`packages/learning/torch_dqn.py`), NumPy twin, checkpoints | REAL | own nets/Adam/replay per instance; **reused** as the base of `NodeLearner` |
| Peer parameter exchange (`peer.py`) | PARTIAL | tensor payloads, validation, accept/reject, rollback, lineage DAG for whole-network weights; no skill/artifact/provenance concept; only `params_sha256` reused |
| Grid world + `Terrain` (`packages/sim`) | REAL, but terrain only occluded sensor crops / marker detection | `terrain.py` docstring: hidden terrain is for visibility physics; the DQN encoders (`grid-flat-v1/v2`) contain no terrain. `Terrain.generate/drone_alt` **reused** |
| Reward `rew-v0` / `rew-v1` | REAL | coverage/target-finding reward of the old grid task; not reused (different task) |
| Connectivity (`coordinator/runner.py::_allowed_links`) | SCRIPTED | `all_pairs(alive) - cut_links` from fault windows; no distance/terrain/RF |
| Node runtime / coordinator / HTTP transport | REAL | separate-process nodes; not modified and not wired to `archipelago_swarm` |
| Skills / capabilities in the Python backend | DID NOT EXIST | no skill object, registry or provenance in any `.py`; "capability" appears only in docs, `apps/web` (`demoScriptController.ts`, `Lineage.tsx`) and Remotion/brand-kit |
| Decision tracing | DID NOT EXIST | telemetry had metrics/events, no per-decision policy output |
| `agents/` ledger, controller | REAL | process tooling, not touched |

Everything below is the new package `packages/swarm/archipelago_swarm`, which is **standalone and in-process**; it reuses `TorchLearner`, `params_sha256` and `Terrain` but is not integrated into the coordinator/noderuntime stack.

## 2. Node architecture

`SwarmNode` (node.py) holds: `NodeLearner`, `SkillRegistry`, position/battery, geofence (`fence`), private eval set, goal RNG, decision/outcome deques, peer view (`peers`), in/out transfer state, counters `c`. It reaches the world only via `plant` (the shared `NavWorld`, used as a stateless observe/step physics for its own cell) and the network only via a `NetPort`. It holds no reference to other nodes.

Per tick (`SwarmNode.tick`): 1) network phase (neighbours, discovery/loss, inbox handling, advert every `advert_period`, summary every `summary_period`, request, stream out, stall check); 2) act phase (observe, Q forward, ε-greedy, safety-checked step, reward, store experience ×8, maybe train, write trace); 3) skills phase when learning and `learn_steps % eval_every == 0`.

Seeding (swarm.py): all nodes share `init_seed = seed` (identical initial weights) and get distinct `node_seed = seed*1000 + 17*i + 1` (replay sampling, torch generator, exploration RNG, goal RNG, eval set).

## 3. PyTorch learner

`NodeLearner(TorchLearner)` (learner.py, subclassing `packages/learning/.../torch_dqn.py`):

| Item | Value |
|---|---|
| Algorithm | Double DQN (`double=True`; online net picks argmax, target net evaluates) |
| Network | MLP 13 → 64 → 4, ReLU (`w1 13×64, b1 64, w2 64×4, b2 4`) |
| Parameters | **1156** (measured: 832+64+256+4) |
| Optimizer | Adam, lr `2e-3`, betas (0.9, 0.999), eps 1e-8 |
| Gamma | 0.95 |
| Loss | Huber (`smooth_l1_loss`) |
| Grad clip | global norm 10.0 (norm returned in the update record) |
| Replay | per-node ring buffer, capacity 40000 transitions |
| Batch | 32, uniform sample with the node's own RNG |
| Target sync | hard copy every 200 optimizer steps (`TARGET_EVERY`) |
| Update schedule | after each learning step if `lr.n >= warmup*8 = 800` stored transitions and `learn_steps % train_every(1) == 0`; one gradient step per env step |
| Data augmentation | each real transition stored under 8 compass symmetries (4 rotations × E/W reflection); goal-offset and per-direction features are transformed, reward/done unchanged. So replay `n` grows 8 per env step and the warm-up is reached after ~100 env steps |
| Versioning | `version` +1 per gradient step and per `install_params` |

Acting uses a published read-only snapshot (`_published`), so the Q forward pass is independent of the training step.

## 4. Observation space

`nav-terrain-v1`, 13 float32, `world.OBS_SCHEMA` (source: `world.py::observe`). Built only from the node's own cell, goal and terrain within 3 cells; the node never receives a global terrain array.

| Name | Shape | Range | Normalization | Meaning |
|---|---|---|---|---|
| goal_dx | 1 | [-1,1] | clip((gx-x)/8) | east(+)/west(-) offset to goal |
| goal_dy | 1 | [-1,1] | clip((gy-y)/8) | south(+)/north(-) offset to goal |
| goal_dist | 1 | [0,1] | clip(euclid/12) | cells to goal |
| slope_N/E/S/W | 4 | [-2,2] | clip(Δz/cell_m/MAX_SLOPE) | rise of next cell in that direction; >1 = move rejected; 2.0 = map edge |
| ahead_N/E/S/W | 4 | [-2,2] | clip((mean(z[+2],z[+3]) − z0)/(2.5·cell_m·MAX_SLOPE)) | look-ahead gradient; 2.0 if next cell is off-map |
| roughness | 1 | [0,1] | clip(std(3×3 elevations)/50 m) | local relief |
| clearance | 1 | [-1,1] | clip((drone_alt − max elev in 5×5)/agl_m) | airframe height above highest ground within 2 cells |

`SCHEMA_SHA` = sha256 of `"nav-terrain-v1:" + name:normalization` string; used in skill compatibility.

## 5. Terrain representation

`NavWorld` (world.py) wraps `archipelago_sim.terrain.Terrain.generate(size=24, cell_m=100, seed, relief_m=500, agl_m=80)`: a deterministic procedural heightmap, style `classic` (elevation 0–500 m per 100 m cell, median neighbouring slope about 0.3–0.5, ridges well above the 80 m AGL flight height). Drone altitude = ground elevation + `agl_m` at its own cell ("terrain-following"). Terrain affects the node (a) through its observation (slopes, look-ahead, roughness, clearance), (b) through the safety controller (steep faces rejected), and (c) through the RF model (line-of-sight). Nodes never read the array; only `NavWorld.observe/step` do.

## 6. Action space

`nav-act-v1`: Discrete(4) = N, E, S, W (`DELTA = ((0,-1),(1,0),(0,1),(-1,0))`), one cell (100 m) per step. The flight safety controller (`NavWorld.step`) rejects a move that (in order) leaves the map (`map_edge`), leaves the node's geofence (`geofence`), or has |slope| > `MAX_SLOPE` = 1.0 (`too_steep`). On rejection the node stays and takes the invalid penalty. Geofence = the node's operating `area` box, else a disk of `home_radius` (default 4) around home; **no geofence during a mission** (`fence=None`). Mission autopilot exception: with `start_mission(..., autopilot=True)` the action is the first step of the planner's BFS path (`NavWorld.route(pos, target, 1)`); the Q-values are still computed and logged, no experience is stored, no training occurs, and the decision is tagged `selection_method="mission_autopilot"`.

## 7. Reward function

`rew-nav-v1`; per step the sum of:

| Term | Value |
|---|---|
| progress | `+0.5 · (d_prev − d_new)` (euclidean cell distance to goal; only on executed moves) |
| step | `−0.02` every step |
| invalid | `−0.3` on a rejected move |
| slope | `−0.3 · max(0, |slope|/1.0 − 0.6)` on executed moves |
| goal | `+5.0` on arrival (terminal) |

Components are stored per decision (`reward_components`).

## 8. Local learning lifecycle

1. Spawn: baseline eval of the untrained policy on the node's private eval set (`base_eval`); learning disabled (ε = `eps_eval` 0.02).
2. `set_learning(True)`: ε(t) = max(`eps_min` 0.05, 1 − `learn_steps`/`eps_decay` 1500) while the policy is self-trained; `eps_adapt` 0.1 once the active skill is PEER_RECEIVED or LOCALLY_DERIVED.
3. Episodes: new goal sampled in the node's home region (`feasible_goal`: 3..7 cells Manhattan, legal path ≤ m+2); episode ends on goal or `max_ep_steps` 30 (mission legs: `mission_max_steps` 40).
4. Every `eval_every`=250 learning steps: greedy evaluation on the 40-episode eval set (`eval_episodes`, max 30 steps each); qualify (section 14) or derive (section 18).
5. `set_learning(False)` stops experience storage/training; the policy stays usable.

## 9. Decision trace system

One record per node per tick (`decisions/<node>.jsonl`). Fields (node.py `_act`):

- Identity/time: `decision_id` (`node-3-d000042`), `sim_time_s`, `step`, `node_step`, `episode_id`, `node_id`
- State: `position`, `elevation_m`, `battery`, `goal`, `mission`
- Inputs: `observation_summary` (named), `observation` (vector), `terrain_features` (non-goal features)
- Network: `network_context` (peer → link state), `reachable_peers`
- Policy: `active_policy_id`, `active_skill_id/origin/version/source_peer`, `policy_diverged_from_skill`
- Output: `raw_policy_output.q_values`, `action_distribution` (ε-greedy probabilities), `greedy_action`, `selected_action(_index)`, `action_confidence`, `q_margin`, `exploration_vs_exploitation` (`explore|exploit|scripted`), `selection_method` (`greedy_argmax_q|epsilon_random|mission_autopilot`), `epsilon`
- `attribution`: `{versus, top[3]: {feature, value, contribution}}`
- Outcome: `executed {rejected, slope}`, `reward_after_action`, `reward_components`, `next_position`, `reached_goal`, `next_state_summary`
- Learning: `experience_recorded`, `training_update_triggered`, `training_event_id`, `policy_version_before/after`
- `reason_codes`: GREEDY_Q / EXPLORATORY_RANDOM_ACTION / MISSION_AUTOPILOT, MOVE_REJECTED_<REASON>, LEARNING_DISABLED, ISOLATED

Storage: JSONL under the run dir: `decisions/<node>.jsonl`, `policy_updates/<node>.jsonl`, `events.jsonl`, `skills/*.skill`, `metrics.json`, `report.json`. Policy update records (`add_update`): `training_event_id, node_id, episode, step, node_step, decision_id, batch_size, replay_size, loss, grad_norm, q_mean, td_abs_mean, target_synced, policy_version_before/after, experience_count, reward_window, success_window, policy_id_after, policy_hash_after, active_skill_id, n_neighbors`.

Queries (`Store`, work live or after `Store.load(run_dir)`): `get_decisions(node)`, `get_recent_decisions(node, n=20)`, `get_decision(decision_id)`, `get_policy_updates(node)`, `get_skill_lineage(skill_id)` (ancestors root-first, then children, each with holders), `get_events(type, node)`.

CLI:

```
.venv/Scripts/python.exe scripts/swarm_experiment.py inspect decisions --run runs/swarm-exp --node node-3 --last 20 --explain
```
(other `inspect` targets: `decision --id`, `updates --node`, `lineage --id`, `events --type`, `metrics`.)

**What explanations can claim** (`explain.py`): only numbers present in the record: Q-values, chosen action and method, ε/probability, terrain features toward the chosen direction, goal offset, reward components, whether a move was rejected, whether an update ran. **Attribution**: for Q_a − Q_b (a = chosen, b = runner-up or greedy), `contribution_i = x_i · ∂(Q_a−Q_b)/∂x_i` using the local ReLU linearization of the 13→64→4 net (gradient `W1·(relu'(z)⊙(W2[:,a]−W2[:,b]))`). It is a first-order input×gradient share of the learned function at that observation, computed with the published weights at decision time. **It cannot claim** causation, intent, "understanding", that a feature is "why" in a counterfactual sense (it is local and linear; ReLU kinks and feature interactions are ignored), or anything about the true terrain beyond the 13 inputs.

## 10. Policy versioning

`policy_id = <node>-policy-v<version:04d>`; `version` increments on every gradient step and on skill install. `policy_hash` = sha256 of the numpy params (`params_sha256`). `SKILL_ACTIVATED` records `policy_version_before/after`. Each decision records version before/after and `policy_diverged_from_skill` (current hash ≠ the active skill's `training.params_sha256`). Training records carry `policy_hash_after`. Installing params resets the optimizer and syncs the target net.

## 11. Terrain/RF model

`rf.py`, `RFConfig` defaults: freq 2400 MHz, tx 14 dBm, noise −95 dBm, SNR required 10 dB, UP margin 3 dB, obstruction base 8 dB + 0.2 dB/m, cap 60 dB, max bandwidth 250 kbps (full at margin ≥ 12 dB), LOS sample step 0.5 cell, hysteresis 1.5 dB.

- 3D distance d = √(horizontal² + Δaltitude²), min 1 m; altitude = ground + 80 m AGL at each endpoint.
- `PL = 32.44 + 20·log10(d_km) + 20·log10(f_MHz) + obstruction`; `RSSI = tx − PL`; `SNR = RSSI − noise`; `margin = SNR − 10`.
- LOS: sample the straight 3D line every 0.5 cell with bilinear ground elevation; `depth` = max (ground − line height). LOS if depth ≤ 0; else `obstruction = min(60, 8 + 0.2·depth)`.
- State: UP margin ≥ 3; DEGRADED 0 ≤ margin < 3; DOWN margin < 0. `quality = clamp(margin/12, 0, 1)`; bandwidth = 0 if DOWN else `250·max(quality, 0.05)` kbps.
- Hysteresis (applied by `Network`, using the previous state): entering a better state needs ±1.5 dB extra margin than staying.
- Pure function of positions and terrain: deterministic.
- Simplifications: no diffraction/Fresnel/multipath/fading/antenna patterns; obstruction is a linear function of the worst single-point depth; no interference between links; symmetric links.

## 12. Dynamic network graph

`Network.update` each tick recomputes all pairwise links from current node positions and emits `RF_LINK_UP/DEGRADED/DOWN` when a link's state has differed from the last announced state for `EVENT_DEBOUNCE_TICKS` (5) consecutive ticks (the link table itself is instantaneous, and `neighbors()` always reflects it). Nodes likewise announce `PEER_DISCOVERED/PEER_LOST` only after `peer_debounce` (5) ticks. Nodes see a `NetPort` exposing `neighbors()` (non-DOWN links only, with state/quality/bandwidth/distance), `send`, `budget_bytes`, `recv`. Messages sent in tick t arrive in t+1.

| Message kind | UP | DEGRADED | DOWN |
|---|---|---|---|
| PEER_SUMMARY | ✔ | ✔ | ✘ |
| SKILL_ADVERT | ✔ | ✔ | ✘ |
| SKILL_REQUEST | ✔ | ✔ | ✘ |
| SKILL_ACK | ✔ | ✔ | ✘ |
| SKILL_CHUNK | ✔ | ✘ | ✘ |

No routing and no relaying of messages. Multi-hop spread happens only because an intermediate node installs a skill and then advertises it itself. Blocked sends are counted per source (`net.stats`).

## 13. Definition of a skill

`Skill` (skills.py): frozen snapshot of the policy weights (`param-map-v1`: w1, b1, w2, b2, float32) + manifest. Manifest: `skill_id` (`terrain-nav-v<ver>@<node>`), `skill_type="terrain-nav"`, `version`, `origin_node_id`, `origin_type`, `parent_skill_id`, `derived_from_node_id`, `created_step`, `evaluation`, `training`, `compat`, `observation_schema`, `action_schema`, `action_names`. `evaluation` = greedy rollout stats on the creator's eval set (`success_rate, mean_return, mean_steps, episodes, max_steps, eval_set, baseline_success_rate`). `training` = policy id/version, params sha, updates, experience count, episodes, algorithm `double-dqn`, reward id. `compat` = `obs_dim 13, hidden 64, n_actions 4, schema_sha256, reward_id, param_map`.

Wire/disk format: 4-byte big-endian manifest length, manifest JSON (sorted keys, includes `content_hash`), npz weights (`allow_pickle=False`). `content_hash` = sha256(canonical manifest without hash + weight bytes). Max artifact 1 MiB. Saved to `<run>/skills/<skill_id>__<node>.skill`. Artifacts are immutable.

## 14. Skill qualification

At each evaluation (`_maybe_qualify`, for nodes whose active policy is self-trained): evaluate greedily on the node's eval set (40 episodes). Required success = `max(0.5, base_eval + 0.3)` for the first skill; for later ones `max(0.5, best held SELF_LEARNED success + 0.1)`. Emits `SKILL_EVALUATED(purpose=qualification)`; if passed, `SKILL_CANDIDATE_CREATED` then `SKILL_CREATED`, registers as active SELF_LEARNED, saves the file. The eval set is the creator's own home region, so the claim is "works in the creator's region".

## 15. Skill registry

`SkillRegistry` (node-local): `entries` (skill_id → `RegistryEntry{skill, local_state, source_peer, installed_step, local_eval}`), `active_id`. `list_local_skills`, `has(content_hash)`, `add` (refuses duplicate `skill_id`), `advertisement()` (metadata + `size_bytes`, no weights), `counts()`. `Store.skill_meta` is a telemetry mirror, not canonical, and nodes never read it.

## 16. Sharing protocol

1. **Advert**: every `advert_period` (10) ticks (phase-shifted per node) a node with skills sends `SKILL_ADVERT{skills[...]}` to each non-DOWN neighbour. Emits `SKILL_ADVERTISED` once per (peer, hash).
2. **Request** (`_request_phase`, one inbound transfer at a time): for a neighbour's advert, skip if already held (hash), in cooldown, `compat` ≠ mine, or advertised success < my last eval success + `request_margin` 0.1. Sends `SKILL_REQUEST{sid, skill_id, content_hash}`; emits `SKILL_REQUESTED`.
3. **Stream**: sender (one outbound per peer) serialises the artifact and sends `SKILL_CHUNK{sid, offset, total, data}` each tick up to `budget = bandwidth_kbps·1000/8·dt` bytes (dt = 0.1 s; at 250 kbps ≈ 3125 B/tick). Budget is 0 unless the link is UP.
4. **Validate** (receiver, when all bytes arrived): parse, finite weights, hash matches content, hash equals the advertised one, `check_compat` (header equal, tensor shapes).
5. **Install**: registry add as PEER_RECEIVED, `SKILL_INSTALLED`, evaluate on own eval set, compare with current policy (section 18).
6. **Ack**: `SKILL_ACK{ok}`; sender then emits `SKILL_TRANSFER_COMPLETED(side=sender)`.
7. **Failures** (`SKILL_TRANSFER_FAILED`): sender `link_not_up` (budget 0 for more than `stall_limit` 5 ticks) or `ack_timeout` (> 15 ticks after last chunk); receiver `no_data_received` (no progress for > 10 ticks) or `validation: …`. Receiver failures set a `request_cooldown` of 30 ticks on that content hash. Chunks out of order or from a wrong `sid` are ignored.

## 17. RF-gated transfer

Only an UP link carries chunks; DEGRADED links carry adverts/requests/acks but never artifacts. Transfer time scales with link bandwidth (margin-dependent). A link dropping mid-transfer stalls the stream; the transfer fails after the stall limit and is retried after cooldown from the start. No resume.

## 18. Adaptation and derivation

On install: evaluate the received skill (`local_eval`) and the node's current policy on the node's own eval set. Activate (`install_params`: load weights, sync target, reset optimizer, version +1; emits `SKILL_ACTIVATED` with the reason numbers) only if candidate success ≥ current success + `act_margin` 0.1. Otherwise it stays installed but inactive.

An active PEER_RECEIVED/LOCALLY_DERIVED policy continues training if learning is enabled (ε = 0.1). At each evaluation `_maybe_derive`: derive if ≥ `adapt_min_updates` 300 gradient steps since activation, the policy hash has diverged from the parent, success ≥ parent's local success, and mean return ≥ parent's + `derive_return_gain` 0.1. `SKILL_DERIVED` creates a new LOCALLY_DERIVED artifact (version `<parent>.<k>`, `parent_skill_id`, `derived_from_node_id` = parent's origin node), which becomes active.

## 19. Provenance

| State | Meaning | Where |
|---|---|---|
| SELF_LEARNED | qualified from this node's own training | artifact `origin_type` and local state |
| PEER_RECEIVED | installed from a peer over RF | local state only (`source_peer` recorded); artifact keeps the creator's `origin_type` |
| LOCALLY_DERIVED | adapted from a held skill and re-qualified | new artifact, `origin_type` and local state |

`metrics()` counts `self_learned_skills / received_skills / derived_skills` per node.

## 20. Observation vs capability sharing

- **Observation sharing**: `PEER_SUMMARY` (position, policy_version, success_rate, rolling_reward) every `summary_period` 20 ticks. Informational only: stored in the peer view, never used to change a policy.
- **Capability sharing**: `SKILL_ADVERT`, `SKILL_REQUEST`, `SKILL_CHUNK`, `SKILL_ACK` move weights.
- Node counters: `peer_summaries_sent/received`, `skill_advertisements`, `skill_adverts_received`, `skill_requests`, `skill_requests_received`, `skill_transfers_sent`, `skill_transfers_received`, `skill_transfer_failures`, plus `decision_count`. Network-level: `network_messages[src]["<KIND>_sent|_blocked"]`.
- Neither path shares raw experience, replay data or terrain.

## 21. Metrics

`Swarm.metrics()` keys: `tick, sim_time_s, nodes[], links[], groups[], network_messages, skills[]`.
- `nodes[]`: `node_id, tick, episode, step, position, battery, learning_enabled, experience_count, policy_update_count, policy_version, policy_id, policy_hash, reward, rolling_reward, success_rate, last_eval, self_learned_skills, received_skills, derived_skills, active_skill_id, decision_count, reachable_peers, rf_link_count`, plus the transfer/summary counters in section 20.
- `links[]`: `node_a, node_b, distance_m, terrain_los, obstruction_depth_m, obstruction_db, path_loss_db, rssi_dbm, snr_db, margin_db, link_quality, bandwidth_kbps, state`.
- `groups`: connected components over non-DOWN links (bookkeeping view only). `skills[]`: `skill_id, version, origin_node, provenance, parent, derived_from_node, evaluation, content_hash, current_holders[{node, local_state, source_peer, active}]`.
- `Swarm.close()` writes `metrics.json`.

## 22. Events

`events.jsonl`; `emit` rejects types outside `EVENT_TYPES`. Record: `seq, type, tick, node, …fields`. Decisions and policy updates are **separate streams** (volume), not events.

| Event | Meaning |
|---|---|
| NODE_SPAWNED | node created; initial policy hash, baseline eval, seeds |
| LOCAL_LEARNING_STARTED / STOPPED | learning toggled |
| NODE_MISSION_STARTED / COMPLETED | transit mission begun (waypoints) / target reached |
| SKILL_EVALUATED | an evaluation (`purpose` = qualification, adaptation, received) and whether it passed |
| SKILL_CANDIDATE_CREATED | qualification passed, before registration |
| SKILL_CREATED | new SELF_LEARNED skill |
| SKILL_ACTIVATED | skill weights installed as the policy, with reason |
| SKILL_DERIVED | new LOCALLY_DERIVED skill with parent |
| RF_LINK_UP / DEGRADED / DOWN | link state change (pair, previous state, RF numbers) |
| PEER_DISCOVERED / PEER_LOST | neighbour became / ceased to be non-DOWN |
| SKILL_ADVERTISED | advert of a skill to a peer (first time per hash) |
| SKILL_REQUESTED | receiver asked for a skill |
| SKILL_TRANSFER_STARTED / COMPLETED / FAILED | transfer lifecycle (`side` sender/receiver) |
| SKILL_INSTALLED | validated artifact registered as PEER_RECEIVED |

## 23. Reproducible experiment

```
.venv/Scripts/python.exe scripts/swarm_experiment.py experiment --out runs/swarm-exp
```
(`--seed` default 0; terrain seed 12 fixed in `SCENARIO`.) Prints `{"ok": bool, "checks": {...}}` and exits 0 only if all checks pass. The `checks` keys: `T0_equal_initial_policies, T4_terrain_partition, T5_no_cross_cluster_link_while_isolated, T6_policies_diverged, T8_skill_earned, T9_skill_local_before_reconnect, T10_topology_changed, T11_peers_discovered, T12_T13_skill_transferred_and_activated, T16_derived_with_lineage`. Output dir gets `events.jsonl, decisions/, policy_updates/, skills/, metrics.json, report.json` (`report.json` is written only when the run completes).

Phases: 1 spawn, 2 fragmentation, 3 isolated learning (3000 ticks; east stops at 300), 4 skill created (≤4000 ticks), 5 skill stays local (150 ticks), 6 topology change (creator autopilots to the crest), 7 transfer (≤300 ticks), 8 adaptation + derivation (≤5000 ticks).

**Result of the run documented here** (seed 0, about 28 s on a laptop CPU, deterministic: two runs produce byte-identical `events.jsonl`, `decisions/*.jsonl`, `policy_updates/*.jsonl`):

```
[1_spawn]  identical_initial_policy=true  policy_hash=6a3c260c50ab  nodes=5
[2_fragmentation] groups=[[node-0,node-1,node-2],[node-3,node-4]] cross_cluster_links=[]
[3_isolated_learning] t=3001 distinct_policies=5 cross_cluster_link_ticks=0
    updates: node-0..2 = 2901, node-3..4 = 201;  last_eval_success: 0.40 0.40 0.575 | 0.05 0.05
[4_skill_created] terrain-nav-v1@node-0 SELF_LEARNED success 0.50 (spawn baseline 0.025) created_tick=1001
[5_skill_stays_local] east_nodes_holding_skill=[]  cross_cluster_link_ticks=0
[6_topology_change] relay node-0 autopilots to (13,4) in 28 ticks; node-0-node-3 DEGRADED; PEER_DISCOVERED node-0<->node-3
[7_transfer] node-3 installs three skills from node-0 (v1@node-2, v1.1@node-1, v1@node-0); two transfers
    fail first (link_not_up / no_data_received) and are retried; node-3 ACTIVATES terrain-nav-v1@node-0
    (local success 0.20 vs own policy 0.10, required margin 0.10)
[8_adaptation_derivation] node-3 trains on, derives terrain-nav-v1.2@node-3 (parent terrain-nav-v1@node-0,
    derived_from_node node-0)   lineage: terrain-nav-v1@node-0 -> terrain-nav-v1.2@node-3
{"ok": true, "checks": {T0, T4, T5, T6, T8, T9, T10, T11, T12_T13, T16 all true}}
```

Event counts of this run: 272 RF_LINK_* (131 UP, 19 DEGRADED, 122 DOWN; links inside a cluster flap as nodes wander), 461 PEER_DISCOVERED/LOST (about 3,000 before the 5-tick debounce), 55 SKILL_EVALUATED, 35 SKILL_ADVERTISED, 13 SKILL_REQUESTED, 11 SKILL_INSTALLED, 4 SKILL_ACTIVATED, 4 SKILL_TRANSFER_FAILED, 3 SKILL_DERIVED, 2 SKILL_CREATED (node-0 and node-2 each earned a `terrain-nav-v1`; ids carry `@node`). The numbers vary with any change to constants or seeds; treat them as this build's output, not a benchmark.

**Read the margins honestly.** The east activation margin was exactly the required 0.10 on a 40-episode eval set (0.20 vs 0.10, i.e. 8 vs 4 successes); that is weak evidence that the skill is better, not proof. The east nodes were deliberately given a 300-step learning budget so that a west node would earn the first skill (scenario input, section 28). The experiment is one seed.

Inspect the result:

```
.venv/Scripts/python.exe scripts/swarm_experiment.py inspect decisions --run runs/swarm-exp --node node-3 --last 5 --explain
.venv/Scripts/python.exe scripts/swarm_experiment.py inspect lineage   --run runs/swarm-exp --id "terrain-nav-v1.2@node-3"
.venv/Scripts/python.exe scripts/swarm_experiment.py inspect events    --run runs/swarm-exp --type SKILL_ACTIVATED
.venv/Scripts/python.exe scripts/swarm_experiment.py inspect updates   --run runs/swarm-exp --node node-0 --last 3
.venv/Scripts/python.exe scripts/swarm_experiment.py inspect metrics   --run runs/swarm-exp
```

Example `--explain` output (real, node-3 after activation):

```
node-3 step 3685 selected S via greedy_argmax_q (epsilon=0.100, p=0.93); policy node-3-policy-v0651, skill terrain-nav-v1@node-0.
Q-values: E=+1.12, N=+0.58, S=+1.25, W=+1.03; greedy=S.
Terrain toward S: slope/limit=-1.00, look-ahead=-0.37; local roughness=1.00, clearance=-0.49.
Goal offset (dx,dy)=(+1.0,+4.0) cells.
Largest input contributions to Q(S) - Q(E): goal_dy=+0.50 (+0.30), roughness=+1.00 (+0.25), slope_N=-0.88 (+0.13)
Outcome: reward -0.32 (invalid=-0.30, step=-0.02); move rejected: too_steep. experience_recorded=True, update=True (policy v651->v652).
```
(The policy chose a move the safety controller then rejected: the explanation reports that, it does not excuse it. The learner is weak: about 50% eval success.)

## 24. Tests

`.venv/Scripts/python.exe -m pytest tests/swarm -q` gives **35 passed** (about 30 s; needs torch, skipped otherwise via `importorskip` in `test_swarm.py`). `scripts/check.sh` lists `tests/swarm` in the `py-live` suites. Not run in this session: the rest of the repository's suites (`make check-fast/integration`), mypy, the web build, Docker tests.

| Test (file) | Guarantee |
|---|---|
| test_independent_learners_do_not_share_state (test_swarm) | separate nets/optimizer/replay/registry; equal initial hashes; training A leaves B and C bit-identical |
| test_learner_state_is_independent (test_learner_world) | same, at learner level |
| test_policies_diverge_on_different_experience | different experience gives different weights |
| test_terrain_changes_observation_and_schema_is_respected, test_observation_shape_range_and_variation, test_observation_dtype_is_float32 | terrain features change with position; 13-D within declared ranges; map edge = 2.0 |
| test_rejected_moves_follow_terrain | steep faces are rejected and penalised |
| test_ridge_obstructs_link_and_removing_it_restores, test_rf_ridge_blocks_clear_los | a ridge between two airframes drops the link; removing it restores it |
| test_distance_degrades_link_monotonically, test_rf_distance_degrades_up_degraded_down | margin falls monotonically with distance; UP, DEGRADED, DOWN |
| test_hysteresis_debounces | state changes need extra margin |
| test_peer_visibility_and_send_follow_rf_graph, test_netport_visibility_and_gating | a node sees/sends only to non-DOWN neighbours; DEGRADED carries no chunks; event debounce |
| test_decision_trace_complete_and_consistent_with_policy, test_decision_trace_fields_and_greedy_consistency | every decision has the full field set; logged Q-values equal the net's forward pass on the logged observation; greedy action = argmax |
| test_attribution_matches_numerical_gradient, test_attribute_sums_to_first_order_difference, test_explain_only_uses_record_values | attribution equals input times finite-difference gradient; explanations use only record values |
| test_policy_versions_track_updates, test_policy_versioning_and_training_without_peers | one version per update, contiguous, matching decisions; training with zero peers |
| test_learning_continues_with_zero_reachable_peers | isolated nodes keep training and send nothing |
| test_skill_not_created_without_qualification, test_skill_requires_qualification | no skill when the threshold is unreachable or when never evaluated |
| test_skill_created_from_real_policy_state_and_roundtrips, test_skill_roundtrip_and_tamper | candidate precedes creation; skill carries real weights; save/load identical; tampered/truncated artifacts rejected |
| test_dihedral_symmetries_are_consistent | augmentation maps are consistent with the action map |
| test_transfer_is_impossible_without_a_link_then_succeeds_when_connected, test_rf_gated_transfer_and_lineage | no advert/request/transfer without a link; after moving into range: advertise, request, start, install, provenance PEER_RECEIVED |
| test_degraded_link_carries_metadata_but_not_the_artifact | metadata passes, artifact does not, failure is reported |
| test_link_loss_mid_transfer_fails_the_transfer | slow transfer in flight, link lost: `SKILL_TRANSFER_FAILED`, nothing installed |
| test_received_skill_stays_learnable_and_derived_copy_is_independent | activated peer skill keeps training; derived skill has parent/`derived_from_node`; sender artifact, registry and learner untouched; lineage query |
| test_observation_and_skill_sharing_are_separate_counters | summary vs skill counters/messages are distinct |
| test_runs_are_deterministic | same seed gives identical policies and decision records |
| test_full_experiment_reproduces_every_phase | all 10 experiment checks pass end-to-end and the run directory reloads |

Tests that build skill artifacts by hand (`give_skill`) do so to test transport and provenance only; they do not test qualification.

## 25. Centralized components

Simulator/bookkeeping, not agents:
- `Swarm`: owns world, network, nodes; advances ticks; `groups()`, `metrics()`. Makes no agent decisions.
- `Network`: computes the RF link table from all positions, delivers/gates messages, keeps stats. Nodes see it only via `NetPort`.
- `Store`: telemetry sink and query API; nodes write, never read.
- `NavWorld`: terrain, physics (`step`), observation function; **task generation**: `feasible_goal` (3..7 cells Manhattan, BFS legal path ≤ m+2) and `path_len`/`_bfs` (BFS over legal moves, used only to sample feasible goals and eval sets); **mission planner**: `route()` returns waypoints along the BFS shortest legal path every 3 cells, used for missions and the autopilot.

## 26. Decentralized components

Per node: `NodeLearner` (weights, replay, optimizer, RNGs), `SkillRegistry`, eval set and evaluation, qualification and derivation decisions, exploration, goal sampling, peer view, advert/request/stream/validate/install/activate logic, decision trace production. Decisions to request, install and activate depend only on the node's own evaluation and what arrives through its `NetPort`.

## 27. Known simplifications

- RF is an approximation (section 11), not an EM/RF simulator.
- 2D grid world (24×24, 100 m cells) with terrain-following altitude; no 3D dynamics or collision beyond slope/geofence rules.
- Small DQN (1156 parameters).
- Goal-conditioned local navigation, not exploration or mapping; no global map in a node.
- Local-feature policies generalize poorly across terrain regions, which limits skill reuse: a skill's `evaluation` is on the creator's region, and a receiver activates it only if it beats its own policy on its own region.
- No multi-hop routing; propagation is by install + re-advertise.
- Everything runs in one Python process with a synchronous tick (not separate OS processes); message latency is a fixed one tick.
- Batteries are bookkeeping only: drain `0.00005/step + 0.000001/m climbed`, not observed, not rewarded, never constrain behaviour.
- Link and peer events are debounced (5 ticks), so event timestamps lag the link table by up to 5 ticks.
- The learner is weak (about 0.4-0.6 greedy success on its own region after about 3000 steps) and its skills transfer only partially between regions.

## 28. Scripted/mocked components

- `experiment.SCENARIO`: terrain seed 12; homes `node-0 (2,8)`, `node-1 (6,12)`, `node-2 (5,9)`, `node-3 (16,5)`, `node-4 (17,7)`; geofence boxes west `(1,7,7,13)`, east `(14,20,3,10)` (chosen by an RF scan so no cell pair across the boxes has a non-DOWN link); west = nodes 0–2, east = nodes 3–4; `relay="creator"`; `crest=(13,4)`; `home_radius 2`; `isolated_learning_ticks 3000`; `east_learning_budget 300` (east nodes stop learning at tick 300 while west continues, so a west node earns the first skill); `max_skill_ticks 4000`, `max_mission_ticks 400`, `max_adapt_ticks 5000`; seed 0.
- The creator's relay flight is a **scripted mission autopilot** (BFS path; the learned policy does not fly it; `hold=True` then parks it on the vantage cell and stops its training so the link is stable). A learned-policy flight along planner waypoints (`start_mission(route=...)`) exists but did not reliably cross the terrain, so the experiment does not use it.
- East learning budget (300 steps) and the choice of which cluster learns first are scenario inputs; they decide who is sender and receiver. Which node qualifies first is not scripted (it was node-0 for this seed).
- Task goals come from the BFS-based generator; eval sets are sampled by the same generator.
- Reconnection is caused by the relay's flight to the crest, not injected; skills, links and transfers are not injected.

## 29. Supported claims

- Each node has its own weights, replay, optimizer, RNG streams; initial weights are identical, later weights diverge (checked in T0/T6 when the experiment runs).
- Links are computed from positions and terrain; ridges can drop a link; nodes cannot message across a DOWN link.
- A skill is a hash-verified artifact; a corrupted or incompatible artifact is rejected at install.
- Transfers are bandwidth-limited, UP-only for chunks, and can fail and be retried after cooldown.
- A receiver activates a peer skill only if it beats its own policy on its own eval set.
- Every executed action has a stored trace with Q-values, selection method, reward terms and input×gradient attribution.
- Lineage and provenance are recorded and queryable.

## 30. Unsupported claims

- That the experiment generalizes: one seed, one terrain, hand-chosen geofence boxes and budgets (section 28).
- That a transferred skill is *better* in general: the observed activation margin was the minimum allowed.
- That a skill generalizes beyond the creator's region, or that reuse always helps.
- That attributions explain causes, intent or "understanding".
- Real-world RF fidelity, real-time/embedded performance, multi-process or networked operation.
- Multi-hop routing, consensus, or federated averaging between nodes (none exist here).
- That this is integrated into the live system: **`archipelago_swarm` is not wired into the coordinator/noderuntime stack.**

Existing narrative claims that are inaccurate or need qualification:
- The pre-existing coordinator builds connectivity as `all_pairs` of living nodes minus scripted fault cuts (`services/coordinator/archipelago_coordinator/runner.py::_allowed_links`, ~line 302–308); it is not terrain- or RF-derived.
- The older `packages/learning` peer exchange (`peer.py`: `offer`, `encode/decode`) works on whole-network parameter sets (replace, or an `alpha ≤ 0.5` blend in mixing mode) with no skill/artifact/provenance concept. (Read function signatures and the blend line only; not audited in full.)
- `apps/web/src/demoScriptController.ts` narrates a surviving "capability" and `Lineage.tsx` renders "Capability lineage" from the old stack's policy/offer events; the web app and the Remotion/brand-kit assets do not read `archipelago_swarm` output, so anything they show about skills, partitions or transfers is scripted/illustrative with respect to this backend. The README line about nodes sharing learned capabilities and validating them before adoption is true of the old parameter-exchange stack (whole-network weights), not of a skill abstraction; the README already says topologies in marketing graphics are illustrative.
- Terrain in the older sim previously only occluded sensor crops (`terrain.py` docstring: hidden terrain used for the simulator's visibility physics only); it did not shape links or the learned policy's inputs.

## 31. Important files

| File | Purpose |
|---|---|
| packages/swarm/archipelago_swarm/world.py | `NavWorld`: terrain nav task, obs schema, step/reward, BFS task generation, route |
| packages/swarm/archipelago_swarm/rf.py | RF link model, `RFConfig`, hysteresis |
| packages/swarm/archipelago_swarm/network.py | `Network`, `NetPort`, message gating, bandwidth budget |
| packages/swarm/archipelago_swarm/learner.py | `NodeLearner` (double DQN, symmetry augmentation, Huber, clip, install) |
| packages/swarm/archipelago_swarm/skills.py | `Skill` artifact, compat check, `SkillRegistry`, `evaluate_params` |
| packages/swarm/archipelago_swarm/node.py | `SwarmNode`, `NodeConfig`: act/learn/skills/network logic |
| packages/swarm/archipelago_swarm/swarm.py | `Swarm`: tick loop, groups, metrics |
| packages/swarm/archipelago_swarm/store.py | `Store`: events/decisions/updates JSONL + query API, `EVENT_TYPES` |
| packages/swarm/archipelago_swarm/explain.py | input×gradient `attribute`, `explain` text |
| packages/swarm/archipelago_swarm/experiment.py | `SCENARIO`, `run_experiment`, `checks` |
| packages/swarm/archipelago_swarm/__main__.py | CLI: `experiment`, `inspect` |
| scripts/swarm_experiment.py | path-setup wrapper for the CLI |
| packages/learning/archipelago_learning/torch_dqn.py | reused `TorchLearner` (nets, Adam, replay, target) |
| packages/learning/archipelago_learning/peer.py | reused `params_sha256` (older peer exchange otherwise unused here) |
| packages/sim/archipelago_sim/terrain.py | reused `Terrain.generate`, `drone_alt` |
| tests/swarm/ | unit tests (section 24) |
