# Plan: Linux Compatibility

## Investigation

### Affected modules

| File | Issue | Strategy |
|------|-------|----------|
| `pyproject.toml` | pyobjc-* and py2app unconditional | Add `markers = "sys_platform == 'darwin'"` |
| `monitor/app.py` | `import objc`, `from AppKit`, `from Foundation` at module top, no guard | Wrap in `try/except ImportError`; set `_HAS_COCOA` |
| `monitor/navigation.py` | `import AppKit`, `from ApplicationServices/CoreFoundation/Quartz` at module top; 8× osascript, 2× pbcopy, 1× mdfind | Wrap imports; guard each call with `sys.platform == 'darwin'`; add Linux VS Code + WezTerm paths |
| `monitor/_mixins/pr_display_mixin.py` | `import objc`, `from AppKit`, `from Foundation` at module top | Wrap in try/except; guard UNUserNotificationCenter usage |
| `monitor/dialogs/notifications_dialog.py` | `from AppKit import NSBeep, NSSound`, `from Foundation import NSURL` | Wrap; replace with `QApplication.beep()` on Linux |
| `monitor/sleep_guard.py` | `_CAFFEINATE_PATH` hardcoded; `_PMSET_PATH` hardcoded | `sys.platform == 'darwin'` guard; add `systemd-inhibit` Linux paths |
| `client/image_handler.py` | 2× osascript for clipboard | Guard; add xclip→xsel→None Linux path |
| `server/server.py` | `HAS_APPKIT` guard already exists | Clipboard *write* path needs Linux variant via Qt clipboard |
| `scripts/configure-shell-helper.sh` | Writes block into `~/.zshrc`/`~/.bashrc` directly | Write to `~/.leap.zshrc`/`~/.leap.bashrc`; source line in main rc |
| `scripts/configure_wezterm_csi_u.py` | `mdfind`, `/Applications/WezTerm.app` | Add `sys.platform` guard; replace with `which wezterm` on Linux |
| `scripts/configure_iterm2_csi_u.py` | iTerm2 is macOS-only | Exit 0 silently on non-macOS at the top of the script |
| `Makefile` | `install` depends on `check-macos`; uses `tccutil`, `open x-apple:`, `osascript` | Remove hard dep; wrap macOS-only steps in `uname == Darwin` guards with skip messages |

### Existing patterns to follow

`permissions.py` (lines 18–28) and `server.py` (lines 23–33) already demonstrate
the correct pattern:
```python
try:
    import objc
    from AppKit import ...
    _HAS_COCOA = True
except ImportError:  # pragma: no cover — non-macOS / missing pyobjc
    _HAS_COCOA = False
```
Every new guard must follow this exact form — `ImportError` only, sentinel immediately
after the import block, `# pragma: no cover` on the except line (we test via monkeypatch,
not by running on an actually non-macOS box in CI).

### Risks

- `navigation.py` is ~1900 lines with 13 macOS call sites scattered across multiple
  unrelated functions. Individual guards are simple but the file is large. Mitigated by
  working function-by-function rather than a single bulk edit.
- `app.py` uses `NSAppearance` for theme detection. Qt's dark-mode detection via
  `QPalette.color(QPalette.Window)` luminance is a drop-in; needs brief testing.
- D-Bus notification availability on Linux is DE-dependent. The fallback (no
  notifications) must leave the rest of the monitor fully functional.
- Shell config migration: users who hand-edited the `START/END` block will lose those
  edits. Acceptable — the block was always documented as non-editable.

## Technical Decisions

- **TD-1 Sentinel naming**: Use `_HAS_COCOA` for files that import from multiple PyObjC
  frameworks (matching `permissions.py`). Use `HAS_APPKIT` only in files that import
  only AppKit (matching `server.py`). No new sentinel names.
- **TD-2 Platform guard form**: Always `if sys.platform == 'darwin':` for the macOS
  path, with an `else:` for the Linux alternative. Never `if sys.platform != 'linux':`.
  This ensures the macOS path is never accidentally dropped for a future third platform.
- **TD-3 Linux clipboard**: Use `subprocess(['xclip', '-selection', 'clipboard', ...])`,
  falling back to `xsel`, falling back to None/False. No new Python package required.
- **TD-4 Linux sleep prevention**: `systemd-inhibit --what=idle --who=LeapMonitor
  --why="Leap session running" --mode=block sleep <monitor-pid>` wraps the monitor
  process. For `LidCloseGuard`, use `systemd-inhibit --what=sleep`. Both are
  best-effort: OSError is caught and logged, not raised.
- **TD-5 VS Code Linux navigation**: Replace the `osascript` window-focus block with
  `subprocess(['code', '--reuse-window', project_path])` on Linux. The
  `~/.leap-terminal-request` file-based extension trigger is already cross-platform and
  requires no change.
- **TD-6 WezTerm Linux discovery**: Replace `mdfind` with `shutil.which('wezterm')`.
  The `wezterm cli` navigation commands are already cross-platform.
- **TD-7 Shell config**: `~/.leap.zshrc` / `~/.leap.bashrc` written atomically (tmp +
  rename). Main rc gets `[ -f "$HOME/.leap.zshrc" ] && source "$HOME/.leap.zshrc"` —
  idempotent because `grep -q` checks before appending.
- **TD-8 Makefile platform detection**: `$(UNAME_S) := $(shell uname -s)` at the top;
  macOS-only targets guard with `ifeq ($(UNAME_S),Darwin)` or inline
  `[ "$$(uname)" = "Darwin" ] &&`. The `check-macos` target is repurposed to a
  *warning* (not an error) so `install` proceeds on Linux.
- **TD-9 Notifications dialog sound**: `QApplication.beep()` requires no deps and works
  on all platforms. Use it unconditionally on Linux; NSBeep/NSSound only on macOS.

## Design Principles Applied

- **Additive-only for Linux**: no existing macOS code is removed or altered in
  behaviour, only guarded. The macOS path is always the `if sys.platform == 'darwin'`
  branch.
- **Fail-open on missing Linux tools**: if xclip, systemd-inhibit, or wezterm are
  absent the feature silently no-ops rather than erroring. Same philosophy as the
  existing SleepGuard caffeinate failure path (already logs + swallows OSError).
- **Both branches tested**: every platform guard has a unit test covering macOS (mock
  pyobjc available / `sys.platform = darwin`) and Linux (mock pyobjc missing /
  `sys.platform = linux`). NFR-8 is a hard requirement, not optional.

## Task Breakdown

### Subtask 1: pyproject.toml — platform markers
See `subtasks/1_pyproject-markers.md`

### Subtask 2: PyObjC import guards
See `subtasks/2_pyobjc-import-guards.md`

### Subtask 3: SleepGuard Linux path
See `subtasks/3_sleep-guard-linux.md`

### Subtask 4: Clipboard Linux path
See `subtasks/4_clipboard-linux.md`

### Subtask 5: Navigation Linux path (VS Code + WezTerm + osascript guards)
See `subtasks/5_navigation-linux.md`

### Subtask 6: Notifications Linux path
See `subtasks/6_notifications-linux.md`

### Subtask 7: Shell config — ~/.leap.zshrc
See `subtasks/7_shell-config.md`

### Subtask 8: Makefile + configure scripts Linux-aware
See `subtasks/8_makefile-linux.md`
