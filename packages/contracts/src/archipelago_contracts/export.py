"""Export committed JSON Schemas from the canonical Pydantic models.

Usage: python -m archipelago_contracts.export [--check]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any, Union

from pydantic import Field, TypeAdapter

from .models import RECORDS

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


def render() -> dict[str, str]:
    out: dict[str, str] = {}
    for kind, model in RECORDS.items():
        schema = model.model_json_schema(mode="validation")
        out[f"{kind}.schema.json"] = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    union = TypeAdapter[Any](
        Annotated[Union[tuple(RECORDS.values())], Field(discriminator="kind")]  # type: ignore[arg-type]  # noqa: UP007
    ).json_schema(mode="validation")
    out["record.schema.json"] = json.dumps(union, indent=2, sort_keys=True) + "\n"
    return out


def main(argv: list[str]) -> int:
    rendered = render()
    if "--check" in argv:
        stale = [
            n
            for n, t in rendered.items()
            if not (SCHEMA_DIR / n).is_file() or (SCHEMA_DIR / n).read_text() != t
        ]
        if stale:
            print(f"stale schemas (run export): {stale}", file=sys.stderr)
            return 1
        return 0
    SCHEMA_DIR.mkdir(exist_ok=True)
    for name, text in rendered.items():
        (SCHEMA_DIR / name).write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
