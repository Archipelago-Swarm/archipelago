# Budget guard (T10)

No spend has occurred and none is authorized by this branch. Agents must not create cloud resources.

Rules:
1. Prefer an operator-named existing Vultr instance. A new instance needs a written cap in the task card or an operator message (amount, max duration, instance plan).
2. Before any create call, the agent writes the planned resource list and monthly price into the deploy handoff and waits for explicit approval; unattended runs treat missing approval as `blocked`.
3. One instance only. No object storage, load balancer, reserved IP, snapshot or managed service unless listed in the approval (all of these bill separately and persist after the instance is deleted).
4. Set a billing alert in the Vultr and TigerData consoles at 50% and 80% of the cap (operator action).
5. At the end of a session, record the inventory table from `rollback-teardown.md` and the usage figure seen in the console. If it cannot be read, record "spend status unknown".
6. Local packaging and static checks continue when the deployment is blocked.

Cost-saving defaults already in the stack: container CPU/RAM limits, log rotation, no hosted registry (images built on the host), TLS via ACME at no charge.
