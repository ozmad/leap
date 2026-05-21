"""Verify that macOS-only dependencies carry sys_platform == 'darwin' markers.

This test parses pyproject.toml directly so it catches any future dep that
is added without a platform marker.  It does not require the leap package to
be imported.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).parent.parent.parent / "pyproject.toml"

MACOS_ONLY_PREFIXES = ("pyobjc-",)
MACOS_ONLY_EXACT = {"py2app", "gnureadline"}

EXPECTED_MARKER = "sys_platform == 'darwin'"


def _all_deps(data: dict) -> dict[str, object]:
    """Collect every dependency from all groups into {name: value}."""
    deps: dict[str, object] = {}
    poetry = data.get("tool", {}).get("poetry", {})
    # Core deps
    deps.update(poetry.get("dependencies", {}))
    # Group deps
    for group in poetry.get("group", {}).values():
        deps.update(group.get("dependencies", {}))
    return deps


def test_macos_only_deps_have_platform_markers() -> None:
    data = tomllib.loads(PYPROJECT.read_text())
    deps = _all_deps(data)

    missing: list[str] = []
    for name, value in deps.items():
        name_lower = name.lower()
        is_macos_only = (
            any(name_lower.startswith(p) for p in MACOS_ONLY_PREFIXES)
            or name_lower in MACOS_ONLY_EXACT
        )
        if not is_macos_only:
            continue

        if isinstance(value, dict):
            marker = value.get("markers", "")
        else:
            marker = ""

        if EXPECTED_MARKER not in marker:
            missing.append(name)

    assert not missing, (
        f"macOS-only deps missing '{EXPECTED_MARKER}' marker: {missing}"
    )
