"""``python -m archipelago_noderuntime``: configuration entirely by environment variables."""

from __future__ import annotations

import json
import os
import signal
import sys


def main() -> int:
    # Thread env must be set before torch is imported (config parsing is torch-free).
    threads = os.environ.get("TORCH_THREADS") or "1"
    for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ.setdefault(k, threads)
    from .config import Config, ConfigError

    try:
        cfg = Config.from_env()
    except ConfigError as e:
        print(f"archipelago_noderuntime: configuration error: {e}", file=sys.stderr)
        return 2
    from .runtime import Runtime

    sys.setswitchinterval(0.001)  # keep act latency low while a validation thread holds the GIL
    rt = Runtime(cfg).start()
    done = rt.node.stop_event
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: done.set())
    print(
        json.dumps(
            {
                "event": "node_ready",
                "node_id": cfg.node_id,
                "boot_id": rt.node.boot_id,
                "control_url": rt.control_url,
                "peer_url": rt.peer_url,
                "restore": rt.node.restore_info,
            }
        ),
        flush=True,
    )
    done.wait()
    rt.stop(checkpoint=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
