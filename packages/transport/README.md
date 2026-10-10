# Transport fault scope (T05)

- Fault injection is **application-level only**: directed link gates, seeded loss, tick-based delay and per-tick bandwidth are simulated inside `Network` (memory). The HTTP peer (`packages/node/peer`) wraps the same `Network`, so `PeerServer(seed=, loss=, delay=, bandwidth=)` applies the same schedule per request: lost/rejected -> 422, deferred -> 202, delivered -> 200.
- Static manifest (`load_manifest`): `{"nodes": {id: url}, "links": [[src, dst], ...]}`; links are directed. `serve_manifest` binds one server per node; `PeerClient` sends to manifest URLs.
- Telemetry (`Telemetry`) is a separate bounded channel, not gated by learning links; `send` never blocks, so partitions never block acting.
- Reconnect catch-up is **receiver-initiated** over HTTP: `PeerServer.set_links` detects a newly opened inbound link and POSTs `/catchup` to the sender, whose `on_catchup` hook (e.g. `PeerClient.catch_up`) resends only the newest envelope, never a backlog. Detection is only for links changed through `set_links` (application-level gate); the test cuts and restores that gate. A real link/process drop is not detected.
- **Pending (not done):** real network-fault tests (kernel/netem/packet-level loss, latency, partitions between processes or hosts), multi-process tests, automatic detection of real connection loss.
