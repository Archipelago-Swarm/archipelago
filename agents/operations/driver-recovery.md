# A/B driver recovery

> **Legacy status (ADR-0003/0004):** describes the pre-ledger runner. Reliability: CONDITIONALLY_RELIABLE (needs an awake machine and an open terminal). Planning from `BOARD.md`, the `agent-coordination` branch and the mailbox is superseded by `agents/TASKS.yaml`; replacement is task T20. Do not extend it.

The `driver.py` processes assign and integrate bounded Claude Code runs. Use
`watchdog.py` as their outer process on each computer. It restarts a driver
that exits before the agreed UTC deadline, with 15-second to five-minute
backoff. Each driver also holds an OS lock, so a second updated driver cannot
write the same machine's state. The watchdog records its PID, restart count,
and last exit in `.agent-runtime/watchdog-A.json` or `watchdog-B.json`.

From each computer's **own clean repository root**, after the current direct
driver has stopped and `git pull --ff-only` succeeds:

```powershell
# Computer A
python tools/agents/watchdog.py --machine A --until-utc 2026-10-10T21:00:00Z --max-rounds 10

# Computer B, in its own terminal
python tools/agents/watchdog.py --machine B --until-utc 2026-10-10T21:00:00Z --max-rounds 10
```

For a later run, replace the UTC deadline on **both** computers with the
approved run end. Leave one terminal open per computer; keep the PCs awake.
Do not launch the watchdog beside a direct `driver.py` on the same computer.
During a current worker slice, wait for a checkpoint or report before
switching launchers, or let the direct driver finish the current run.

The B driver now retries the **same** published run if its worker exits before
uploading a report. A likewise resumes its own supervisor if its report is
missing. A holds a new B assignment while B starts its first branch.
Both drivers stop at the deadline or a local `.agent-runtime/STOP` file.
Task branches, handoffs and reports remain the recovery source; the watchdog
does not delete or reset them. Usage-limit waits remain inside `night.py` and
do not switch a subscription to API billing.

Lock marker files remain on disk after a clean stop or crash. Only their live
OS locks prevent another process from starting; file existence alone does
not mean the machine is busy. Do not manually delete them to restart.

The watchdog repairs process exits and transient preflight/network failures.
It cannot restart a powered-off computer or repair missing credentials,
permissions, quota, a dirty main checkout, or an unsafe merge. Those cases
remain blocked with logs or handoffs for an operator. It never takes over the
other machine's assignment or spends on Vultr/TigerData without approval.

If the output goes quiet, read the watchdog JSON and the latest driver output.
An active task also has a remote `agent/<machine>/<run-id>/<task>` branch and
`agents/handoffs/<task>/LATEST.md`. A `review` result is waiting for A's gate
and integration; it is not a stuck Claude session.
