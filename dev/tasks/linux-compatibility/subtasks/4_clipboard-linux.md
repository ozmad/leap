# Subtask 4: Clipboard Linux Path

## Parent Task
linux-compatibility

## Description
Add Linux clipboard support to `client/image_handler.py` (currently uses `osascript`)
and guard the `pbcopy` call in `navigation.py`. `server.py`'s `HAS_APPKIT` guard
already handles the read side; add a Linux write path there too.
Add `test_clipboard_platform.py`.

## Scope
- `src/leap/client/image_handler.py` — `check_clipboard_has_image()` and
  `save_clipboard_image()`
- `src/leap/monitor/navigation.py` — the two `pbcopy` call sites (lines 1365, 1442)
- `src/leap/server/server.py` — clipboard image *write* path (under `HAS_APPKIT`)
- `tests/unit/test_clipboard_platform.py` — new file

## Requirements Addressed
- FR-10
- SC-17 (macOS path preserved), SC-20

## Technical Context

### image_handler.py

**Current macOS implementation:**
- `check_clipboard_has_image()` — runs `osascript -e 'clipboard info'`, returns True if
  output contains 'TIFF data' or 'PNG'.
- `save_clipboard_image(path)` — runs a multi-line osascript to write clipboard TIFF
  data to a file.

**Linux replacement:**
```python
import sys, shutil, subprocess

def check_clipboard_has_image() -> bool:
    if sys.platform == 'darwin':
        # ... existing osascript path ...
    # Linux: try xclip, then xsel
    if shutil.which('xclip'):
        try:
            r = subprocess.run(
                ['xclip', '-selection', 'clipboard', '-t', 'TARGETS', '-o'],
                capture_output=True, timeout=2,
            )
            return b'image/png' in r.stdout or b'image/jpeg' in r.stdout
        except (subprocess.SubprocessError, OSError):
            pass
    if shutil.which('xsel'):
        try:
            r = subprocess.run(
                ['xsel', '--clipboard', '--output'],
                capture_output=True, timeout=2,
            )
            # xsel outputs raw bytes; check for PNG magic bytes
            return r.stdout[:4] == b'\x89PNG'
        except (subprocess.SubprocessError, OSError):
            pass
    return False

def save_clipboard_image(path: str) -> bool:
    if sys.platform == 'darwin':
        # ... existing osascript path ...
    if shutil.which('xclip'):
        try:
            r = subprocess.run(
                ['xclip', '-selection', 'clipboard', '-t', 'image/png', '-o'],
                capture_output=True, timeout=5,
            )
            if r.returncode == 0 and r.stdout:
                with open(path, 'wb') as f:
                    f.write(r.stdout)
                return True
        except (subprocess.SubprocessError, OSError):
            pass
    if shutil.which('xsel'):
        try:
            r = subprocess.run(['xsel', '--clipboard', '--output'],
                               capture_output=True, timeout=5)
            if r.returncode == 0 and r.stdout[:4] == b'\x89PNG':
                with open(path, 'wb') as f:
                    f.write(r.stdout)
                return True
        except (subprocess.SubprocessError, OSError):
            pass
    return False
```

### navigation.py pbcopy (lines 1365, 1442)

Both sites copy a command string to the clipboard to paste into an IDE terminal:
```python
subprocess.run(['pbcopy'], input=command.encode('utf-8'), timeout=2, ...)
```

Linux replacement using xclip → xsel → no-op:
```python
def _copy_to_clipboard(text: str) -> None:
    """Copy *text* to system clipboard (macOS and Linux)."""
    if sys.platform == 'darwin':
        subprocess.run(['pbcopy'], input=text.encode('utf-8'),
                       capture_output=True, timeout=2)
        return
    for cmd in (['xclip', '-selection', 'clipboard'],
                ['xsel', '--clipboard', '--input']):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, input=text.encode('utf-8'),
                               capture_output=True, timeout=2)
                return
            except (subprocess.SubprocessError, OSError):
                pass
```

Replace both pbcopy call sites with `_copy_to_clipboard(command)`.
`shutil` is not yet imported in `navigation.py` — add it at the top.

### server.py clipboard write

`server.py` already has:
```python
try:
    from AppKit import NSBitmapImageRep, NSPasteboard, ...
    HAS_APPKIT = True
except ImportError:
    HAS_APPKIT = False
```

The *read* from clipboard (saving a pasted image) already falls back to `return None`
when `HAS_APPKIT = False`. The *write* path (writing an image to the pasteboard) also
needs a Linux path via Qt clipboard:

```python
if HAS_APPKIT:
    # existing NSPasteboard write
else:
    # Linux: use QApplication clipboard
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtGui import QImage
    app = QApplication.instance()
    if app:
        img = QImage(path)
        app.clipboard().setImage(img)
```

`QApplication` is already imported in monitor context; `QImage` is in `PyQt5.QtGui`
(already a dep). This is monitor-only code, so Qt is always available.

## Acceptance Criteria
- AC-1: On macOS, `check_clipboard_has_image()` and `save_clipboard_image()` still use
  the osascript path.
- AC-2: On Linux with xclip present, clipboard image detection and save use xclip.
- AC-3: On Linux with xclip absent, xsel present — xsel is used.
- AC-4: On Linux with neither present, both return False/None without crashing.
- AC-5: Both `pbcopy` sites in navigation.py are replaced with `_copy_to_clipboard()`;
  macOS uses pbcopy, Linux uses xclip→xsel→no-op.
- AC-6: `test_clipboard_platform.py` covers all five cases (SC-20).
- AC-7: `make test` passes on macOS (SC-13, SC-17).

## Dependencies
- Depends on: Subtask 2 (import guards) for navigation.py changes to be safe
- Must not break: macOS clipboard image paste in client and server

## Estimated Complexity
S — additive branches, no complex logic.
