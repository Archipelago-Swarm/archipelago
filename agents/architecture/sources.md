# Technical references

Reviewed 2026-10-10. These links support tool capabilities; the project architecture and budgets are our decisions. Recheck installed versions before copying commands. Earlier project context was recovered from the project's "Architect P2P AI Stack" discussion; its referenced downloadable long roadmap was not available in this checkout.

- [PettingZoo Parallel API](https://pettingzoo.farama.org/api/parallel/): simultaneous multi-agent observation/action environment interface.
- [gym-pybullet-drones](https://github.com/learnsyslab/gym-pybullet-drones): open-source Python drone simulation candidate; consult its current runtime and build requirements, license and examples when pinning.
- [PX4 Gazebo simulation](https://docs.px4.io/main/en/sim_gazebo_gz/): later open-source flight simulation integration route.
- [TigerData with Grafana](https://www.tigerdata.com/docs/integrations/latest/grafana): Grafana PostgreSQL data source connection.
- [Vultr Docker installation](https://docs.vultr.com/how-to-install-docker-on-ubuntu-2204): Docker hosting on a Vultr Ubuntu instance.
- [Docker Compose in production](https://docs.docker.com/compose/how-tos/production/): production deployment configuration considerations.
- [Claude Code programmatic usage](https://code.claude.com/docs/en/headless): bounded CLI invocation, structured results and error handling.
- [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference): supported flags must be checked against the installed version.
- [Claude Code agent teams](https://code.claude.com/docs/en/agent-teams): optional experimental coordination inside supported sessions; not the cross-computer authority for this project.
- [Claude usage and length limits](https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work): session and weekly allowance constraints; do not promise uninterrupted overnight inference.

The reliable starting deployment is separate bounded worker sessions plus an external supervisor and remote ledger. Optional built-in agent teams may be tested later; their session-local task state does not replace Git handoffs between computers.
