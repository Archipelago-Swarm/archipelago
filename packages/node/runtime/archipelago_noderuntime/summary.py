"""Visited-cell summary: the non-model peer information message (live-runtime.md Amendment A18).

A summary tells a peer which grid cells this node has stood on in the current episode. It carries
no parameters, replay rows, policy outputs or map cells, and it is never counted as a model offer.
It travels in the same authenticated ``Envelope`` as model offers, distinguished by its first
payload byte (``{``: a JSON object; model offers are npz/zip archives, which start with ``PK``).

Wire format ``visit-summary-v1`` (UTF-8 JSON, one object, no extra keys)::

    {"kind": "visit-summary-v1", "node": "node-02", "run_id": "...", "episode": 3, "tick": 17,
     "encoder": "grid-flat-v2-visits-shared-s16-r2", "size": 16, "n": 41, "cells": "<base64>"}

``cells`` is the full state (not a delta, so a lost or refused message is repaired by the next
one): a bitmap of ``size * size`` bits, bit ``y * size + x`` (little-endian bit order inside each
byte), base64 encoded; ``n`` is its population count. Size bound: the bitmap is at most
``ceil(size**2 / 8)`` bytes (32 bytes for 16x16, 8 KiB for the largest world of 256x256), the
whole payload at most ``MAX_SUMMARY_BYTES``.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass

import numpy as np

KIND = "visit-summary-v1"
MAX_SUMMARY_BYTES = 16 * 1024  # 256x256 world: 8192 B bitmap -> 10924 B base64 + header
MAX_SIZE = 256
_KEYS = {"kind", "node", "run_id", "episode", "tick", "encoder", "size", "n", "cells"}


class SummaryError(ValueError):
    """A summary that must be refused; ``str(e)`` is the named reason."""


def is_summary(payload: bytes) -> bool:
    """Message-class test used by the peer receive path (model npz payloads start with PK)."""
    return payload[:1] == b"{"


@dataclass(frozen=True)
class Summary:
    node: str
    run_id: str
    episode: int
    tick: int
    encoder: str
    size: int
    cells: frozenset[tuple[int, int]]


def encode(
    node: str,
    run_id: str,
    episode: int,
    tick: int,
    encoder: str,
    size: int,
    cells,
) -> bytes:
    if not 1 <= size <= MAX_SIZE:
        raise SummaryError(f"size {size} outside 1..{MAX_SIZE}")
    bits = np.zeros(size * size, np.uint8)
    n = 0
    for x, y in cells:
        if 0 <= x < size and 0 <= y < size and not bits[y * size + x]:
            bits[y * size + x] = 1
            n += 1
    packed = np.packbits(bits, bitorder="little").tobytes()
    doc = {
        "kind": KIND,
        "node": node,
        "run_id": run_id,
        "episode": episode,
        "tick": tick,
        "encoder": encoder,
        "size": size,
        "n": n,
        "cells": base64.b64encode(packed).decode("ascii"),
    }
    out = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
    if len(out) > MAX_SUMMARY_BYTES:
        raise SummaryError("summary exceeds MAX_SUMMARY_BYTES")
    return out


def _int(v, lo: int, hi: int, what: str) -> int:
    if type(v) is not int or not lo <= v <= hi:
        raise SummaryError(f"bad {what}")
    return v


def decode(payload: bytes, *, expect_size: int, expect_encoder: str) -> Summary:
    """Parse and validate a summary. Never raises anything but ``SummaryError``."""
    if len(payload) > MAX_SUMMARY_BYTES:
        raise SummaryError("summary too large")
    try:
        doc = json.loads(payload)
    except ValueError as e:
        raise SummaryError(f"malformed summary: {e}") from e
    if not isinstance(doc, dict) or set(doc) != _KEYS:
        raise SummaryError("unexpected summary members")
    if doc["kind"] != KIND:
        raise SummaryError(f"unknown message kind {str(doc['kind'])[:40]!r}")
    for k in ("node", "run_id", "encoder"):
        if not isinstance(doc[k], str) or not 0 < len(doc[k]) <= 128:
            raise SummaryError(f"bad {k}")
    if doc["encoder"] != expect_encoder:
        raise SummaryError(f"incompatible encoder: {doc['encoder']!r}")
    size = _int(doc["size"], 1, MAX_SIZE, "size")
    if size != expect_size:
        raise SummaryError(f"incompatible size: {size}")
    episode = _int(doc["episode"], 0, 2**31, "episode")
    tick = _int(doc["tick"], 0, 2**31, "tick")
    n = _int(doc["n"], 0, size * size, "n")
    if not isinstance(doc["cells"], str):
        raise SummaryError("bad cells")
    try:
        raw = base64.b64decode(doc["cells"], validate=True)
    except (binascii.Error, ValueError) as e:
        raise SummaryError("cells is not base64") from e
    if len(raw) != (size * size + 7) // 8:
        raise SummaryError("cells has the wrong length")
    bits = np.unpackbits(np.frombuffer(raw, np.uint8), bitorder="little")
    if bits[size * size :].any():
        raise SummaryError("cells has bits beyond the grid")
    bits = bits[: size * size]
    if int(bits.sum()) != n:
        raise SummaryError("n does not match the bitmap")
    idx = np.flatnonzero(bits)
    cells = frozenset((int(i % size), int(i // size)) for i in idx)
    return Summary(doc["node"], doc["run_id"], episode, tick, doc["encoder"], size, cells)
