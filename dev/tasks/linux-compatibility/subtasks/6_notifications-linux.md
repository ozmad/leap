# Subtask 6: Notifications Linux Path

## Parent Task
linux-compatibility

## Description
Replace `NSBeep`/`NSSound` in `notifications_dialog.py` with `QApplication.beep()` on
Linux. Guard `UNUserNotificationCenter` usage in `pr_display_mixin.py` and `app.py`
with the `_HAS_COCOA` sentinel (already set by Subtask 2). Add a best-effort D-Bus
desktop notification sender for Linux.

## Scope
- `src/leap/monitor/dialogs/notifications_dialog.py` — `_play_sound()` method
- `src/leap/monitor/_mixins/pr_display_mixin.py` — `_setup_modern_notifications()` and
  notification-dispatch methods
- `src/leap/monitor/app.py` — any `_HAS_COCOA`-gated macOS notification code

No new test file required for this subtask — the import guard tests in Subtask 2 cover
the sentinel. A smoke test (calling `_play_sound()` with a mock QApplication) should be
added to `test_platform_imports.py` as an additional case if straightforward.

## Requirements Addressed
- FR-6 (partial — notifications), FR-7 (partial — notification guard)
- SC-6, SC-7

## Technical Context

### notifications_dialog.py — `_play_sound()`

Current code (lines 538–548):
```python
try:
    NSBeep()
except Exception:
    try:
        url = NSURL.fileURLWithPath_(sound_name)
        sound = NSSound.alloc().initWithContentsOfURL_byReference_(url, True)
        ...
    except Exception:
        sound = NSSound.soundNamed_(sound_name)
        ...
```

After Subtask 2, `from AppKit import NSBeep, NSSound` is wrapped with `_HAS_NOTIFICATIONS`
sentinel. The guard in `_play_sound()`:
```python
def _play_sound(self, sound_name: str) -> None:
    if _HAS_NOTIFICATIONS:
        # existing NSBeep / NSSound path
        ...
        return
    # Linux: use Qt
    from PyQt5.QtWidgets import QApplication   # already imported at module top
    QApplication.beep()
```

Note: `QApplication` is already imported in the monitor codebase. Check the top of
`notifications_dialog.py` — if not already imported, it will be after the dialog
inherits from the broader monitor import chain. Add it to the module top imports if
missing.

### pr_display_mixin.py — notification dispatch

After Subtask 2, `_HAS_COCOA = False` on Linux. The methods that call
`UNUserNotificationCenter`, `NSUserNotification`, `NSUserNotificationCenter` need:
```python
def _setup_modern_notifications(self) -> None:
    if not _HAS_COCOA:
        return
    # existing UNUserNotificationCenter setup ...

def _send_notification(self, title: str, body: str) -> None:
    if not _HAS_COCOA:
        self._send_dbus_notification(title, body)
        return
    # existing macOS notification path ...

def _send_dbus_notification(self, title: str, body: str) -> None:
    """Send a desktop notification via D-Bus (Linux)."""
    try:
        import dbus  # optional; graceful skip if not installed
        bus = dbus.SessionBus()
        notify = bus.get_object(
            'org.freedesktop.Notifications',
            '/org/freedesktop/Notifications',
        )
        iface = dbus.Interface(notify, 'org.freedesktop.Notifications')
        iface.Notify('Leap Monitor', 0, '', title, body, [], {}, 5000)
    except Exception:
        pass  # dbus not available or DE doesn't support it — silently skip
```

`dbus` (python-dbus) is an optional system package on Linux. It is NOT added to
`pyproject.toml` as a required dep — the `except Exception` fallback handles absence.
The import of `dbus` must live at module top level inside a `try/except ImportError`
block with a `_HAS_DBUS = False` sentinel.

### app.py

After Subtask 2, `NSAppearance` (dark mode detection) is behind `_HAS_COCOA`. The
method that calls it should check the sentinel:
```python
def _apply_macos_appearance(self) -> None:
    if not _HAS_COCOA:
        return
    # existing NSAppearance code
```

Qt's `QPalette` already correctly reflects the system dark/light theme on Linux — no
additional code needed; just the guard to prevent the NSAppearance call from crashing.

## Acceptance Criteria
- AC-1: `_play_sound()` on Linux calls `QApplication.beep()` and does not crash,
  regardless of whether pyobjc is installed.
- AC-2: `_setup_modern_notifications()` on Linux returns early without crashing.
- AC-3: `_send_notification()` on Linux attempts D-Bus; silently no-ops if `dbus`
  module is absent or the D-Bus call fails.
- AC-4: On macOS, NSBeep/NSSound and UNUserNotificationCenter paths are completely
  unchanged.
- AC-5: `make test` passes on macOS (SC-13).

## Dependencies
- Depends on: Subtask 2 (sentinels must be in place before these guards are meaningful)
- Must not break: macOS notification delivery (UNUserNotificationCenter, NSBeep/NSSound)

## Estimated Complexity
S — mostly `if not _HAS_COCOA: return` guards + one small Linux sound replacement.
