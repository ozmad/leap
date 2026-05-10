"""Test harness that simulates a CLI with a 'leaky' permission menu.

Used by ``test_dialog_answer_leak_protection.py`` to verify that
Leap's rapid-send protocol for ``select_option`` doesn't let the
trailing CR leak past the menu and submit the user's typed-but-
unsubmitted composer text.

Behavior:

* **composer mode** (default): typed chars accumulate in a composer
  buffer.  Enter (``\\r`` or ``\\n``) "submits" the buffer — logs a
  ``SUBMIT msg=<contents>`` event.  Ctrl+U clears the buffer.

* **menu mode**: triggered by Ctrl+A from composer mode.  In menu
  mode, ANY digit press immediately confirms the menu (logs
  ``MENU_CONFIRM option=<n>``) and switches back to composer mode.
  This is the *worst case* Claude-like behavior — the menu doesn't
  wait for Enter.  A trailing CR sent after the digit would land in
  the composer.

Reads are **chunked** (``os.read(fd, 1024)``) so multiple bytes
arriving in the same kernel buffer get processed together — letting
the test distinguish between "digit and CR sent atomically vs in
separate writes".

Every event is timestamped and logged to the file named in
``LEAK_TEST_LOG`` env var (one event per line).
"""

import os
import sys
import termios
import time
import tty


def _open_log() -> object:
    path = os.environ['LEAK_TEST_LOG']
    return open(path, 'w', buffering=1)


def _log(f: object, msg: str) -> None:
    f.write(f'{time.time():.6f} {msg}\n')


def main() -> None:
    log_f = _open_log()
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        composer = bytearray()
        menu_mode = False
        _log(log_f, 'READY')

        while True:
            try:
                chunk = os.read(fd, 1024)
            except OSError:
                break
            if not chunk:
                continue

            mode_label = 'menu' if menu_mode else 'composer'
            _log(log_f, f'READ mode={mode_label} bytes={chunk!r}')

            # Iterate bytes; mode can change mid-chunk if menu
            # auto-confirms on a digit.
            i = 0
            while i < len(chunk):
                b = chunk[i]
                if menu_mode:
                    if 0x30 <= b <= 0x39:  # digit -> auto-confirm
                        opt = b - 0x30
                        _log(log_f, f'MENU_CONFIRM option={opt}')
                        menu_mode = False
                        i += 1
                        # Drain the rest of THIS read so the trailing
                        # CR (sent in the same syscall as the digit)
                        # is harmlessly discarded — matches the
                        # behavior of a well-behaved input loop that
                        # flushes pending bytes after dismissal.
                        if i < len(chunk):
                            drained = chunk[i:]
                            _log(log_f, f'DRAIN_AFTER_CONFIRM bytes={bytes(drained)!r}')
                            i = len(chunk)
                    elif b == 0x1b:  # Esc -> cancel
                        _log(log_f, 'MENU_CANCEL')
                        menu_mode = False
                        i += 1
                    else:
                        _log(log_f, f'MENU_IGNORE byte={b}')
                        i += 1
                else:
                    if b == 0x01:  # Ctrl+A -> open menu
                        _log(log_f, 'MENU_OPEN')
                        menu_mode = True
                        i += 1
                    elif b == 0x03:  # Ctrl+C -> exit
                        _log(log_f, 'EXIT')
                        return
                    elif b in (0x0d, 0x0a):  # Enter -> submit
                        msg = bytes(composer).decode('utf-8', errors='replace')
                        _log(log_f, f'SUBMIT msg={msg!r}')
                        composer.clear()
                        i += 1
                    elif b == 0x15:  # Ctrl+U -> clear composer
                        composer.clear()
                        _log(log_f, 'COMPOSER_CLEARED')
                        i += 1
                    elif b == 0x05:  # Ctrl+E -> cursor to end (no-op)
                        _log(log_f, 'CURSOR_END')
                        i += 1
                    elif b == 0x1b:  # Esc -> log and skip (no escape parsing)
                        _log(log_f, 'COMPOSER_ESC')
                        i += 1
                    else:
                        composer.append(b)
                        _log(log_f, f'COMPOSER_APPEND byte={b} buf={bytes(composer)!r}')
                        i += 1
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        log_f.close()


if __name__ == '__main__':
    main()
