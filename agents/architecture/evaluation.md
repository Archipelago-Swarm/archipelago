# Evaluation and honest demo evidence

## Questions

1. Does a peer learning update change recipient behavior and improve held-out performance beyond information sharing alone?
2. Do islands keep acting and learning while their peer graph is disconnected?
3. Does reconnection recover useful knowledge without destroying local policies?
4. What do larger swarms cost in bytes, latency, CPU/RAM and training samples?

## Baseline matrix

| Mode | Decision ownership | Learning transfer |
|---|---|---|
| Rule-based explorer | Local | None; sanity/control |
| Independent DQN | Local per-node policy | None |
| Information-sharing DQN | Local | Same map/status messages as P2P mode; no parameters transferred |
| Archipelago | Local | Same information messages plus validated peer candidates |
| Central online controller | Server receives observations and returns actions | Central model; explicit control-channel dependency |
| Shared-policy CTDE | Local actors with centrally trained policy | Centralized training, decentralized execution |

The first four are required for a learning-transfer claim. A claim against central approaches additionally requires the last two. Do not assume a centrally trained policy fails at inference during a partition: local CTDE actors can continue. For the online central controller, specify the fallback and apply comparable link latency/loss to its sensor/control links. Report the physically different network paths being cut.

## Experimental protocol

Use immutable scenario configs and paired evaluation seeds: initial smoke seeds 100-104, final untouched seeds 200-219, training seeds 0-9. These are starting manifests, not sufficient statistical power by themselves. Never tune on final seeds. Freeze the manifest before final comparisons and retain all failed/negative runs.

Hold total environment transitions, local optimizer update budget, model size, reward, sensor range, topology schedule, peer bandwidth and evaluation duration comparable. Report extra candidate validation cost and bytes. For scaling, run both fixed-total-work and fixed-work-per-node views; label added compute so increased swarm size is not mistaken for free intelligence.

Scenarios: connected; seeded 50% link loss; two-island partition; reconnection; one-node failure; telemetry/DB outage. The demonstration scenario has a 900-tick horizon, split at tick 300, rejoin at 600. Specify which links are affected and keep world dynamics equal across paired modes.

Metrics: coverage fraction, markers discovered/time-to-discovery, episode return, collisions per agent-step, energy use, local training updates, accepted/rejected transfers, peer bytes and staleness, p50/p95 inference latency, simulation real-time factor, recovery time, CPU/RAM. Resilience score can be partition-period coverage gain divided by the matched connected-run gain; report undefined denominators instead of inventing a score.

Controlled transfer test: train a donor on a declared related local task; checkpoint it; compare the same recipient before and after candidate transfer on untouched validation episodes. Include sham/no-transfer and random-update controls. A parameter hash changing proves transfer occurred; it does not prove transfer helped. Record rejected transfers and regression frequency.

Use multiple independent training runs when feasible. Report mean and dispersion plus paired confidence intervals over independent seed/run outcomes; do not treat thousands of correlated ticks as independent samples. If overnight compute only allows five seeds, label the result preliminary and show all values. No target improvement percentage is a shipping gate.

## Reproducibility bundle

Each experiment writes a manifest with commit, container image, locked dependencies, hardware, all seeds, config/reward hashes, mode, clock policy, model/checkpoint hashes, commands, start/end UTC and exit status. Export metrics, events, topology and replay actions from the actual run. Store large files outside Git with immutable hashes and retrievable paths; keep small result summaries in `experiments/reports/`.

Deterministic CPU tests verify reset/step and recorded-action replay. Cross-device PyTorch training is not promised bitwise reproducible. Record deterministic flags and any unsupported operations.

## Presentation

Three-minute sequence: establish local learning -> display split and surviving islands -> reconnect and show transfer decisions -> compare actual outcomes -> state limitations and 3D path. Live and replay modes must be visibly labeled. A scripted fault schedule is acceptable; a scripted winning metric is not.

Remotion may consume generated `metrics.json`, `events.json`, `topology.json` and result figures to make a video. Show the run ID and commit; derive percentages from the exported data. If learning does not outperform baselines, show the resilience mechanism and the negative result candidly.
