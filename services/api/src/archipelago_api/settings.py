from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    api_token: str  # owner-operated demo login; required, never defaulted
    data_dir: Path
    allowed_origins: frozenset[str] = field(default_factory=frozenset)
    max_active_runs: int = 1
    tick_interval: float | None = 0.1  # None = manual: only the step command advances
    event_log_size: int = 5000
    subscriber_queue: int = 64
    send_timeout: float = 5.0

    @classmethod
    def from_env(cls) -> Settings:
        token = os.environ.get("ARCHIPELAGO_API_TOKEN", "")
        if len(token) < 16:
            raise RuntimeError("ARCHIPELAGO_API_TOKEN must be set (>= 16 chars)")
        origins = os.environ.get("ARCHIPELAGO_ALLOWED_ORIGINS", "")
        return cls(
            api_token=token,
            data_dir=Path(os.environ.get("ARCHIPELAGO_DATA_DIR", "var/api")),
            allowed_origins=frozenset(o for o in origins.split(",") if o),
        )
