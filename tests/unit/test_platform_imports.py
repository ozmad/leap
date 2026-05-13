"""Verify that PyObjC import guards set the correct sentinel on both platforms.

Each module that wraps a PyObjC import in try/except must:
  - Set sentinel = True  when the import succeeds (macOS / pyobjc installed)
  - Set sentinel = False when the import fails  (Linux  / pyobjc missing)
  - Not raise in either case

Tests work by manipulating sys.modules to simulate presence / absence of pyobjc,
then force-reloading the target module so its module-level code re-runs.
"""

from __future__ import annotations

import importlib
import sys
import types
from typing import Iterator

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Names of all PyObjC sub-modules that the monitored files import from.
_PYOBJC_MODULES = [
    "objc",
    "AppKit",
    "Foundation",
    "ApplicationServices",
    "CoreFoundation",
    "Quartz",
]

# Leap monitor modules that are indirectly imported by the target modules.
# We need to keep these out of sys.modules while testing to avoid cascade
# failures from unrelated macOS-only code in transitive imports.
_TARGET_MODULES = [
    "leap.monitor.app",
    "leap.monitor.navigation",
    "leap.monitor._mixins.pr_display_mixin",
    "leap.monitor.dialogs.notifications_dialog",
]


def _make_fake_pyobjc() -> dict[str, types.ModuleType]:
    """Return a minimal set of fake pyobjc modules sufficient for the guards."""
    fake: dict[str, types.ModuleType] = {}
    for name in _PYOBJC_MODULES:
        mod = types.ModuleType(name)
        # Populate every symbol that the import lines reference so that
        # "from AppKit import NSAppearance, ..." doesn't raise AttributeError.
        for attr in [
            # AppKit
            "NSAppearance", "NSApplication", "NSEvent", "NSImage",
            "NSKeyDownMask", "NSWindowStyleMaskFullSizeContentView",
            "NSBeep", "NSSound",
            # Foundation
            "NSDate", "NSMakeRect", "NSRunLoop",
            "NSDictionary", "NSObject", "NSSet",
            "NSUserNotification", "NSUserNotificationCenter",
            "NSURL",
            # ApplicationServices
            "AXIsProcessTrusted", "AXIsProcessTrustedWithOptions",
            "AXUIElementCopyAttributeValue", "AXUIElementCreateApplication",
            "AXUIElementPerformAction", "kAXErrorSuccess",
            # CoreFoundation
            "kCFBooleanTrue",
            # Quartz
            "CGEventCreateKeyboardEvent", "CGEventPost", "CGEventSetFlags",
            "kCGEventFlagMaskCommand", "kCGEventFlagMaskControl",
            "kCGEventFlagMaskShift", "kCGHIDEventTap",
        ]:
            setattr(mod, attr, object())
        fake[name] = mod
    return fake


def _fresh_import(module_name: str) -> types.ModuleType:
    """Remove *module_name* (and all leap.monitor.* that depend on it) from
    sys.modules, then import fresh so module-level code re-runs."""
    # Drop the target and every already-cached module that could re-export it.
    to_drop = [k for k in sys.modules if k == module_name or k.startswith("leap.monitor")]
    for key in to_drop:
        sys.modules.pop(key, None)
    return importlib.import_module(module_name)


# ---------------------------------------------------------------------------
# Parametrised cases: (module, sentinel_attr)
# ---------------------------------------------------------------------------

_CASES = [
    ("leap.monitor.app",                              "_HAS_COCOA"),
    ("leap.monitor.navigation",                       "_HAS_COCOA"),
    ("leap.monitor._mixins.pr_display_mixin",         "_HAS_COCOA"),
    ("leap.monitor.dialogs.notifications_dialog",     "_HAS_NOTIFICATIONS"),
]


@pytest.mark.parametrize("module_name,sentinel", _CASES)
def test_sentinel_false_when_pyobjc_missing(
    module_name: str,
    sentinel: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sentinel is False and no exception is raised when pyobjc is absent."""
    # Block every pyobjc module so the try/except ImportError fires.
    for name in _PYOBJC_MODULES:
        monkeypatch.setitem(sys.modules, name, None)  # None → ImportError on import

    mod = _fresh_import(module_name)

    assert getattr(mod, sentinel) is False


@pytest.mark.parametrize("module_name,sentinel", _CASES)
def test_sentinel_true_when_pyobjc_available(
    module_name: str,
    sentinel: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sentinel is True when pyobjc symbols are importable (macOS / mock)."""
    fake_mods = _make_fake_pyobjc()
    for name, mod in fake_mods.items():
        monkeypatch.setitem(sys.modules, name, mod)

    mod = _fresh_import(module_name)

    assert getattr(mod, sentinel) is True


@pytest.mark.parametrize("module_name,sentinel", _CASES)
def test_import_does_not_raise_when_pyobjc_missing(
    module_name: str,
    sentinel: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Importing the module never raises, regardless of pyobjc availability."""
    for name in _PYOBJC_MODULES:
        monkeypatch.setitem(sys.modules, name, None)

    # Should not raise.
    _fresh_import(module_name)
