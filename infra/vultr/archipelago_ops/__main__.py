"""python -m archipelago_ops {inventory|record-start|guard|tigerdata|deploy} ..."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from . import deploy, guard, tigerdata, vultr


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "deploy":
        return deploy.main(rest)
    p = argparse.ArgumentParser(prog=cmd)
    p.add_argument("--evidence-dir", type=Path, default=Path("evidence"))
    if cmd == "inventory":
        p.add_argument("--base-url", default=vultr.DEFAULT_BASE_URL)
    elif cmd == "record-start":
        p.add_argument("--inventory", type=Path)
    elif cmd == "guard":
        p.add_argument("--inventory", type=Path)
        p.add_argument("--plan", type=Path, required=True)
        p.add_argument("--start", type=Path)
    elif cmd != "tigerdata":
        print(__doc__)
        return 2
    a = p.parse_args(rest)
    ev: Path = a.evidence_dir
    now = datetime.now(UTC)
    if cmd == "inventory":
        try:
            client = vultr.VultrClient.from_env(a.base_url)
            inv = vultr.build_inventory(client, now.isoformat())
        except vultr.VultrError as e:
            print(f"inventory failed: {e}")
            return 1
        _write(ev / "inventory.json", inv)
        print(f"wrote {ev / 'inventory.json'}")
        return 0
    if cmd == "record-start":
        inv_path = a.inventory or ev / "inventory.json"
        _write(ev / "spend-start.json", guard.record_start(json.loads(inv_path.read_text())))
        print(f"wrote {ev / 'spend-start.json'}")
        return 0
    if cmd == "guard":
        code, rep, msg = guard.run_guard(
            a.inventory or ev / "inventory.json",
            a.plan,
            a.start or ev / "spend-start.json",
            ev / "guard-report.json",
            now,
        )
        print(msg)
        if rep:
            print(json.dumps(rep.costs, indent=2))
        return code
    report = tigerdata.main()
    _write(ev / "tigerdata-report.json", report)
    for c in report["checks"]:
        print(("PASS " if c["ok"] else "FAIL ") + c["check"])
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
