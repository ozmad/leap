# Subtask 2: PyObjC Import Guards

## Parent Task
linux-compatibility

## Description
Wrap all unconditional PyObjC module-level imports in `try/except ImportError` blocks
with `_HAS_COCOA` / `HAS_APPKIT` sentinels in the four files that currently crash on
Linux at import time. Add `test_platform_imports.py` covering both branches for each
file.

## Scope
- `src/leap/monitor/app.py` — lines 18–23
- `src/leap/monitor/navigation.py` — lines 20–31
- `src/leap/monitor/_mixins/pr_display_mixin.py` — lines 10–12
- `src/leap/monitor/dialogs/notifications_dialog.py` — lines 7–8
- `tests/unit/test_platform_imports.py` — new file

No other files touched. This subtask does NOT add Linux *behaviour* — only prevents
import crashes. Callers that use `_HAS_COCOA`-gated APIs already skip gracefully on
False; any that don't will be fixed in the relevant later subtask.

## Requirements Addressed
- FR-5
- SC-4, SC-5, SC-6, SC-7, SC-14, SC-18

## Technical Context
Follow the exact pattern from `permissions.py` (the established project model):

```python
try:
    import objc
    from AppKit import NSAppearance, NSApplication, NSEvent, NSImage, NSKeyDownMask, NSWindowStyleMaskFullSizeContentView
    from Foundation import NSDate, NSMakeRect, NSRunLoop
    _HAS_COCOA = True
except ImportError:  # pragma: no cover — non-macOS / missing pyobjc
    _HAS_COCOA = False
```

**app.py**: uses `NSAppearance` for dark-mode detection (in `_apply_theme`) and
`NSApplication`/`NSEvent` for global keyboard shortcut handling. On Linux these code
paths are already Qt-based or can be skipped; they are already inside method bodies
that can be guarded with `if not _HAS_COCOA: return`. No behaviour change yet — just
the sentinel.

**navigation.py**: imports 4 frameworks (`AppKit`, `ApplicationServices`,
`CoreFoundation`, `Quartz`). Wrap all four in one try/except block → single
`_HAS_COCOA` sentinel. The 13 call sites that use these symbols are guarded in Subtask 5.

**pr_display_mixin.py**: imports `objc`, `AppKit` (NSApplication, NSImage),
`Foundation` (NSDictionary, NSObject, NSSet, NSUserNotification,
NSUserNotificationCenter). Wrap → `_HAS_COCOA`. Call sites guarded in Subtask 6.

**notifications_dialog.py**: imports `AppKit` (NSBeep, NSSound) and `Foundation`
(NSURL). These are used inline in `_play_sound()`. Wrap → `_HAS_NOTIFICATIONS`.
(Separate sentinel name because this file doesn't use the full Cocoa stack.) Call site
guarded in Subtask 6.

### Test pattern (monkeypatch sys.modules)
```python
import importlib, sys

def test_hAS_cocoa_true_when_pyobjc_available(monkeypatch):
    # Arrange: ensure objc is importable (it is on macOS; mock it on Linux)
    fake_objc = types.ModuleType('objc')
    # ... set up minimal fakes for AppKit, Foundation symbols ...
    monkeypatch.setitem(sys.modules, 'objc', fake_objc)
    # Force reimport
    mod = importlib.reload(importlib.import_module('leap.monitor.app'))
    assert mod._HAS_COCOA is True

def test_hAS_cocoa_false_when_pyobjc_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, 'objc', None)   # None → ImportError on import
    mod = importlib.reload(importlib.import_module('leap.monitor.app'))
    assert mod._HAS_COCOA is False
```

Use `importlib.reload` after monkeypatching `sys.modules` so the sentinel is
re-evaluated. Clean up with `monkeypatch` (automatic teardown).

## Acceptance Criteria
- AC-1: `python -c "from leap.monitor.app import MonitorWindow"` exits 0 on Linux
  (pyobjc not installed).
- AC-2: `python -c "from leap.monitor.navigation import open_terminal_with_command"`
  exits 0 on Linux.
- AC-3: `python -c "from leap.monitor._mixins.pr_display_mixin import PRDisplayMixin"`
  exits 0 on Linux.
- AC-4: `python -c "from leap.monitor.dialogs.notifications_dialog import NotificationsDialog"`
  exits 0 on Linux.
- AC-5: `test_platform_imports.py` passes: for each of the 4 files, two cases —
  sentinel=True when mocked importable, sentinel=False when mocked missing, no exception
  in either case.
- AC-6: On macOS, all four imports still work and sentinels are True (verified by
  `make test` — no regressions).

## Dependencies
- Depends on: Subtask 1 (pyproject markers, so the test environment is consistent)
- Must not break: any existing caller that tests `_HAS_COCOA` before calling macOS APIs
  (those callers already work; we just need the sentinel to still be True on macOS)

## Estimated Complexity
M — four files, mechanical wrapping, but requires careful testing of both branches.
