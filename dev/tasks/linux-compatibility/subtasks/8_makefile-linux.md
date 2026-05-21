# Subtask 8: Makefile + Configure Scripts Linux-Aware

## Parent Task
linux-compatibility

## Description
Remove the hard macOS gate from the `install` target. Wrap macOS-only Makefile steps
(`tccutil`, `open x-apple:`, `osascript app-quit`) in `uname` guards so they skip with
an informational message on Linux. Make `install-monitor` on Linux print a clear skip
message and exit 0. Guard `configure_iterm2_csi_u.py` and fix
`configure_wezterm_csi_u.py` to use `which wezterm` on Linux.

## Scope
- `Makefile` — `check-macos`, `install`, `install-monitor`, `BUILD_MONITOR_APP` macro,
  `.prompt-notifications`, and any `open x-apple:` / `tccutil` / `osascript` lines
- `src/scripts/configure_iterm2_csi_u.py` — add early exit on non-macOS
- `src/scripts/configure_wezterm_csi_u.py` — replace `mdfind` + `/Applications` check
  with `which wezterm` on Linux

No test file required for this subtask. The acceptance criteria are verified by running
`make install` and `make install-monitor` on a Linux system.

## Requirements Addressed
- FR-10, FR-12 (configure scripts), FR-17, FR-18, FR-19, FR-20
- SC-9

## Technical Context

### Makefile — check-macos

Current:
```makefile
.PHONY: check-macos
check-macos:
    @if [ "$$(uname)" != "Darwin" ]; then \
        echo "$(RED)✗ Leap requires macOS. Linux is not supported.$(NC)"; \
        exit 1; \
    fi
```

New: repurpose as a *warning* that prints but does NOT exit non-zero:
```makefile
.PHONY: check-macos
check-macos:
    @if [ "$$(uname)" != "Darwin" ]; then \
        echo "$(YELLOW)ℹ Running on Linux — macOS-only features will be skipped.$(NC)"; \
    fi
```

The `install` target already has `check-macos` as a dependency — keeping it there
ensures the message is always printed on Linux without aborting.

### Makefile — BUILD_MONITOR_APP macro

The `osascript -e 'quit app "Leap Monitor"'` line (line 78) and the entire py2app
build logic only make sense on macOS. Wrap:
```makefile
define BUILD_MONITOR_APP
if [ "$$(uname)" != "Darwin" ]; then \
    echo "$(YELLOW)ℹ Monitor app build skipped on Linux (py2app is macOS-only).$(NC)"; \
    echo "  Run 'make run-monitor' to launch the monitor from source."; \
    exit 0; \
fi
# ... existing py2app logic ...
endef
```

### Makefile — install-monitor

Add a platform guard at the top of the `install-monitor` recipe:
```makefile
install-monitor: check-python .env ensure-storage
    @if [ "$$(uname)" != "Darwin" ]; then \
        echo "$(YELLOW)ℹ Monitor app build requires macOS (py2app).$(NC)"; \
        echo "  Use 'make run-monitor' to launch from source on Linux."; \
        exit 0; \
    fi
    # ... existing recipe ...
```

### Makefile — Accessibility + Notification prompts

Lines 307, 447, 463: `open "x-apple.systempreferences:..."` — wrap each in:
```makefile
if [ "$$(uname)" = "Darwin" ]; then open "x-apple...."; fi
```

Line 126: `tccutil reset Accessibility com.leap.monitor` — wrap:
```makefile
if [ "$$(uname)" = "Darwin" ]; then tccutil reset Accessibility com.leap.monitor 2>/dev/null || true; fi
```

### configure_iterm2_csi_u.py

Add at the very top of `main()` (or module level after imports):
```python
import sys
if sys.platform != 'darwin':
    sys.exit(0)
```
iTerm2 is macOS-only. Silent exit 0 on Linux — no message needed.

### configure_wezterm_csi_u.py

Current detection (lines 31–46):
```python
if (Path("/Applications/WezTerm.app").is_dir()
        or Path.home().joinpath("Applications/WezTerm.app").is_dir()):
    wezterm_path = "/Applications/WezTerm.app/..."
elif ...:
    result = subprocess.run(["mdfind", ...], ...)
    ...
```

New:
```python
import sys, shutil

def _find_wezterm() -> Optional[str]:
    if sys.platform == 'darwin':
        # existing /Applications + mdfind logic (unchanged)
        ...
    else:
        return shutil.which('wezterm')
```

The config-writing logic (editing `~/.wezterm.lua`) is unchanged — it runs on any
platform where WezTerm is found.

### `configure_hooks.py` and provider `configure_hooks()`

These configure Claude/Codex/Gemini/Cursor hook files in `~/.claude`, `~/.codex`, etc.
These directories and JSON/TOML config files exist on Linux too. No change needed —
hook configuration works cross-platform.

## Acceptance Criteria
- AC-1: `make install` on Linux exits 0 and prints the Linux-notice message.
- AC-2: `make install-monitor` on Linux exits 0 and prints the py2app-skip message.
- AC-3: `tccutil` is not called on Linux (wrapped).
- AC-4: `open x-apple.systempreferences:` is not called on Linux (wrapped).
- AC-5: `osascript -e 'quit app "Leap Monitor"'` is not called on Linux.
- AC-6: `python configure_iterm2_csi_u.py` on Linux exits 0 silently.
- AC-7: `python configure_wezterm_csi_u.py` on Linux calls `which wezterm` instead
  of `mdfind`.
- AC-8: `make install` on macOS is completely unchanged (check-macos now prints a
  no-op on Darwin, still runs all install steps).
- AC-9: `make test` passes on macOS (SC-13).

## Dependencies
- Depends on: Subtask 7 (shell config refactor should land first so the `configure-shell`
  target writes `~/.leap.zshrc`); all Python subtasks (1–6) should be complete so a
  full `make install` on Linux has a working Python stack to install
- Must not break: full macOS install flow; `make reconfigure` on macOS

## Estimated Complexity
M — many small targeted edits across Makefile + 2 scripts; no complex logic.
