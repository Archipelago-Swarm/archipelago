"""Coordinator configuration (environment driven; secrets only from the environment)."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MIN_TOKEN = 16


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    coordinator_token: str
    admin_token: str
    node_token: str
    data_dir: Path
    production: bool = False
    node_urls: dict[str, str] = field(default_factory=dict)  # readiness probes only
    world_kwargs: dict[str, Any] = field(default_factory=dict)
    tick_interval_s: float = 0.0  # optional pacing between ticks
    start_paused: bool = False  # run waits (paused) before its first tick until resumed/stepped
    commit: str = "unknown"

    def validate(self) -> None:
        for name in ("coordinator_token", "admin_token", "node_token"):
            if len(getattr(self, name)) < MIN_TOKEN:
                raise ConfigError(f"{name} must be at least {MIN_TOKEN} characters")
        if self.admin_token == self.coordinator_token:
            raise ConfigError("admin token must differ from the coordinator token")
        if self.tick_interval_s < 0:
            raise ConfigError("tick_interval_s must be >= 0")

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        def need(k: str) -> str:
            v = env.get(k, "")
            if not v:
                raise ConfigError(f"{k} is required")
            return v

        urls: dict[str, str] = {}
        for part in filter(None, re.split(r"[,\s]+", env.get("COORDINATOR_NODE_URLS", ""))):
            node, sep, url = part.partition("=")
            if not sep or not url:
                raise ConfigError(f"bad COORDINATOR_NODE_URLS entry {part!r}")
            urls[node] = url
        try:
            kwargs = json.loads(env.get("COORDINATOR_WORLD_KWARGS", "{}"))
        except json.JSONDecodeError as e:
            raise ConfigError(f"COORDINATOR_WORLD_KWARGS is not JSON: {e}") from e
        if not isinstance(kwargs, dict):
            raise ConfigError("COORDINATOR_WORLD_KWARGS must be a JSON object")
        s = cls(
            coordinator_token=need("COORDINATOR_TOKEN"),
            admin_token=need("COORDINATOR_ADMIN_TOKEN"),
            node_token=need("NODE_CONTROL_TOKEN"),
            data_dir=Path(env.get("COORDINATOR_DATA_DIR", "/data/coordinator")),
            production=env.get("ARCHIPELAGO_ENV", "") == "production",
            node_urls=urls,
            world_kwargs=kwargs,
            tick_interval_s=float(env.get("COORDINATOR_TICK_INTERVAL_S", "0")),
            commit=env.get("ARCHIPELAGO_COMMIT") or _git_commit(),
        )
        s.validate()
        return s


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=True
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"
