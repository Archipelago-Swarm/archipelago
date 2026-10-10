# Transport fault scope (T05)

- Fault injection is **application-level only**: directed link gates, seeded loss, tick-based delay and per-tick bandwidth are simulated inside `Network` (memory). The HTTP peer (`packages/node/peer`) wraps the same `Network`, so `PeerServer(seed=, loss=, delay=, bandwidth=)` applies the same schedule per request: lost/rejected -> 422, deferred -> 202, delivered -> 200.
- Static manifest (`load_manifest`): `{"nodes": {id: url}, "links": [[src, dst], ...]}`; links are directed. `serve_manifest` binds one server per node; `PeerClient` sends to manifest URLs.
- Telemetry (`Telemetry`) is a separate bounded channel, not gated by learning links; `send` never blocks, so partitions never block acting.
- Reconnect catch-up is **sender-driven**: `PeerClient.catch_up` (and the memory network's reconnect path) resends only the newest envelope, never a backlog. The receiver does not request it and nothing detects the reconnect automatically; the caller decides when to call it. The HTTP test simulates the partition by restarting a server, not by cutting/restoring a gated link.
- **Pending (not done):** real network-fault tests (kernel/netem/packet-level loss, latency, partitions between processes or hosts), multi-process tests, receiver-initiated catch-up request with reconnect detection.
