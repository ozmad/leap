"""Tests for :meth:`CLIProvider.hooks_installed` across all four
built-in providers.

The check is the symmetric inverse of ``configure_hooks()`` — it
verifies both that the hook script exists in ``hook_config_dir`` AND
that the CLI's settings file references ``leap-hook.sh``.  Tests
monkey-patch ``$HOME`` to an isolated tmp dir so they never touch
the real ``~/.claude``, ``~/.codex``, ``~/.cursor``, or ``~/.gemini``.

Each provider is exercised through five cases:

1. Empty home → ``hooks_installed() == False``.
2. After running ``configure_hooks()`` → ``True``.
3. Hook script wiped, settings file kept → ``False``.
4. Settings file wiped, hook script kept → ``False``.
5. Settings file corrupt (invalid JSON / TOML) → ``False`` (no raise).

For Codex specifically: a sixth case verifies that without the
``codex_hooks`` feature flag in ``config.toml`` we treat it as
"not installed" (Codex 0.121+ silently ignores ``hooks.json``
otherwise — better to flag it loudly via the gate).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

import pytest

from leap.cli_providers.claude import ClaudeProvider
from leap.cli_providers.codex import CodexProvider
from leap.cli_providers.cursor_agent import CursorAgentProvider
from leap.cli_providers.gemini import GeminiProvider


# --------------------------------------------------------------------------
# Fixture: isolated $HOME so providers see an empty config dir tree
# --------------------------------------------------------------------------

@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point $HOME at a tmp dir.  Re-imports module-level constants in
    each provider so they re-evaluate ``Path.home()``.

    The four providers cache their config-dir constants at import
    time (``CODEX_CONFIG_DIR``, ``GEMINI_SETTINGS_FILE``, etc.).
    Monkey-patching them is the cleanest way to redirect file I/O
    without touching the provider source.
    """
    monkeypatch.setenv("HOME", str(tmp_path))

    # Patch every cached constant to point at the new home.
    from leap.cli_providers import codex as codex_mod
    from leap.cli_providers import cursor_agent as cursor_mod
    from leap.cli_providers import gemini as gemini_mod

    monkeypatch.setattr(codex_mod, "CODEX_CONFIG_DIR", tmp_path / ".codex")
    monkeypatch.setattr(codex_mod, "CODEX_HOOKS_FILE", tmp_path / ".codex" / "hooks.json")
    monkeypatch.setattr(cursor_mod, "CURSOR_CONFIG_DIR", tmp_path / ".cursor")
    monkeypatch.setattr(cursor_mod, "CURSOR_HOOKS_FILE", tmp_path / ".cursor" / "hooks.json")
    monkeypatch.setattr(gemini_mod, "GEMINI_CONFIG_DIR", tmp_path / ".gemini")
    monkeypatch.setattr(gemini_mod, "GEMINI_SETTINGS_FILE", tmp_path / ".gemini" / "settings.json")

    yield tmp_path


# Path inside the source tree — used as the hook script source for
# configure_hooks(); we don't actually run the hook, just install its
# path into settings files.
_REPO_HOOK_SCRIPT = (
    Path(__file__).resolve().parents[2] / "src" / "scripts" / "leap-hook.sh"
)


def _install_hook_script(provider, isolated_home: Path) -> Path:
    """Copy the repo's leap-hook.sh into the provider's hook_config_dir
    so configure_hooks() can install a settings file that references
    a real on-disk path.  Returns the destination path."""
    hook_dir = provider.hook_config_dir
    hook_dir.mkdir(parents=True, exist_ok=True)
    dest = hook_dir / "leap-hook.sh"
    dest.write_text(_REPO_HOOK_SCRIPT.read_text())
    dest.chmod(0o755)
    return dest


# --------------------------------------------------------------------------
# Generic per-provider test parametrisation
# --------------------------------------------------------------------------

PROVIDERS = [
    pytest.param(ClaudeProvider, id="claude"),
    pytest.param(CodexProvider, id="codex"),
    pytest.param(CursorAgentProvider, id="cursor-agent"),
    pytest.param(GeminiProvider, id="gemini"),
]


@pytest.mark.parametrize("provider_cls", PROVIDERS)
def test_empty_home_returns_false(provider_cls, isolated_home: Path) -> None:
    provider = provider_cls()
    assert provider.hooks_installed() is False


@pytest.mark.parametrize("provider_cls", PROVIDERS)
def test_after_configure_hooks_returns_true(
    provider_cls, isolated_home: Path
) -> None:
    provider = provider_cls()
    dest = _install_hook_script(provider, isolated_home)
    provider.configure_hooks(str(dest))
    assert provider.hooks_installed() is True


@pytest.mark.parametrize("provider_cls", PROVIDERS)
def test_hook_script_wiped_returns_false(
    provider_cls, isolated_home: Path
) -> None:
    provider = provider_cls()
    dest = _install_hook_script(provider, isolated_home)
    provider.configure_hooks(str(dest))
    assert provider.hooks_installed() is True
    dest.unlink()
    assert provider.hooks_installed() is False


@pytest.mark.parametrize(
    "provider_cls,settings_relpath",
    [
        (ClaudeProvider, ".claude/settings.json"),
        (CodexProvider, ".codex/hooks.json"),
        (CursorAgentProvider, ".cursor/hooks.json"),
        (GeminiProvider, ".gemini/settings.json"),
    ],
    ids=["claude", "codex", "cursor-agent", "gemini"],
)
def test_settings_file_wiped_returns_false(
    provider_cls, settings_relpath: str, isolated_home: Path
) -> None:
    provider = provider_cls()
    dest = _install_hook_script(provider, isolated_home)
    provider.configure_hooks(str(dest))
    assert provider.hooks_installed() is True
    (isolated_home / settings_relpath).unlink()
    assert provider.hooks_installed() is False


@pytest.mark.parametrize(
    "provider_cls,settings_relpath",
    [
        (ClaudeProvider, ".claude/settings.json"),
        (CodexProvider, ".codex/hooks.json"),
        (CursorAgentProvider, ".cursor/hooks.json"),
        (GeminiProvider, ".gemini/settings.json"),
    ],
    ids=["claude", "codex", "cursor-agent", "gemini"],
)
def test_corrupt_settings_returns_false_not_raise(
    provider_cls, settings_relpath: str, isolated_home: Path
) -> None:
    provider = provider_cls()
    dest = _install_hook_script(provider, isolated_home)
    provider.configure_hooks(str(dest))
    # Replace settings file with garbage — must NOT raise.
    settings_path = isolated_home / settings_relpath
    settings_path.write_text("{not valid json")
    assert provider.hooks_installed() is False


# --------------------------------------------------------------------------
# Defensive: weird-but-valid-JSON shapes in settings files must not raise.
# The session-start gate calls hooks_installed() on every server start, so
# a TypeError or KeyError here would crash the user's session with no clear
# remediation.  Returning False is the correct behaviour — the gate then
# fires its friendly error pointing at `leap --reconfigure`.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "provider_cls,settings_relpath,corrupt_payload",
    [
        # Claude: command field is an int (non-string) — `in` on int raises.
        (
            ClaudeProvider, ".claude/settings.json",
            {"hooks": {"Stop": [{"hooks": [{"command": 42}]}]}},
        ),
        # Codex: hooks list at the entry level is a string instead of list.
        (
            CodexProvider, ".codex/hooks.json",
            {"hooks": {"Stop": [{"hooks": "not-a-list"}]}},
        ),
        # Cursor: command field is None.
        (
            CursorAgentProvider, ".cursor/hooks.json",
            {"version": 1, "hooks": {"stop": [{"command": None}]}},
        ),
        # Gemini: top-level hooks is a list instead of dict.
        (
            GeminiProvider, ".gemini/settings.json",
            {"hooks": ["this should be a dict"]},
        ),
    ],
    ids=["claude-int-command", "codex-string-hooks", "cursor-none-command", "gemini-list-hooks"],
)
def test_weird_but_valid_json_returns_false_not_raise(
    provider_cls, settings_relpath, corrupt_payload, isolated_home: Path
) -> None:
    """Settings files written by a third party (or hand-edited) might
    have valid JSON but the wrong shape.  ``hooks_installed()`` must
    cope without raising — the gate would otherwise crash with a
    TypeError instead of pointing the user at ``leap --reconfigure``.
    """
    import json as _json

    provider = provider_cls()
    # Install hook script so the first half of the check passes.
    hook_dir = provider.hook_config_dir
    hook_dir.mkdir(parents=True, exist_ok=True)
    (hook_dir / "leap-hook.sh").write_text("#!/bin/sh\n")

    settings_path = isolated_home / settings_relpath
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(_json.dumps(corrupt_payload))

    # Codex extra-needs the feature flag in config.toml.
    if provider_cls is CodexProvider:
        (isolated_home / ".codex" / "config.toml").write_text(
            "[features]\ncodex_hooks = true\n"
        )

    # Must return False, must not raise.
    assert provider.hooks_installed() is False


# --------------------------------------------------------------------------
# Codex-specific: missing feature flag in config.toml → False
# --------------------------------------------------------------------------

def test_codex_missing_feature_flag_returns_false(isolated_home: Path) -> None:
    """Codex 0.121+ silently ignores hooks.json without
    ``codex_hooks = true`` in config.toml — gate must catch this."""
    provider = CodexProvider()
    dest = _install_hook_script(provider, isolated_home)
    provider.configure_hooks(str(dest))
    assert provider.hooks_installed() is True

    # Wipe the feature flag from config.toml.  configure_hooks() puts
    # it under ``[features]``; we just truncate the whole file.
    config_toml = isolated_home / ".codex" / "config.toml"
    config_toml.write_text("# no feature flag here\n")
    assert provider.hooks_installed() is False


# --------------------------------------------------------------------------
# base_type defaults — built-in providers return their own name so the
# session-start gate's ``get_provider(provider.base_type).hooks_installed()``
# resolves to themselves.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "provider_cls,expected",
    [
        (ClaudeProvider, "claude"),
        (CodexProvider, "codex"),
        (CursorAgentProvider, "cursor-agent"),
        (GeminiProvider, "gemini"),
    ],
)
def test_built_in_providers_base_type_is_own_name(
    provider_cls, expected: str
) -> None:
    assert provider_cls().base_type == expected


# --------------------------------------------------------------------------
# CustomCLIProvider delegation — a custom Claude wrapper inherits the
# base's hooks_installed() result via __getattribute__ delegation.
# --------------------------------------------------------------------------

def test_custom_cli_provider_inherits_hooks_installed(
    isolated_home: Path,
) -> None:
    """A custom CLI wrapping ClaudeProvider should report
    ``hooks_installed()`` based on the Claude base's state, not its
    own.  This is the entire reason custom providers don't need to
    implement the method themselves.
    """
    from leap.cli_providers.registry import CustomCLIProvider

    base = ClaudeProvider()
    custom = CustomCLIProvider(
        custom_id="my-claude-wrapper",
        base_provider=base,
        custom_display_name="My Claude Wrapper",
    )

    # Empty home — both should be False.
    assert custom.hooks_installed() is False
    assert base.hooks_installed() is False

    # Install hooks for the base (via the custom — they share storage).
    dest = _install_hook_script(base, isolated_home)
    base.configure_hooks(str(dest))

    # Custom now reports True too, via delegation.
    assert base.hooks_installed() is True
    assert custom.hooks_installed() is True

    # base_type — custom returns the base's name (delegation), not
    # its own custom id.
    assert custom.base_type == "claude"
