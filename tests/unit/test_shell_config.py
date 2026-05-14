"""Tests for configure-shell-helper.sh.

Covers AC-1..AC-6 from subtask 7 (linux-compatibility):
  (a) ~/.leap.zshrc exists and contains export LEAP_PROJECT_DIR
  (b) ~/.zshrc contains exactly one source ... .leap.zshrc line
  (c) Re-running doesn't duplicate the source line
  (d) Legacy START/END block migrated; migration notice printed
  (e) Unknown shell exits 0, prints warning, no files changed
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

# Path to the script under test.
_SCRIPT = Path(__file__).parents[2] / "src" / "scripts" / "configure-shell-helper.sh"
# A fake repo path we pass as the positional arg to avoid 'git rev-parse' calls.
_FAKE_REPO = "/tmp/fake-leap-repo"


def _run(home: Path, shell: str = "/bin/zsh", extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = {
        "HOME": str(home),
        "SHELL": shell,
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(_SCRIPT), str(_FAKE_REPO)],
        env=env,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# (a) + (b) Fresh install — zsh
# ---------------------------------------------------------------------------

class TestFreshInstallZsh:
    def test_leap_rc_created_with_export(self, tmp_path: Path) -> None:
        result = _run(tmp_path)
        assert result.returncode == 0, result.stderr
        leap_rc = tmp_path / ".leap.zshrc"
        assert leap_rc.exists(), "~/.leap.zshrc should be created"
        content = leap_rc.read_text()
        assert "export LEAP_PROJECT_DIR=" in content

    def test_main_rc_contains_source_line(self, tmp_path: Path) -> None:
        _run(tmp_path)
        zshrc = tmp_path / ".zshrc"
        assert zshrc.exists(), "~/.zshrc should be created (source line)"
        content = zshrc.read_text()
        source_lines = [l for l in content.splitlines() if ".leap.zshrc" in l]
        assert len(source_lines) >= 1, "At least one source line expected"

    def test_leap_rc_contains_leap_function(self, tmp_path: Path) -> None:
        _run(tmp_path)
        content = (tmp_path / ".leap.zshrc").read_text()
        assert "leap()" in content or "leap (" in content


# ---------------------------------------------------------------------------
# (c) Idempotency — re-running doesn't duplicate the source line
# ---------------------------------------------------------------------------

class TestIdempotencyZsh:
    def test_source_line_not_duplicated(self, tmp_path: Path) -> None:
        _run(tmp_path)
        _run(tmp_path)  # second run
        zshrc = tmp_path / ".zshrc"
        content = zshrc.read_text()
        source_lines = [l for l in content.splitlines() if ".leap.zshrc" in l]
        assert len(source_lines) == 1, (
            f"Expected exactly 1 source line, got {len(source_lines)}: {source_lines}"
        )


# ---------------------------------------------------------------------------
# (d) Legacy START/END block migration
# ---------------------------------------------------------------------------

class TestLegacyMigration:
    def test_start_end_block_removed_and_source_added(self, tmp_path: Path) -> None:
        zshrc = tmp_path / ".zshrc"
        zshrc.write_text(
            "# some existing config\n"
            "\n"
            "# ===== Leap Configuration START - DO NOT REMOVE =====\n"
            'export LEAP_PROJECT_DIR="/old/path"\n'
            "\n"
            "leap() {\n"
            '    "$LEAP_PROJECT_DIR/src/scripts/leap-select.sh" "$@"\n'
            "}\n"
            "# ===== Leap Configuration END - DO NOT REMOVE =====\n"
        )
        result = _run(tmp_path)
        assert result.returncode == 0, result.stderr

        content = zshrc.read_text()
        assert "Leap Configuration START" not in content, "Legacy block should be removed"
        assert ".leap.zshrc" in content, "Source line should be added"

    def test_migration_notice_printed(self, tmp_path: Path) -> None:
        zshrc = tmp_path / ".zshrc"
        zshrc.write_text(
            "# ===== Leap Configuration START - DO NOT REMOVE =====\n"
            'export LEAP_PROJECT_DIR="/old"\n'
            "# ===== Leap Configuration END - DO NOT REMOVE =====\n"
        )
        result = _run(tmp_path)
        # Migration notice should appear in stdout (script uses -e with color codes)
        assert "Migrated" in result.stdout or "Migrated" in result.stderr

    def test_new_config_in_leap_rc_not_main_rc(self, tmp_path: Path) -> None:
        zshrc = tmp_path / ".zshrc"
        zshrc.write_text(
            "# ===== Leap Configuration START - DO NOT REMOVE =====\n"
            'export LEAP_PROJECT_DIR="/old"\n'
            "# ===== Leap Configuration END - DO NOT REMOVE =====\n"
        )
        _run(tmp_path)
        leap_rc_content = (tmp_path / ".leap.zshrc").read_text()
        assert "export LEAP_PROJECT_DIR=" in leap_rc_content


# ---------------------------------------------------------------------------
# (e) Unknown shell — exits 0, warning printed, no rc files changed
# ---------------------------------------------------------------------------

class TestUnknownShell:
    def test_exits_zero_and_warns(self, tmp_path: Path) -> None:
        result = _run(tmp_path, shell="/bin/fish")
        assert result.returncode == 0, "Should exit 0 for unknown shell"
        assert "Unknown shell" in result.stdout or "Unknown shell" in result.stderr

    def test_does_not_create_any_rc_files(self, tmp_path: Path) -> None:
        _run(tmp_path, shell="/bin/fish")
        assert not (tmp_path / ".leap.zshrc").exists()
        assert not (tmp_path / ".leap.bashrc").exists()
        assert not (tmp_path / ".zshrc").exists()
        assert not (tmp_path / ".bashrc").exists()


# ---------------------------------------------------------------------------
# Fresh install — bash
# ---------------------------------------------------------------------------

class TestFreshInstallBash:
    def test_leap_bashrc_created(self, tmp_path: Path) -> None:
        result = _run(tmp_path, shell="/bin/bash")
        assert result.returncode == 0, result.stderr
        leap_rc = tmp_path / ".leap.bashrc"
        assert leap_rc.exists(), "~/.leap.bashrc should be created"
        content = leap_rc.read_text()
        assert "export LEAP_PROJECT_DIR=" in content

    def test_bashrc_contains_source_line(self, tmp_path: Path) -> None:
        _run(tmp_path, shell="/bin/bash")
        bashrc = tmp_path / ".bashrc"
        assert bashrc.exists()
        content = bashrc.read_text()
        assert ".leap.bashrc" in content
