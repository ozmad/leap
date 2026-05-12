# Subtask 5: Navigation Linux Path (VS Code + WezTerm + osascript guards)

## Parent Task
linux-compatibility

## Description
Guard all `osascript` and `mdfind` call sites in `navigation.py` with
`sys.platform == 'darwin'`. Add Linux implementations for VS Code (via `code
--reuse-window` + existing extension trigger) and WezTerm (via `wezterm cli`).
All other AppleScript-based navigation functions (Terminal.app, JetBrains,
Arduino) return False gracefully on Linux. Add `test_navigation_platform.py`.

## Scope
- `src/leap/monitor/navigation.py` — 8× osascript sites, 2× pbcopy (done in Subtask 4),
  1× mdfind, macOS app bundle path detection functions
- `tests/unit/test_navigation_platform.py` — new file

`pbcopy` is handled in Subtask 4. This subtask covers the remaining osascript,
mdfind, and `/Applications` path sites.

## Requirements Addressed
- FR-11, FR-12, FR-13, FR-14, FR-15
- SC-5, SC-8 (partial), SC-11, SC-15, SC-21

## Technical Context

### osascript call inventory
```
Line 628  — _navigate_iterm2()
Line 674  — _navigate_wezterm() (macOS AppleScript focus)
Line 700  — _navigate_wezterm() (macOS AppleScript tab)
Line 736  — _navigate_wezterm() (macOS AppleScript send keys)
Line 923  — _navigate_jetbrains()
Line 963  — _navigate_jetbrains()
Line 1279 — _navigate_vscode() (window focus)
Line 1860 — _navigate_terminal_app()
Line 1898 — _navigate_arduino()
```

### Strategy per function

**`_navigate_vscode(project_path, terminal_name, ide)`**
- macOS: existing osascript window-focus + `~/.leap-terminal-request` trigger (unchanged)
- Linux new path:
  ```python
  if sys.platform != 'darwin':
      # Focus VS Code window via CLI (opens if not running; reuses if already open)
      code_bin = shutil.which('code') if ide == 'VS Code' else shutil.which('cursor')
      if code_bin and project_path:
          subprocess.run([code_bin, '--reuse-window', project_path],
                         capture_output=True, timeout=5)
          time.sleep(0.3)
      # Write the terminal-request file (extension trigger — same as macOS)
      request_file = os.path.expanduser('~/.leap-terminal-request')
      try:
          with open(request_file, 'w') as f:
              f.write(terminal_name)
          time.sleep(0.1)
      except OSError:
          pass
      return True
  ```

**`_navigate_wezterm()`**
- macOS: existing AppleScript paths (3 osascript calls, unchanged)
- Linux: `wezterm cli` is already cross-platform. The WezTerm CLI commands
  (`wezterm cli list-panes`, `wezterm cli activate-pane-direction`, etc.) work on Linux
  without any AppleScript. The macOS version used osascript only to *focus the window*;
  on Linux, `wmctrl -a WezTerm` or `xdotool search --name WezTerm windowfocus` serves
  the same purpose. For now: use `wezterm cli` for pane selection and `wmctrl`/`xdotool`
  for window focus (best-effort, skip if absent).

  Concrete change: wrap the three osascript blocks in `if sys.platform == 'darwin':`.
  Add a Linux path that calls `wezterm cli` for the pane navigation part (the
  substantive part) and uses `shutil.which('wmctrl')` for window focus.

**`_find_wezterm_executable()` / `_WEZTERM_BUNDLE_ID` / mdfind**
- Current: checks `/Applications/WezTerm.app`, `~/Applications/WezTerm.app`, then
  `mdfind`.
- Linux replacement:
  ```python
  if sys.platform == 'darwin':
      # existing /Applications + mdfind logic
  else:
      return shutil.which('wezterm')
  ```

**`_navigate_iterm2()`**, **`_navigate_terminal_app()`**, **`_navigate_arduino()`**
- iTerm2 and Terminal.app are macOS-only; Arduino IDE navigation is AppleScript only.
- Wrap entire function body: `if sys.platform != 'darwin': return False`.

**`_navigate_jetbrains()`**
- JetBrains navigation is deferred (see Out of Scope in requirements).
- Wrap: `if sys.platform != 'darwin': return False`.

**`detect_supported_ide_for_move()`**
- Currently checks `.app` bundle suffixes and `~/Library/Application Support/JetBrains`.
- Linux: `code` on PATH → `'VS Code'`; `cursor` on PATH → `'VS Code'` (same extension);
  others → `None`.
- App bundle paths (`/Applications`, `~/Applications`, `~/Library`) guarded with
  `sys.platform == 'darwin'`.

**`open_terminal_with_command()` (the main entry point)**
- Already dispatches to per-terminal functions. No change needed beyond ensuring each
  sub-function returns False gracefully on Linux.

### `shutil` import
Add `import shutil` to navigation.py's top-level imports (not already present).

### `_HAS_COCOA` usage
After Subtask 2, `navigation.py` has `_HAS_COCOA`. Each function that calls
`AppKit`/`ApplicationServices`/`Quartz` symbols must also check
`if not _HAS_COCOA: return False` before proceeding. This is belt-and-suspenders with
the `sys.platform` guard — both protect against Linux.

## Acceptance Criteria
- AC-1: `_navigate_vscode()` on Linux with `code` on PATH: calls `code --reuse-window`,
  writes terminal-request file, returns True.
- AC-2: `_navigate_vscode()` on Linux without `code` on PATH: returns True (writes
  terminal-request; window focus is best-effort).
- AC-3: `_navigate_wezterm()` on Linux: calls `wezterm cli` for pane navigation;
  does not call osascript.
- AC-4: `_find_wezterm_executable()` on Linux: returns `shutil.which('wezterm')`.
- AC-5: `_navigate_iterm2()`, `_navigate_terminal_app()`, `_navigate_jetbrains()`,
  `_navigate_arduino()` on Linux all return False without raising.
- AC-6: On macOS, all existing osascript paths are still taken (not accidentally blocked).
- AC-7: `detect_supported_ide_for_move()` returns `'VS Code'` on Linux when `code` is
  on PATH.
- AC-8: `test_navigation_platform.py` passes all three cases (SC-21): macOS osascript,
  Linux + code, Linux without code.
- AC-9: `make test` passes on macOS (SC-13, SC-15).

## Dependencies
- Depends on: Subtask 2 (import guards must be in place before running navigation code
  on Linux), Subtask 4 (pbcopy → `_copy_to_clipboard` done)
- Must not break: all existing macOS navigation paths; `detect_supported_ide_for_move()`
  return values for macOS callers

## Estimated Complexity
M — large file (1900 lines), 9+ call sites to guard, new VS Code + WezTerm Linux paths.
  Individually each change is simple; the surface area is the risk.
