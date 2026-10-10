"""Transactional checkpoint generations (live-runtime.md section 7). Single writer per root.

Layout: root/gen-<n>/<files> + MANIFEST.json (sha256 per file, written last), root/CURRENT
(JSON {generation, manifest_sha256}) switched atomically. Stdlib only.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path

KEEP = 3
_GEN = re.compile(r"^gen-(\d+)$")
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")


class CheckpointError(RuntimeError):
    pass


class DurableIO:
    """Filesystem primitives. Every primitive calls hook() first so tests can inject a kill."""

    def hook(self, op: str, path: str) -> None:
        pass

    def mkdir(self, path: Path) -> None:
        self.hook("mkdir", str(path))
        path.mkdir(parents=True, exist_ok=True)

    def write_tmp(self, tmp: Path, data: bytes) -> None:
        self.hook("write_tmp", str(tmp))
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

    def rename(self, src: Path, dst: Path) -> None:
        self.hook("rename", str(dst))
        os.replace(src, dst)

    def fsync_dir(self, path: Path) -> None:
        self.hook("fsync_dir", str(path))
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def write_file(self, path: Path, data: bytes) -> None:
        tmp = path.with_name(path.name + ".tmp")
        self.write_tmp(tmp, data)
        self.rename(tmp, path)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _gens(root: Path) -> list[int]:
    if not root.is_dir():
        return []
    return sorted(int(m.group(1)) for p in root.iterdir() if (m := _GEN.match(p.name)))


def _verify(root: Path, n: int) -> tuple[dict, dict[str, bytes]] | None:
    """Load and hash-check generation n; None if incomplete or corrupt."""
    d = root / f"gen-{n}"
    try:
        manifest = json.loads((d / "MANIFEST.json").read_bytes())
        if manifest.get("generation") != n:
            return None
        files = {}
        for name, info in manifest["files"].items():
            if not _NAME.match(name):
                return None
            data = (d / name).read_bytes()
            if len(data) != info["bytes"] or _sha(data) != info["sha256"]:
                return None
            files[name] = data
        return manifest, files
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _gc(root: Path) -> None:
    complete = []
    for n in _gens(root):
        if _verify(root, n) is not None:
            complete.append(n)
        else:
            shutil.rmtree(root / f"gen-{n}", ignore_errors=True)  # incomplete/corrupt: unloadable
    for n in complete[:-KEEP]:
        shutil.rmtree(root / f"gen-{n}", ignore_errors=True)
    for t in root.glob("*.tmp"):
        t.unlink(missing_ok=True)


def write_generation(root, files: dict[str, bytes], io: DurableIO | None = None) -> dict:
    io = io or DurableIO()
    root = Path(root)
    for name in files:
        if not _NAME.match(name) or name in ("MANIFEST.json", "CURRENT"):
            raise ValueError(f"bad checkpoint file name {name!r}")
    io.mkdir(root)
    _gc(root)
    gens = _gens(root)
    n = (gens[-1] if gens else 0) + 1
    d = root / f"gen-{n}"
    io.mkdir(d)
    for name, data in files.items():
        io.write_file(d / name, data)
    io.fsync_dir(d)
    manifest = {
        "generation": n,
        "files": {k: {"sha256": _sha(v), "bytes": len(v)} for k, v in files.items()},
    }
    mbytes = json.dumps(manifest, sort_keys=True).encode()
    io.write_file(d / "MANIFEST.json", mbytes)
    io.fsync_dir(d)
    cur = json.dumps({"generation": n, "manifest_sha256": _sha(mbytes)}).encode()
    io.write_file(root / "CURRENT", cur)
    io.fsync_dir(root)
    _gc(root)
    return manifest


def read_latest(root) -> tuple[dict, dict[str, bytes]]:
    """Newest verified generation: CURRENT's first, then older complete ones."""
    root = Path(root)
    order: list[int] = []
    try:
        cur = json.loads((root / "CURRENT").read_bytes())
        n = int(cur["generation"])
        mb = (root / f"gen-{n}" / "MANIFEST.json").read_bytes()
        if _sha(mb) == cur["manifest_sha256"]:
            order.append(n)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    order += [n for n in reversed(_gens(root)) if n not in order]
    for n in order:
        got = _verify(root, n)
        if got is not None:
            return got
    raise CheckpointError(f"no loadable checkpoint generation under {root}")


# A17 fixed file names and cadence (live-runtime.md section 13).
FILE_POLICY = "policy.npz"
FILE_TARGET = "target.npz"
FILE_OPTIMIZER = "optimizer.npz"
FILE_REPLAY = "replay.npz"
FILE_RNG = "rng.json"
FILE_COUNTERS = "counters.json"
CHECKPOINT_FILES = (FILE_POLICY, FILE_TARGET, FILE_OPTIMIZER, FILE_REPLAY, FILE_RNG, FILE_COUNTERS)
CHECKPOINT_EVERY_FEEDBACK_STEPS = 200  # plus one generation at each episode_end


def replay_max_bytes(capacity: int, obs_dim: int) -> int:
    """Replay file size bound from A17: capacity * obs_dim * 4 * 2."""
    return capacity * obs_dim * 4 * 2


def checkpoint_due(feedback_steps: int) -> bool:
    return feedback_steps > 0 and feedback_steps % CHECKPOINT_EVERY_FEEDBACK_STEPS == 0


# A3: crash-safe monotonic sequence numbers. The persisted value is a ceiling: every number
# below it may already have been issued. A new process starts at the persisted ceiling and
# reserves the next block before issuing from it, so a crash can waste numbers but never reuse.
SEQUENCE_BLOCK = 1000


class SequenceAllocator:
    """Block-reserved sequence allocator. ``state_path`` holds JSON {"ceiling": n}."""

    def __init__(self, state_path, io: DurableIO | None = None, block: int = SEQUENCE_BLOCK):
        self._path = Path(state_path)
        self._io = io or DurableIO()
        self._block = block
        try:
            self._ceiling = int(json.loads(self._path.read_bytes())["ceiling"])
        except FileNotFoundError:
            self._ceiling = 0
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise CheckpointError(f"unreadable sequence state {self._path}: {e}") from e
        self._next = self._ceiling  # numbers below the old ceiling may have been issued

    @property
    def ceiling(self) -> int:
        return self._ceiling

    def next(self) -> int:
        if self._next >= self._ceiling:
            new = self._ceiling + self._block
            self._io.mkdir(self._path.parent)
            self._io.write_file(self._path, json.dumps({"ceiling": new}).encode())
            self._io.fsync_dir(self._path.parent)
            self._ceiling = new
        n = self._next
        self._next += 1
        return n
