"""Sleep prevention for macOS and Linux.

This module exposes two cooperating guards that the monitor activates
together while any session is in ``RUNNING`` state:

:class:`SleepGuard`
    macOS: spawns ``caffeinate -i -w <monitor-pid>`` to block idle sleep.
    Self-cleans on parent death thanks to ``-w``; survives a crash.
    Linux: spawns ``systemd-inhibit --what=idle ... sleep infinity``.
    Best-effort — silently no-ops if ``systemd-inhibit`` is absent.

:class:`LidCloseGuard`
    macOS: calls ``sudo pmset -a disablesleep 1/0`` via :class:`SudoManager`
    to additionally block lid-close sleep.  ``disablesleep`` is a sticky
    kernel setting and can't be tied to a process lifetime, so we lean
    on a marker file (``.storage/disablesleep.marker``) to detect and
    recover from a crashed-while-active state on the next monitor startup.
    Linux: spawns ``systemd-inhibit --what=sleep ... sleep infinity``.
    Best-effort — silently no-ops if ``systemd-inhibit`` is absent.

The :class:`SleepGuard` is idempotent: ``start()`` while already
active and ``stop()`` while inactive are both no-ops.
"""

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

from leap.monitor.sudo_manager import SudoManager
from leap.utils.constants import STORAGE_DIR

logger = logging.getLogger(__name__)

# Marker written while we hold ``disablesleep=1`` so a crashed monitor
# can be detected on the next launch and the kernel state cleaned up.
_DISABLESLEEP_MARKER = STORAGE_DIR / 'disablesleep.marker'


class SleepGuard:
    """Holds a ``caffeinate(8)`` child process while active."""

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None

    @property
    def is_active(self) -> bool:
        """True iff a caffeinate child is currently running."""
        return self._proc is not None and self._proc.poll() is None

    # Hardcoded so the py2app bundle (which can launch with a sanitized
    # PATH) always finds the binary.  ``caffeinate`` has lived at this
    # path on every macOS release since 10.8 — well below our minimum.
    _CAFFEINATE_PATH = '/usr/bin/caffeinate'

    def start(self) -> None:
        """Spawn the platform sleep-inhibitor if not already running.

        macOS: ``caffeinate -i -w <pid>`` — exits automatically when the
        monitor dies (``-w``), so the assertion is always released even on
        a hard crash or ``os._exit``.

        Linux: ``systemd-inhibit --what=idle ... sleep infinity`` — we hold
        the child process; terminating it releases the inhibit lock.
        Best-effort: if ``systemd-inhibit`` is absent the guard silently
        no-ops rather than breaking the monitor.

        Failure to spawn is logged once and swallowed in both cases.
        """
        if self.is_active:
            return
        if sys.platform == 'darwin':
            cmd = [self._CAFFEINATE_PATH, '-i', '-w', str(os.getpid())]
        else:
            inhibit = shutil.which('systemd-inhibit')
            if not inhibit:
                logger.debug("SleepGuard: systemd-inhibit not found, skipping")
                return
            cmd = [
                inhibit,
                '--what=idle',
                '--who=LeapMonitor',
                '--why=Leap session active',
                '--mode=block',
                'sleep', 'infinity',
            ]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info("SleepGuard active (pid=%d)", self._proc.pid)
        except OSError:
            logger.exception("Failed to spawn SleepGuard")
            self._proc = None

    def stop(self) -> None:
        """Terminate the caffeinate child if running."""
        proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1.0)
            logger.info("SleepGuard released")
        except Exception:
            logger.exception("Error stopping caffeinate")


class LidCloseGuard:
    """Toggles ``pmset -a disablesleep 1/0`` to also block lid-close sleep.

    Unlike :class:`SleepGuard` (a child-process assertion that the
    kernel auto-releases on parent death), ``disablesleep`` is a
    sticky system property that survives reboot.  We therefore pair
    every ``start`` with a marker file write, and every ``stop`` with
    a marker file delete, so the next monitor startup can detect a
    crashed-while-active state and clean it up.

    Each call needs the user's sudo password; on auth failure the
    caller (MonitorWindow) is expected to re-prompt and retry.  The
    methods return ``(success, stderr)`` so the caller can distinguish
    a wrong-password retry from a hard error.
    """

    _PMSET_PATH = '/usr/bin/pmset'

    def __init__(self) -> None:
        self._active: bool = False
        # Linux: holds the systemd-inhibit child process (analogous to SleepGuard._proc)
        self._proc: Optional[subprocess.Popen] = None

    @property
    def is_active(self) -> bool:
        return self._active

    @staticmethod
    def marker_path() -> Path:
        return _DISABLESLEEP_MARKER

    @staticmethod
    def marker_present() -> bool:
        return _DISABLESLEEP_MARKER.exists()

    def start(self, password: str) -> Tuple[bool, str]:
        """Activate lid-close sleep prevention.

        macOS: runs ``sudo pmset -a disablesleep 1``.  Idempotent — if
        already active, returns ``(True, '')`` without touching the system.

        Linux: spawns ``systemd-inhibit --what=sleep ... sleep infinity``.
        Best-effort — returns ``(True, '')`` whether or not the binary is
        present; ``password`` is ignored.
        """
        if sys.platform != 'darwin':
            if self._proc is not None and self._proc.poll() is None:
                return True, ''
            inhibit = shutil.which('systemd-inhibit')
            if not inhibit:
                logger.debug("LidCloseGuard: systemd-inhibit not found, skipping")
                return True, ''
            try:
                self._proc = subprocess.Popen(
                    [inhibit, '--what=sleep', '--who=LeapMonitor',
                     '--why=Lid close disabled', '--mode=block',
                     'sleep', 'infinity'],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._active = True
                logger.info("LidCloseGuard active (systemd-inhibit pid=%d)",
                            self._proc.pid)
            except OSError:
                logger.exception("Failed to spawn LidCloseGuard inhibitor")
            return True, ''

        # macOS path — unchanged
        if self._active:
            return True, ''
        rc, err = SudoManager.run(
            [self._PMSET_PATH, '-a', 'disablesleep', '1'], password)
        if rc == 0:
            self._active = True
            try:
                _DISABLESLEEP_MARKER.touch()
            except OSError:
                logger.exception("Failed to write disablesleep marker")
            logger.info("LidCloseGuard active (disablesleep=1)")
            return True, ''
        logger.error(
            "pmset disablesleep 1 failed (rc=%d): %s", rc, err.strip())
        return False, err

    def stop(self, password: str) -> Tuple[bool, str]:
        """Deactivate lid-close sleep prevention.

        macOS: runs ``sudo pmset -a disablesleep 0``.  Invokes pmset even
        when not ``_active`` if the marker file is present (crash recovery).

        Linux: terminates the systemd-inhibit child if running.
        ``password`` is ignored.
        """
        if sys.platform != 'darwin':
            proc, self._proc = self._proc, None
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=2.0)
                except (subprocess.TimeoutExpired, OSError):
                    proc.kill()
            self._active = False
            return True, ''

        # macOS path — unchanged
        if not self._active and not _DISABLESLEEP_MARKER.exists():
            return True, ''
        rc, err = SudoManager.run(
            [self._PMSET_PATH, '-a', 'disablesleep', '0'], password)
        if rc == 0:
            self._active = False
            try:
                _DISABLESLEEP_MARKER.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                logger.exception("Failed to remove disablesleep marker")
            logger.info("LidCloseGuard released (disablesleep=0)")
            return True, ''
        logger.error(
            "pmset disablesleep 0 failed (rc=%d): %s", rc, err.strip())
        return False, err

    def force_inactive(self) -> None:
        """Mark the guard as inactive locally without running pmset.

        Called when the user has cancelled a re-auth dialog or when
        even a freshly-validated password keeps getting rejected by
        ``sudo pmset`` — in either case we've given up trying to
        cleanly release the OS-level assertion.

        Clears both ``self._active`` and the marker file so subsequent
        evaluator ticks don't keep retrying (and re-opening dialogs).
        Trade-off: the next monitor startup loses its orphan-recovery
        signal, so if ``disablesleep=1`` is still set at the OS level
        the user has to clear it by hand.  The caller is expected to
        warn them to that effect via QMessageBox.
        """
        self._active = False
        try:
            _DISABLESLEEP_MARKER.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            logger.exception("Failed to remove disablesleep marker")
