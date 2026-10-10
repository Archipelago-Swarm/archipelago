# ADR-0002: Pose.z stays 0 in the shared contract; 3D height is adapter-local

- Status: accepted by integrator A, 2026-10-10 (revisit when T12 proves the adapter)
- Scope: T12 and any 3D adapter

The shared `Pose` contract pins `z` to 0 so the 2D mission, replay and dashboard keep one frozen schema. The 3D adapter reports height through its own `poses3d()` and maps to 2D `Pose` by projecting onto the ground plane for run/event contracts. A contract version bump to carry `z` is deferred until a 3D run must be replayed in the dashboard; it needs a coordinated change to contracts, fixtures and generated TypeScript, so it is not done inside a worker branch.
