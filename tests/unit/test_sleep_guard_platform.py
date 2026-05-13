"""Platform dispatch tests for SleepGuard and LidCloseGuard.

Covers SC-19 (four required cases) plus Linux LidCloseGuard cases.
All subprocess.Popen calls are mocked — no real processes are spawned.
"""

from __future__ import annotations

import subprocess
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from leap.monitor.sleep_guard import LidCloseGuard, SleepGuard
from leap.monitor.sudo_manager import SudoManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_popen(pid: int = 42) -> MagicMock:
    proc = MagicMock(spec=subprocess.Popen)
    proc.pid = pid
    proc.poll.return_value = None  # process is "running"
    return proc


# ---------------------------------------------------------------------------
# SleepGuard
# ---------------------------------------------------------------------------

class TestSleepGuardMacOS:
    def test_spawns_caffeinate_on_macos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("leap.monitor.sleep_guard.sys.platform", "darwin")
        mock_proc = _mock_popen()
        with patch("leap.monitor.sleep_guard.subprocess.Popen", return_value=mock_proc) as mock_popen:
            guard = SleepGuard()
            guard.start()

        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == SleepGuard._CAFFEINATE_PATH
        assert '-i' in cmd
        assert guard.is_active

    def test_macos_caffeinate_absent_logs_and_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("leap.monitor.sleep_guard.sys.platform", "darwin")
        with patch("leap.monitor.sleep_guard.subprocess.Popen", side_effect=OSError("no binary")):
            guard = SleepGuard()
            guard.start()  # must not raise
        assert not guard.is_active


class TestSleepGuardLinux:
    def test_spawns_systemd_inhibit_when_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("leap.monitor.sleep_guard.sys.platform", "linux")
        monkeypatch.setattr(
            "leap.monitor.sleep_guard.shutil.which",
            lambda name: "/usr/bin/systemd-inhibit" if name == "systemd-inhibit" else None,
        )
        mock_proc = _mock_popen()
        with patch("leap.monitor.sleep_guard.subprocess.Popen", return_value=mock_proc) as mock_popen:
            guard = SleepGuard()
            guard.start()

        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "/usr/bin/systemd-inhibit"
        assert "--what=idle" in cmd
        assert "sleep" in cmd
        assert guard.is_active

    def test_no_op_when_systemd_inhibit_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("leap.monitor.sleep_guard.sys.platform", "linux")
        monkeypatch.setattr("leap.monitor.sleep_guard.shutil.which", lambda _: None)
        with patch("leap.monitor.sleep_guard.subprocess.Popen") as mock_popen:
            guard = SleepGuard()
            guard.start()  # must not raise
        mock_popen.assert_not_called()
        assert not guard.is_active


class TestSleepGuardStop:
    def test_stop_terminates_proc_on_both_platforms(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for platform in ("darwin", "linux"):
            monkeypatch.setattr("leap.monitor.sleep_guard.sys.platform", platform)
            mock_proc = _mock_popen()
            guard = SleepGuard()
            guard._proc = mock_proc
            guard.stop()
            mock_proc.terminate.assert_called_once()
            assert guard._proc is None


# ---------------------------------------------------------------------------
# LidCloseGuard
# ---------------------------------------------------------------------------

class TestLidCloseGuardMacOS:
    def test_calls_pmset_on_macos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("leap.monitor.sleep_guard.sys.platform", "darwin")
        with patch.object(SudoManager, 'run', return_value=(0, "")) as mock_run:
            with patch("leap.monitor.sleep_guard._DISABLESLEEP_MARKER") as mock_marker:
                mock_marker.touch.return_value = None
                guard = LidCloseGuard()
                ok, err = guard.start("password")
        assert ok is True
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == LidCloseGuard._PMSET_PATH
        assert "disablesleep" in cmd

    def test_stop_calls_pmset_on_macos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("leap.monitor.sleep_guard.sys.platform", "darwin")
        with patch.object(SudoManager, 'run', return_value=(0, "")) as mock_run:
            with patch("leap.monitor.sleep_guard._DISABLESLEEP_MARKER") as mock_marker:
                mock_marker.exists.return_value = True
                mock_marker.unlink.return_value = None
                guard = LidCloseGuard()
                guard._active = True
                ok, err = guard.stop("password")
        assert ok is True
        cmd = mock_run.call_args[0][0]
        assert "disablesleep" in cmd


class TestLidCloseGuardLinux:
    def test_spawns_systemd_inhibit_sleep_when_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("leap.monitor.sleep_guard.sys.platform", "linux")
        monkeypatch.setattr(
            "leap.monitor.sleep_guard.shutil.which",
            lambda name: "/usr/bin/systemd-inhibit" if name == "systemd-inhibit" else None,
        )
        mock_proc = _mock_popen()
        with patch("leap.monitor.sleep_guard.subprocess.Popen", return_value=mock_proc) as mock_popen:
            guard = LidCloseGuard()
            ok, err = guard.start("")

        assert ok is True
        assert err == ""
        cmd = mock_popen.call_args[0][0]
        assert "--what=sleep" in cmd

    def test_no_op_when_systemd_inhibit_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("leap.monitor.sleep_guard.sys.platform", "linux")
        monkeypatch.setattr("leap.monitor.sleep_guard.shutil.which", lambda _: None)
        with patch("leap.monitor.sleep_guard.subprocess.Popen") as mock_popen:
            guard = LidCloseGuard()
            ok, err = guard.start("")
        assert ok is True
        assert err == ""
        mock_popen.assert_not_called()

    def test_stop_terminates_proc_on_linux(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("leap.monitor.sleep_guard.sys.platform", "linux")
        mock_proc = _mock_popen()
        guard = LidCloseGuard()
        guard._proc = mock_proc
        guard._active = True
        ok, err = guard.stop("")
        assert ok is True
        mock_proc.terminate.assert_called_once()
        assert guard._proc is None
        assert not guard._active
