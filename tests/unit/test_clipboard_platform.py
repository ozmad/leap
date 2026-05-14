"""Platform dispatch tests for clipboard helpers.

Covers AC-1..AC-6 from subtask 4 (linux-compatibility):
  - check_clipboard_has_image: macOS osascript path, Linux xclip, Linux xsel, neither
  - save_clipboard_image: macOS osascript path, Linux xclip, Linux xsel
  - _copy_to_clipboard: macOS pbcopy, Linux xclip, Linux xsel, neither
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# check_clipboard_has_image
# ---------------------------------------------------------------------------

class TestCheckClipboardHasImageMacOS:
    def test_returns_true_when_osascript_reports_picture(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("leap.client.image_handler.sys.platform", "darwin")
        mock_result = MagicMock()
        mock_result.stdout = "picture, TIFF data, PNG"
        with patch("leap.client.image_handler.subprocess.run", return_value=mock_result):
            from leap.client.image_handler import check_clipboard_has_image
            assert check_clipboard_has_image() is True

    def test_returns_false_when_osascript_reports_no_image(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("leap.client.image_handler.sys.platform", "darwin")
        mock_result = MagicMock()
        mock_result.stdout = "string, Unicode text"
        with patch("leap.client.image_handler.subprocess.run", return_value=mock_result):
            from leap.client.image_handler import check_clipboard_has_image
            assert check_clipboard_has_image() is False

    def test_returns_false_on_osascript_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("leap.client.image_handler.sys.platform", "darwin")
        with patch(
            "leap.client.image_handler.subprocess.run",
            side_effect=OSError("not found"),
        ):
            from leap.client.image_handler import check_clipboard_has_image
            assert check_clipboard_has_image() is False


class TestCheckClipboardHasImageLinux:
    def test_xclip_detects_png(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("leap.client.image_handler.sys.platform", "linux")
        monkeypatch.setattr(
            "leap.client.image_handler.shutil.which",
            lambda name: "/usr/bin/xclip" if name == "xclip" else None,
        )
        mock_result = MagicMock()
        mock_result.stdout = b"image/png\nimage/jpeg\n"
        with patch("leap.client.image_handler.subprocess.run", return_value=mock_result):
            from leap.client.image_handler import check_clipboard_has_image
            assert check_clipboard_has_image() is True

    def test_xsel_fallback_detects_png_magic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("leap.client.image_handler.sys.platform", "linux")
        monkeypatch.setattr(
            "leap.client.image_handler.shutil.which",
            lambda name: "/usr/bin/xsel" if name == "xsel" else None,
        )
        mock_result = MagicMock()
        mock_result.stdout = b"\x89PNG\r\nfakedata"
        with patch("leap.client.image_handler.subprocess.run", return_value=mock_result):
            from leap.client.image_handler import check_clipboard_has_image
            assert check_clipboard_has_image() is True

    def test_returns_false_when_neither_tool_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("leap.client.image_handler.sys.platform", "linux")
        monkeypatch.setattr("leap.client.image_handler.shutil.which", lambda _: None)
        from leap.client.image_handler import check_clipboard_has_image
        assert check_clipboard_has_image() is False


# ---------------------------------------------------------------------------
# save_clipboard_image
# ---------------------------------------------------------------------------

class TestSaveClipboardImageMacOS:
    def test_uses_osascript_and_deduplicates(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: "pytest.TempPathFactory"
    ) -> None:
        import os
        import tempfile as _real_tempfile

        monkeypatch.setattr("leap.client.image_handler.sys.platform", "darwin")
        monkeypatch.setattr("leap.client.image_handler.QUEUE_IMAGES_DIR", tmp_path)
        png_bytes = b"\x89PNG\r\nfakeimagedata"

        # Save the original mkstemp before patching to avoid recursion.
        _orig_mkstemp = _real_tempfile.mkstemp

        def fake_mkstemp(suffix: str, dir: str) -> tuple:
            fd, path = _orig_mkstemp(suffix=suffix, dir=dir)
            os.write(fd, png_bytes)
            os.close(fd)
            # Return a fresh fd so the caller can close it.
            return (os.open(path, os.O_RDONLY), path)

        mock_run = MagicMock()
        mock_run.return_value.returncode = 0

        with (
            patch("leap.client.image_handler.tempfile.mkstemp", side_effect=fake_mkstemp),
            patch("leap.client.image_handler.subprocess.run", mock_run),
        ):
            from leap.client.image_handler import save_clipboard_image
            result = save_clipboard_image()

        assert result is not None
        assert result.endswith(".png")
        assert os.path.isfile(result)


class TestSaveClipboardImageLinux:
    def test_xclip_saves_png(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: "pytest.TempPathFactory"
    ) -> None:
        monkeypatch.setattr("leap.client.image_handler.sys.platform", "linux")
        monkeypatch.setattr("leap.client.image_handler.QUEUE_IMAGES_DIR", tmp_path)
        monkeypatch.setattr(
            "leap.client.image_handler.shutil.which",
            lambda name: "/usr/bin/xclip" if name == "xclip" else None,
        )
        png_bytes = b"\x89PNG\r\nfakedata"
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = png_bytes
        with patch("leap.client.image_handler.subprocess.run", return_value=mock_result):
            from leap.client.image_handler import save_clipboard_image
            result = save_clipboard_image()
        import os
        assert result is not None
        assert os.path.isfile(result)

    def test_xsel_fallback_saves_png(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: "pytest.TempPathFactory"
    ) -> None:
        monkeypatch.setattr("leap.client.image_handler.sys.platform", "linux")
        monkeypatch.setattr("leap.client.image_handler.QUEUE_IMAGES_DIR", tmp_path)
        monkeypatch.setattr(
            "leap.client.image_handler.shutil.which",
            lambda name: "/usr/bin/xsel" if name == "xsel" else None,
        )
        png_bytes = b"\x89PNG\r\nfakedata"
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = png_bytes
        with patch("leap.client.image_handler.subprocess.run", return_value=mock_result):
            from leap.client.image_handler import save_clipboard_image
            result = save_clipboard_image()
        import os
        assert result is not None
        assert os.path.isfile(result)

    def test_returns_none_when_no_tool_present(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: "pytest.TempPathFactory"
    ) -> None:
        monkeypatch.setattr("leap.client.image_handler.sys.platform", "linux")
        monkeypatch.setattr("leap.client.image_handler.QUEUE_IMAGES_DIR", tmp_path)
        monkeypatch.setattr("leap.client.image_handler.shutil.which", lambda _: None)
        from leap.client.image_handler import save_clipboard_image
        assert save_clipboard_image() is None


# ---------------------------------------------------------------------------
# _copy_to_clipboard (navigation.py)
# ---------------------------------------------------------------------------

class TestCopyToClipboardMacOS:
    def test_uses_pbcopy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("leap.monitor.navigation.sys.platform", "darwin")
        with patch("leap.monitor.navigation.subprocess.run") as mock_run:
            from leap.monitor.navigation import _copy_to_clipboard
            _copy_to_clipboard("hello world")
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "pbcopy"

    def test_does_not_raise_on_pbcopy_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("leap.monitor.navigation.sys.platform", "darwin")
        with patch(
            "leap.monitor.navigation.subprocess.run",
            side_effect=OSError("pbcopy missing"),
        ):
            from leap.monitor.navigation import _copy_to_clipboard
            _copy_to_clipboard("hello")  # must not raise


class TestCopyToClipboardLinux:
    def test_uses_xclip_when_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("leap.monitor.navigation.sys.platform", "linux")
        monkeypatch.setattr(
            "leap.monitor.navigation.shutil.which",
            lambda name: "/usr/bin/xclip" if name == "xclip" else None,
        )
        with patch("leap.monitor.navigation.subprocess.run") as mock_run:
            from leap.monitor.navigation import _copy_to_clipboard
            _copy_to_clipboard("hello")
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "xclip"

    def test_falls_back_to_xsel(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("leap.monitor.navigation.sys.platform", "linux")
        monkeypatch.setattr(
            "leap.monitor.navigation.shutil.which",
            lambda name: "/usr/bin/xsel" if name == "xsel" else None,
        )
        with patch("leap.monitor.navigation.subprocess.run") as mock_run:
            from leap.monitor.navigation import _copy_to_clipboard
            _copy_to_clipboard("hello")
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "xsel"

    def test_no_op_when_neither_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("leap.monitor.navigation.sys.platform", "linux")
        monkeypatch.setattr("leap.monitor.navigation.shutil.which", lambda _: None)
        with patch("leap.monitor.navigation.subprocess.run") as mock_run:
            from leap.monitor.navigation import _copy_to_clipboard
            _copy_to_clipboard("hello")  # must not raise
        mock_run.assert_not_called()
