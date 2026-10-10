"""The outer loop preserves its deadline and prevents duplicate owners."""

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "agents"))
import watchdog  # noqa: E402


def test_watchdog_lock_is_released_after_owner_exits(tmp_path: Path) -> None:
    with patch.object(watchdog, "RUNTIME", tmp_path):
        with watchdog.process_lock("watchdog-B"):
            if os.name == "nt":
                with pytest.raises(RuntimeError, match="already running"):
                    with watchdog.process_lock("watchdog-B"):
                        pass
        with watchdog.process_lock("watchdog-B"):
            pass


def test_deadline_prevents_launching_another_driver(tmp_path: Path) -> None:
    with (
        patch.object(watchdog, "RUNTIME", tmp_path),
        patch.object(watchdog.subprocess, "Popen") as launch,
    ):
        watchdog.supervise("B", datetime.now(UTC) - timedelta(seconds=1), 10)
    launch.assert_not_called()
    assert '"state": "stopped"' in (tmp_path / "watchdog-B.json").read_text()


def test_driver_exit_is_restarted_until_stop_file(tmp_path: Path) -> None:
    def stop_after_second_exit(_delay: float, _deadline: datetime) -> None:
        if launch.call_count == 2:
            (tmp_path / "STOP").touch()

    child = SimpleNamespace(pid=1234, wait=lambda: 1)
    with (
        patch.object(watchdog, "RUNTIME", tmp_path),
        patch.object(watchdog.subprocess, "Popen", return_value=child) as launch,
        patch.object(watchdog, "pause", side_effect=stop_after_second_exit),
    ):
        watchdog.supervise("B", datetime.now(UTC) + timedelta(hours=1), 10)
    assert launch.call_count == 2
    assert '"reason": "STOP file"' in (tmp_path / "watchdog-B.json").read_text()
