# Requirements: Linux Compatibility

## Summary
Leap currently runs exclusively on macOS due to deep dependencies on PyObjC frameworks
(AppKit, ApplicationServices, CoreFoundation, Quartz), macOS-only binaries (osascript,
caffeinate, pmset, pbcopy/pbpaste, mdfind), and a py2app build system. This task makes
**all of Leap** — server, client, CLI providers, and the monitor GUI — run fully on
Ubuntu/Debian Linux. Each macOS subsystem is replaced with its Linux equivalent; nothing
is permanently demoted to "graceful degradation" unless no Linux equivalent exists (e.g.
dock badge on non-Ubuntu desktops). Full IDE navigation parity on Linux is in scope for
VS Code and WezTerm (both have cross-platform CLIs); JetBrains and terminal-level
AppleScript navigation are deferred.

The install also changes the shell config strategy: instead of writing a marked block
directly into `~/.zshrc` / `~/.bashrc`, Leap writes all config to `~/.leap.zshrc` (or
`~/.leap.bashrc`) and adds a single `source "$HOME/.leap.zshrc"` line to the main rc.

## Context
A full audit identified the following blockers by category:

**Critical — crash on import (unconditional PyObjC imports):**
- `src/leap/monitor/navigation.py` — AppKit, ApplicationServices, CoreFoundation, Quartz
- `src/leap/monitor/_mixins/pr_display_mixin.py` — objc, AppKit, Foundation
- `src/leap/monitor/app.py` — objc, AppKit, Foundation
- `src/leap/monitor/dialogs/notifications_dialog.py` — AppKit, Foundation

**Functional blockers — macOS subsystems with Linux equivalents:**

| macOS subsystem | File(s) | Linux replacement |
|---|---|---|
| `NSAppearance` dark mode | `app.py` | Qt `QPalette` (already works) |
| `NSEvent` keyboard | `app.py` | Qt `QKeyEvent` (already works) |
| `UNUserNotificationCenter` | `pr_display_mixin.py` | D-Bus `org.freedesktop.Notifications` |
| `NSPasteboard` / `pbcopy` | `navigation.py`, `server.py` | Qt clipboard / `xclip` / `xsel` |
| `NSBeep` / `NSSound` | `notifications_dialog.py` | `subprocess(['paplay', ...])` or `QSound` |
| `caffeinate` | `sleep_guard.py` | `systemd-inhibit --what=idle` |
| `pmset disablesleep` | `sleep_guard.py` | `systemd-inhibit --what=sleep` |
| `osascript` (terminal nav) | `navigation.py` | `xdotool` / `wmctrl` / terminal CLIs |
| `AXUIElement` accessibility | `navigation.py` | `pyatspi` or `xdotool` |
| `mdfind` / `/Applications` | `navigation.py`, `configure_wezterm_csi_u.py` | `which`, `~/.local/share` paths |
| Dock badge | `dock_badge.py` | D-Bus `com.canonical.Unity.LauncherEntry` (Ubuntu) / skip on other DEs |
| `osascript` (VS Code nav) | `navigation.py` | `code --reuse-window` + existing Leap extension |
| `osascript` (WezTerm nav) | `navigation.py` | `wezterm cli` (cross-platform) |

**Build/install blockers:**
- `pyproject.toml` — pyobjc-* deps unconditional (will fail `poetry install` on Linux)
- `setup.py` — entire file is py2app-specific
- `Makefile` — `install` target gated on `check-macos`; uses `tccutil`, `osascript`
- `configure-shell-helper.sh` — writes directly into `~/.zshrc`/`~/.bashrc` (changing to `~/.leap.zshrc`/`~/.leap.bashrc`)
- `configure_iterm2_csi_u.py` — iTerm2 is macOS-only; skip on Linux
- `configure_wezterm_csi_u.py` — uses `mdfind`; needs Linux path lookup

**Already cross-platform (no changes needed):**
- `server/` — pexpect + Unix sockets
- `client/` — prompt_toolkit + readline
- `cli_providers/` — shell-based
- `utils/` — pure Python (except clipboard helper)
- `slack/` — pure Python

## Functional Requirements

### Core (server + client)
- FR-1: `poetry install` (core group) completes without error on Ubuntu 22.04+.
- FR-2: `leap <tag>` server starts and reaches idle state on Linux.
- FR-3: `leap <tag>` client connects and accepts input on Linux.
- FR-4: All four CLI providers (claude, codex, gemini, cursor-agent) function on Linux.

### Monitor GUI
- FR-5: PyObjC imports in monitor files are wrapped in `try/except ImportError` guards
  with `_HAS_COCOA = False` sentinels (following the pattern already in `permissions.py`
  and `server.py`).
- FR-6: The monitor launches and displays the session table on Linux without crashing.
- FR-7: Desktop notifications on Linux use D-Bus `org.freedesktop.Notifications`
  (via `dbus-python` or `notify2`), guarded by `sys.platform != 'darwin'`.
- FR-8: `SleepGuard` uses `systemd-inhibit --what=idle` on Linux (best-effort; silently
  no-ops if systemd-inhibit is not present). `LidCloseGuard` uses `systemd-inhibit
  --what=sleep` on Linux; the `sudo pmset` path is macOS-only.
- FR-9: Dock badge uses D-Bus `com.canonical.Unity.LauncherEntry` on Linux where
  available; silently skips on DEs that don't support it.
- FR-10: Clipboard image read/write in `image_handler.py` uses `xclip`→`xsel`→degrade
  on Linux. Clipboard image read/write in `server.py` (NSPasteboard) uses Qt clipboard
  or `xclip` on Linux.
- FR-11: `NSBeep`/`NSSound` in `notifications_dialog.py` replaced with `paplay` or
  `QApplication.beep()` on Linux.

### Navigation
- FR-12: VS Code terminal navigation on Linux uses `code --reuse-window` + the existing
  Leap extension (no AppleScript). `detect_supported_ide_for_move()` returns `'VS Code'`
  on Linux when `code` is on PATH.
- FR-13: WezTerm navigation on Linux uses `wezterm cli` (cross-platform; works already).
  The `mdfind`-based WezTerm discovery is replaced with `which wezterm` on Linux.
- FR-14: JetBrains terminal navigation on Linux is deferred — the function no-ops
  gracefully rather than crashing.
- FR-15: macOS app bundle paths (`/Applications`, `~/Applications`,
  `~/Library/Application Support/JetBrains`) are guarded by `sys.platform == 'darwin'`;
  Linux uses `~/.local/share/JetBrains`, `which code`, `which cursor`, etc.

### Build / Install
- FR-16: pyobjc-* and py2app dependencies in `pyproject.toml` carry
  `markers = "sys_platform == 'darwin'"` so they are not installed on Linux.
- FR-17: `make install` on Linux completes without aborting. macOS-only steps (py2app
  build, `tccutil`, Accessibility/Notification prompts, `osascript` app-quit) are
  skipped with an informational message.
- FR-18: `make install-monitor` on Linux prints "Monitor build requires macOS (py2app)"
  and exits 0. The monitor can still be launched with `make run-monitor` (source mode).
- FR-19: `configure_iterm2_csi_u.py` exits 0 silently on Linux (iTerm2 is macOS-only).
- FR-20: `configure_wezterm_csi_u.py` uses `which wezterm` on Linux instead of `mdfind`.
- FR-21: Shell config is written to `~/.leap.zshrc` (zsh) or `~/.leap.bashrc` (bash).
  The main rc file (`~/.zshrc` / `~/.bashrc`) receives only one idempotent line:
  `source "$HOME/.leap.zshrc"` (or `.bashrc`). The legacy `Leap Configuration START/END`
  block is migrated on first run.

## Non-Functional Requirements

- NFR-1: **No macOS regressions.** All platform guards use `sys.platform == 'darwin'`
  (not `!= 'linux'`). macOS behavior is unchanged.
- NFR-2: **Minimal diff.** Prefer wrapping existing code in platform guards over
  rewriting. Linux paths are additive.
- NFR-3: **No new required deps.** `xclip`/`xsel`/`systemd-inhibit`/`xdotool`/`wmctrl`
  are optional system tools — gracefully skipped if absent.
- NFR-4: **Import convention respected.** All imports stay at module top level. Platform-
  specific imports use `try/except ImportError` at module top level only.
- NFR-5: **py2app / setup.py untouched.** The macOS `.app` bundle build is out of scope;
  Linux packaging is deferred.
- NFR-6: **Shell config idempotent.** Re-running `make install` or `make reconfigure`
  regenerates `~/.leap.zshrc` in-place without duplicating the `source` line in the
  main rc.
- NFR-7: **Narrow exception guards.** Every `try/except` around a PyObjC import must
  catch only `ImportError` (not `Exception`), so real errors on macOS are not silenced.
- NFR-8: **Both branches tested.** Every platform dispatch (osascript, caffeinate, pmset,
  clipboard, navigation) must have unit tests covering both the macOS branch
  (`sys.platform == 'darwin'`) and the Linux branch. A guard with only the Linux side
  tested is not acceptable — it could silently break macOS.
- NFR-9: **Sentinel integrity.** After wrapping a PyObjC import in try/except, a test
  must verify that `_HAS_COCOA = True` when the import succeeds (macOS) and
  `_HAS_COCOA = False` when it fails (Linux mock). The macOS value must never become
  False due to a coding mistake in the guard.

## Success Criteria

### Linux functionality
- SC-1: `poetry install` (no extras) exits 0 on a fresh Ubuntu 22.04 environment.
- SC-2: `leap mytag` (server) starts and reaches idle state on Linux.
- SC-3: `leap mytag` (client) connects and accepts input on Linux.
- SC-4: `python -c "from leap.monitor.app import MonitorWindow"` does not raise on Linux.
- SC-5: `python -c "from leap.monitor.navigation import open_terminal_with_command"` does
  not raise on Linux.
- SC-6: `python -c "from leap.monitor._mixins.pr_display_mixin import PRDisplayMixin"`
  does not raise on Linux.
- SC-7: `python -c "from leap.monitor.dialogs.notifications_dialog import NotificationsDialog"`
  does not raise on Linux.
- SC-8: The monitor window opens and shows the session table on Linux (`make run-monitor`).
- SC-9: `make install` on Linux exits 0 (macOS-only steps skipped with a printed notice).
- SC-10: `SleepGuard.start()` on Linux either uses systemd-inhibit or silently no-ops;
  it does not crash.
- SC-11: VS Code terminal navigation is callable on Linux without crashing when `code`
  is on PATH.
- SC-12: Shell config is written to `~/.leap.zshrc` (or `~/.leap.bashrc`) after install;
  only a `source` line is added to the main rc.

### macOS non-regression (must hold after every subtask)
- SC-13: `make test` (full suite) passes on macOS with zero failures or new skips.
- SC-14: On macOS, all PyObjC import guards resolve to `_HAS_COCOA = True` — no guard
  accidentally evaluates False on macOS due to an import-order or scope bug.
- SC-15: On macOS, `osascript` is still invoked for terminal navigation (not accidentally
  blocked by a platform guard). Verified by the navigation unit tests' macOS branch.
- SC-16: On macOS, `SleepGuard` still spawns `caffeinate`; `LidCloseGuard` still calls
  `pmset`. Neither is accidentally no-oped on macOS.
- SC-17: On macOS, `NSPasteboard` / `osascript` clipboard paths are still taken (not
  replaced by xclip/xsel on macOS).

### Unit test coverage (new tests required)
- SC-18: `tests/unit/test_platform_imports.py` — for each file that gains a
  `try/except ImportError` PyObjC guard, two parametrized cases:
  (a) mock the PyObjC module as importable → sentinel is `True`;
  (b) mock it as missing (`ImportError`) → sentinel is `False`, no exception raised.
- SC-19: `tests/unit/test_sleep_guard_platform.py` — four cases:
  (a) macOS + caffeinate present → `caffeinate` subprocess spawned;
  (b) Linux + systemd-inhibit present → `systemd-inhibit` subprocess spawned;
  (c) Linux + systemd-inhibit absent → no subprocess, no crash;
  (d) macOS + caffeinate absent → existing behaviour preserved (currently raises or logs).
- SC-20: `tests/unit/test_clipboard_platform.py` — five cases:
  (a) macOS → NSPasteboard / osascript path taken (not xclip);
  (b) Linux + xclip present → xclip used;
  (c) Linux + xclip absent, xsel present → xsel used;
  (d) Linux + both absent → returns `False`/`None`, no crash;
  (e) macOS path still returns image data (mock NSPasteboard) — macOS branch not broken.
- SC-21: `tests/unit/test_navigation_platform.py` — three cases:
  (a) macOS → osascript invoked for VS Code navigation;
  (b) Linux + `code` on PATH → `code --reuse-window` invoked, no osascript;
  (c) Linux + `code` not on PATH → returns gracefully, no crash.
- SC-22: `tests/unit/test_shell_config.py` — four cases:
  (a) fresh install → `~/.leap.zshrc` written, `source` line in main rc;
  (b) re-run → `~/.leap.zshrc` overwritten, no duplicate `source` line;
  (c) migration from old START/END block → block removed, `source` line added;
  (d) unknown shell → graceful skip (existing behaviour preserved).
- SC-23: `tests/unit/test_pyproject_markers.py` — parse `pyproject.toml` and assert that
  every `pyobjc-*` and `py2app` dependency has `markers` containing
  `sys_platform == 'darwin'`.

## Out of Scope

- JetBrains terminal navigation on Linux (D-Bus / remote API) — deferred.
- Linux `.deb` / AppImage packaging — deferred.
- Wayland clipboard beyond `xclip`/`xsel` (`wl-clipboard`) — deferred.
- Non-Ubuntu dock badge (KDE TaskManager, etc.) — deferred.
- Full AT-SPI accessibility integration — deferred; `xdotool` is sufficient for navigation.
- `configure_iterm2_csi_u.py` Linux equivalent — iTerm2 is macOS-only.
- py2app replacement with a cross-platform build system — deferred.
- `configure_wezterm_csi_u.py` Lua config writing on Linux — deferred (WezTerm config
  paths differ per distro; `wezterm cli` navigation works without config changes).

## Open Questions

- OQ-1: For `NSBeep`/sound on Linux, prefer `QApplication.beep()` (no extra deps) or
  `paplay` (richer sound, requires PulseAudio)? [ANSWERED: QApplication.beep() first,
  paplay as optional enhancement — keep it simple]
- OQ-2: Should `~/.leap.zshrc` migration from the old `START/END` block happen silently
  or print a one-line notice? [ANSWERED: Print a one-line migration notice]
- OQ-3: For dock badge on non-Ubuntu Linux DEs (KDE, XFCE, etc.), skip entirely or
  attempt multiple D-Bus interfaces? [ANSWERED: Try Unity D-Bus first, skip silently if
  unavailable — no hard dep on Ubuntu]

## Q&A

Q: Should the monitor be fully functional on Linux or gracefully degraded?
A: Fully functional. PyQt5 already handles the window cross-platform; each macOS
subsystem has a Linux equivalent. Nothing is permanently demoted. [ANSWERED]

Q: Is VS Code navigation relevant to Linux compatibility?
A: Yes — `code --reuse-window` + the Leap VS Code extension already abstract terminal
selection cross-platform. VS Code navigation on Linux requires no new mechanism, just
replacing the AppleScript call with a CLI invocation. In scope. [ANSWERED]

Q: What is the shell config approach on Linux?
A: Write all Leap config to `~/.leap.zshrc` or `~/.leap.bashrc`; add only a single
idempotent `source "$HOME/.leap.zshrc"` line to the main rc. [ANSWERED]

Q: For NSBeep/sound replacement on Linux?
A: QApplication.beep() first (no deps); paplay as optional enhancement. [ANSWERED]

Q: Migration from old START/END block: silent or noticed?
A: Print a one-line migration notice. [ANSWERED]

Q: Dock badge on non-Ubuntu DEs?
A: Try Unity D-Bus, skip silently if unavailable. [ANSWERED]
