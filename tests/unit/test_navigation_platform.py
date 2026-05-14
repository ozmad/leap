"""Platform dispatch tests for navigation helpers.

Covers AC-1..AC-8 from subtask 5 (linux-compatibility):
  - _navigate_vscode: macOS osascript path, Linux with code, Linux without code
  - _navigate_iterm2/_navigate_terminal_app/_navigate_arduino/_navigate_jetbrains:
    all return False on Linux without raising
  - _find_wezterm_cli: Linux returns shutil.which result only (no mdfind)
  - _activate_wezterm: macOS uses 'open -a', Linux best-effort wmctrl/xdotool
  - detect_supported_ide_for_move: Linux returns 'VS Code' when code on PATH
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _navigate_vscode
# ---------------------------------------------------------------------------

class TestNavigateVSCodeLinux:
    def test_calls_code_reuse_window_and_writes_request_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr("leap.monitor.navigation.sys.platform", "linux")
        monkeypatch.setattr(
            "leap.monitor.navigation.shutil.which",
            lambda name: "/usr/bin/code" if name == "code" else None,
        )
        request_file = tmp_path / ".leap-terminal-request"
        monkeypatch.setattr(
            "leap.monitor.navigation.os.path.expanduser",
            lambda _: str(request_file),
        )
        with patch("leap.monitor.navigation.subprocess.run") as mock_run:
            from leap.monitor.navigation import _navigate_vscode
            result = _navigate_vscode(str(tmp_path), "my-terminal", "VS Code")

        assert result is True
        cmd = mock_run.call_args[0][0]
        assert "--reuse-window" in cmd
        assert request_file.read_text() == "my-terminal"

    def test_returns_true_without_code_on_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr("leap.monitor.navigation.sys.platform", "linux")
        monkeypatch.setattr("leap.monitor.navigation.shutil.which", lambda _: None)
        request_file = tmp_path / ".leap-terminal-request"
        monkeypatch.setattr(
            "leap.monitor.navigation.os.path.expanduser",
            lambda _: str(request_file),
        )
        from leap.monitor.navigation import _navigate_vscode
        result = _navigate_vscode(None, "my-terminal", "VS Code")
        assert result is True
        assert request_file.read_text() == "my-terminal"

    def test_does_not_call_osascript_on_linux(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr("leap.monitor.navigation.sys.platform", "linux")
        monkeypatch.setattr("leap.monitor.navigation.shutil.which", lambda _: None)
        monkeypatch.setattr(
            "leap.monitor.navigation.os.path.expanduser",
            lambda _: str(tmp_path / ".leap-terminal-request"),
        )
        with patch("leap.monitor.navigation.subprocess.run") as mock_run:
            from leap.monitor.navigation import _navigate_vscode
            _navigate_vscode(None, "t", "VS Code")
        # Must not have called osascript
        for call in mock_run.call_args_list:
            assert 'osascript' not in str(call)


class TestNavigateVSCodeMacOS:
    def test_uses_osascript_on_macos(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr("leap.monitor.navigation.sys.platform", "darwin")
        monkeypatch.setattr(
            "leap.monitor.navigation.os.path.expanduser",
            lambda _: str(tmp_path / ".leap-terminal-request"),
        )
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("leap.monitor.navigation.subprocess.run", return_value=mock_result):
            from leap.monitor.navigation import _navigate_vscode
            result = _navigate_vscode(str(tmp_path), "t", "VS Code")
        assert result is True


# ---------------------------------------------------------------------------
# macOS-only navigation functions return False on Linux
# ---------------------------------------------------------------------------

class TestMacOSOnlyNavigationOnLinux:
    @pytest.mark.parametrize("fn_name,args", [
        ("_navigate_iterm2", ("pattern",)),
        ("_navigate_terminal_app", ("pattern",)),
        ("_navigate_arduino", ("pattern",)),
    ])
    def test_returns_false_on_linux(
        self,
        fn_name: str,
        args: tuple,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("leap.monitor.navigation.sys.platform", "linux")
        import leap.monitor.navigation as nav
        fn = getattr(nav, fn_name)
        with patch("leap.monitor.navigation.subprocess.run") as mock_run:
            result = fn(*args)
        assert result is False
        mock_run.assert_not_called()

    def test_navigate_jetbrains_returns_false_on_linux(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("leap.monitor.navigation.sys.platform", "linux")
        from leap.monitor.navigation import _navigate_jetbrains
        with patch("leap.monitor.navigation.subprocess.run") as mock_run:
            result = _navigate_jetbrains("PyCharm", "/some/path", "terminal")
        assert result is False
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# _find_wezterm_cli
# ---------------------------------------------------------------------------

class TestFindWeztermCli:
    def test_returns_which_result_on_linux(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("leap.monitor.navigation.sys.platform", "linux")
        monkeypatch.setattr(
            "leap.monitor.navigation.shutil.which",
            lambda name: "/usr/bin/wezterm" if name == "wezterm" else None,
        )
        from leap.monitor.navigation import _find_wezterm_cli
        assert _find_wezterm_cli() == "/usr/bin/wezterm"

    def test_returns_none_on_linux_when_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("leap.monitor.navigation.sys.platform", "linux")
        monkeypatch.setattr("leap.monitor.navigation.shutil.which", lambda _: None)
        with patch("leap.monitor.navigation.subprocess.run") as mock_run:
            from leap.monitor.navigation import _find_wezterm_cli
            result = _find_wezterm_cli()
        assert result is None
        # Must not have called mdfind
        mock_run.assert_not_called()

    def test_calls_mdfind_on_macos_as_fallback(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr("leap.monitor.navigation.sys.platform", "darwin")
        monkeypatch.setattr("leap.monitor.navigation.shutil.which", lambda _: None)
        monkeypatch.setattr("leap.monitor.navigation.os.path.isfile", lambda _: False)
        fake_app = str(tmp_path / "WezTerm.app")
        fake_cli = str(tmp_path / "WezTerm.app" / "Contents" / "MacOS" / "wezterm")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = fake_app + "\n"
        with patch("leap.monitor.navigation.subprocess.run", return_value=mock_result):
            with patch(
                "leap.monitor.navigation.os.path.isfile",
                side_effect=lambda p: p == fake_cli,
            ):
                from leap.monitor.navigation import _find_wezterm_cli
                result = _find_wezterm_cli()
        assert result == fake_cli


# ---------------------------------------------------------------------------
# _activate_wezterm
# ---------------------------------------------------------------------------

class TestActivateWezterm:
    def test_uses_open_on_macos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("leap.monitor.navigation.sys.platform", "darwin")
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("leap.monitor.navigation.subprocess.run", return_value=mock_result) as mock_run:
            from leap.monitor.navigation import _activate_wezterm
            result = _activate_wezterm()
        assert result is True
        cmd = mock_run.call_args[0][0]
        assert cmd == ['open', '-a', 'WezTerm']

    def test_uses_wmctrl_on_linux_when_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("leap.monitor.navigation.sys.platform", "linux")
        monkeypatch.setattr(
            "leap.monitor.navigation.shutil.which",
            lambda name: "/usr/bin/wmctrl" if name == "wmctrl" else None,
        )
        with patch("leap.monitor.navigation.subprocess.run") as mock_run:
            from leap.monitor.navigation import _activate_wezterm
            result = _activate_wezterm()
        assert result is True
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "wmctrl"

    def test_returns_true_on_linux_even_without_focus_tool(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("leap.monitor.navigation.sys.platform", "linux")
        monkeypatch.setattr("leap.monitor.navigation.shutil.which", lambda _: None)
        from leap.monitor.navigation import _activate_wezterm
        assert _activate_wezterm() is True


# ---------------------------------------------------------------------------
# detect_supported_ide_for_move
# ---------------------------------------------------------------------------

class TestDetectSupportedIDEForMoveLinux:
    def test_returns_vscode_when_code_on_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("leap.monitor.navigation.sys.platform", "linux")
        monkeypatch.setattr(
            "leap.monitor.navigation.shutil.which",
            lambda name: "/usr/bin/code" if name == "code" else None,
        )
        from leap.monitor.navigation import detect_supported_ide_for_move
        assert detect_supported_ide_for_move("") == "VS Code"

    def test_returns_vscode_for_cursor_on_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("leap.monitor.navigation.sys.platform", "linux")
        monkeypatch.setattr(
            "leap.monitor.navigation.shutil.which",
            lambda name: "/usr/local/bin/cursor" if name == "cursor" else None,
        )
        from leap.monitor.navigation import detect_supported_ide_for_move
        assert detect_supported_ide_for_move("") == "VS Code"

    def test_returns_none_when_no_ide_on_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("leap.monitor.navigation.sys.platform", "linux")
        monkeypatch.setattr("leap.monitor.navigation.shutil.which", lambda _: None)
        from leap.monitor.navigation import detect_supported_ide_for_move
        assert detect_supported_ide_for_move("") is None
