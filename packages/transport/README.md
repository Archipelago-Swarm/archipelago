# Transport fault scope (T05)

- Fault injection is **application-level only**: directed link gates, seeded loss, tick-based delay and per-tick bandwidth are simulated inside `Network` (memory). The HTTP peer (`packages/node/peer`) reuses the same gate and validation rules.
- Static manifest (`load_manifest`): `{"nodes": {id: url}, "links": [[src, dst], ...]}`; links are directed.
- Telemetry (`Telemetry`) is a separate bounded channel, not gated by learning links; `send` never blocks, so partitions never block acting.
- **Pending (not done):** real network-fault tests (kernel/netem/packet-level loss, latency, partitions between processes or hosts) and HTTP-level delay/loss schedules.
