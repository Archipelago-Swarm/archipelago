"""Cost guard. Pure computation over inventory.json + plan file + spend-start.json.

Formula (all Decimal, USD):
  HOURS_PER_MONTH = 730, SAFETY = 1.25 (applied to every prorated hour count)
  existing instance: monthly = plan monthly_cost (full month, regardless of remaining hours)
  new instance:      hours = max(duration_hours, hours from now to experiment_end)
                     prorated = min(monthly_cost, monthly_cost / 730 * hours * SAFETY)
  projected_monthly   = sum(existing monthly) + sum(new prorated)           limit <= 200
  existing_burn       = sum(monthly/730 * hours(now->experiment_end) * SAFETY) for existing
  spend_so_far        = |balance_now - balance_start| + max(0, pending_now - pending_start)
                        (abs: conservative whichever sign convention the account balance uses)
  projected_cumulative= spend_so_far + existing_burn + sum(new prorated)    limit <= 100
  instance count      = existing + new                                      limit <= 5
Exactly at a limit passes; any cent above fails. Unknown plan price fails closed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

HOURS_PER_MONTH = Decimal(730)
SAFETY = Decimal("1.25")
MAX_INSTANCES = 5
MAX_MONTHLY = Decimal(200)
MAX_CUMULATIVE = Decimal(100)
CENT = Decimal("0.01")

EXIT_OK, EXIT_VIOLATION, EXIT_NOT_APPROVED = 0, 2, 3


class GuardError(Exception):
    """Plan/approval problem (exit 3)."""


def _dt(s: str) -> datetime:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def plan_hash(plan: dict[str, Any]) -> str:
    """sha256 over the canonical JSON of the plan minus approved, plan_hash and expires_at."""
    body = {k: v for k, v in plan.items() if k not in ("approved", "plan_hash", "expires_at")}
    blob = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def check_approval(plan: dict[str, Any], now: datetime) -> None:
    if plan.get("approved") is not True:
        raise GuardError('plan is not approved (needs explicit "approved": true)')
    if not plan.get("plan_hash") or plan["plan_hash"] != plan_hash(plan):
        raise GuardError("plan_hash missing or does not match plan contents")
    exp = plan.get("expires_at")
    if not exp:
        raise GuardError("plan has no expires_at")
    if _dt(str(exp)) <= now:
        raise GuardError("plan approval has expired")


@dataclass
class GuardReport:
    passed: bool
    violations: list[str] = field(default_factory=list)
    costs: dict[str, str] = field(default_factory=dict)
    detail: dict[str, Any] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "violations": self.violations,
            "costs": self.costs,
            "detail": self.detail,
        }


def _q(x: Decimal) -> str:
    return str(x.quantize(CENT))


def evaluate(
    inventory: dict[str, Any], plan: dict[str, Any], start: dict[str, Any], now: datetime
) -> GuardReport:
    check_approval(plan, now)
    prices = {k: Decimal(v["monthly_cost"]) for k, v in inventory.get("plans", {}).items()}
    end = _dt(str(plan["experiment_end"]))
    remaining = max(Decimal(0), Decimal((end - now).total_seconds()) / Decimal(3600))
    existing = inventory.get("instances", [])
    new = plan.get("instances", [])
    violations: list[str] = []

    existing_monthly = Decimal(0)
    existing_burn = Decimal(0)
    for inst in existing:
        p = prices.get(str(inst.get("plan")))
        if p is None:
            violations.append(f"UNKNOWN_PLAN_PRICE: existing instance plan {inst.get('plan')}")
            continue
        existing_monthly += p
        existing_burn += p / HOURS_PER_MONTH * remaining * SAFETY
    new_cost = Decimal(0)
    for n in new:
        p = prices.get(str(n.get("plan")))
        if p is None:
            violations.append(f"UNKNOWN_PLAN_PRICE: new instance plan {n.get('plan')}")
            continue
        hours = max(Decimal(str(n.get("duration_hours", 0))), remaining)
        new_cost += min(p, p / HOURS_PER_MONTH * hours * SAFETY)

    acct = inventory.get("account", {})
    spent = abs(Decimal(acct.get("balance", "0")) - Decimal(start["balance"])) + max(
        Decimal(0), Decimal(acct.get("pending_charges", "0")) - Decimal(start["pending_charges"])
    )
    monthly = existing_monthly + new_cost
    cumulative = spent + existing_burn + new_cost
    count = len(existing) + len(new)

    if count > MAX_INSTANCES:
        violations.append(f"MAX_INSTANCES: {count} > {MAX_INSTANCES}")
    if monthly > MAX_MONTHLY:
        violations.append(f"MAX_MONTHLY_COST: {_q(monthly)} > {MAX_MONTHLY} USD")
    if cumulative > MAX_CUMULATIVE:
        violations.append(f"MAX_CUMULATIVE_SPEND: {_q(cumulative)} > {MAX_CUMULATIVE} USD")
    return GuardReport(
        passed=not violations,
        violations=violations,
        costs={
            "existing_monthly": _q(existing_monthly),
            "new_prorated": _q(new_cost),
            "projected_monthly": _q(monthly),
            "spend_so_far": _q(spent),
            "existing_burn_to_end": _q(existing_burn),
            "projected_cumulative": _q(cumulative),
        },
        detail={
            "instance_count": count,
            "limits": {
                "instances": MAX_INSTANCES,
                "monthly_usd": str(MAX_MONTHLY),
                "cumulative_usd": str(MAX_CUMULATIVE),
            },
            "hours_to_experiment_end": _q(remaining),
            "safety_multiplier": str(SAFETY),
            "plan_hash": plan["plan_hash"],
            "evaluated_at": now.isoformat(),
        },
    )


def run_guard(
    inventory_path: Path,
    plan_path: Path,
    start_path: Path,
    report_path: Path | None = None,
    now: datetime | None = None,
) -> tuple[int, GuardReport | None, str]:
    """Return (exit_code, report, message). Exit 0 pass, 2 limit violated, 3 refused."""
    now = now or datetime.now(UTC)
    try:
        inv = json.loads(inventory_path.read_text())
        plan = json.loads(plan_path.read_text())
        start = json.loads(start_path.read_text())
        rep = evaluate(inv, plan, start, now)
    except GuardError as e:
        return EXIT_NOT_APPROVED, None, f"REFUSED: {e}"
    except (OSError, ValueError, KeyError, ArithmeticError) as e:
        return EXIT_NOT_APPROVED, None, f"REFUSED: invalid input ({type(e).__name__})"
    if report_path:
        report_path.write_text(json.dumps(rep.as_json(), indent=2, sort_keys=True) + "\n")
    if rep.passed:
        return EXIT_OK, rep, "guard passed"
    return EXIT_VIOLATION, rep, "guard FAILED: " + "; ".join(rep.violations)


def record_start(inventory: dict[str, Any]) -> dict[str, Any]:
    a = inventory["account"]
    return {
        "balance": a["balance"],
        "pending_charges": a["pending_charges"],
        "recorded_at": inventory.get("generated_at"),
    }
