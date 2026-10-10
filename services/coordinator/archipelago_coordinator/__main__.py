"""Run the coordinator: `python -m archipelago_coordinator [--host H] [--port P]`."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from .httpd import make_server
from .service import Coordinator
from .settings import ConfigError, Settings
from .sim import SimulatorUnavailable


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="archipelago_coordinator")
    ap.add_argument("--host", default=os.environ.get("COORDINATOR_HOST", "0.0.0.0"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("COORDINATOR_PORT", "8800")))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        settings = Settings.from_env(os.environ)
        svc = Coordinator(settings)
    except (ConfigError, SimulatorUnavailable) as e:
        print(f"coordinator: fatal: {e}", file=sys.stderr)
        return 2
    server = make_server(svc, args.host, args.port)
    logging.info("coordinator listening on %s:%s boot_id=%s", args.host, args.port, svc.boot_id)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        svc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
