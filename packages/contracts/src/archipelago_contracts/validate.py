"""Fixture validation entrypoints and stream-level checks."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from .models import RECORDS


def parse_record(data: dict[str, Any]) -> BaseModel:
    """Validate a JSON object by its `kind`. Raises ValueError/ValidationError if invalid."""
    kind = data.get("kind")
    model = RECORDS.get(kind) if isinstance(kind, str) else None
    if model is None:
        raise ValueError(f"unknown record kind: {kind!r}")
    return model.model_validate(data)


def parse_json(text: str) -> BaseModel:
    # Reject NaN/Infinity tokens that Python's parser would otherwise accept.
    def bad_constant(name: str) -> Any:
        raise ValueError(f"non-finite number {name} is not valid JSON")

    return parse_record(json.loads(text, parse_constant=bad_constant))


class SequenceTracker:
    """Rejects non-monotonic per-(run, source) sequences (stale or duplicate events)."""

    def __init__(self) -> None:
        self._last: dict[tuple[str, str | None], int] = {}

    def accept(self, run_id: str, source_node_id: str | None, sequence: int) -> bool:
        key = (run_id, source_node_id)
        if sequence <= self._last.get(key, -1):
            return False
        self._last[key] = sequence
        return True
