# ADR-0001: 2D-first decentralized learning with provider constraints

- Status: accepted design baseline, subject to human revision
- Date: 2026-10-10
- Scope: initial repository architecture

Start with a synthetic search-and-coverage mission, independent local learners and peer learning exchange. Keep the physics harness centralized and explicitly scoped as simulation infrastructure. Require Vultr for deployed compute, Docker for packaging, and TigerData/TimescaleDB with Grafana for persistent metrics.

Use a small discrete-action DQN first to bound CPU cost and make independent learning observable. Parameter mixing is an experimental baseline with compatibility/validation gates, not an established guarantee of improvement. Preserve independent and information-only controls.

Use one Git-based coding dispatcher on computer A, two isolated worker slots per computer and Markdown handoffs. This favors recoverability and conflict avoidance over unrestricted fan-out. External supervision is an implementation task; it is not activated by these documents.

Favor a gym-pybullet-drones adapter for the first 3D spike, followed by Gazebo/PX4 when flight-stack fidelity is required. Keep 2D and 3D encoders/version identifiers separate. Additional deployment providers and large orchestration frameworks are deferred pending evidence.
