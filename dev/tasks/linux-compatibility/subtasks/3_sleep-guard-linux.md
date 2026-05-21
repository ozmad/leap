# Subtask 3: SleepGuard Linux Path

## Parent Task
linux-compatibility

## Description
Add `systemd-inhibit` as the Linux backend for `SleepGuard` (idle sleep) and
`LidCloseGuard` (suspend sleep). Both are best-effort: if `systemd-inhibit` is absent
the guards silently no-op. macOS paths (`caffeinate`, `pmset`) are unchanged.
Add `test_sleep_guard_platform.py`.

## Scope
- `src/leap/monitor/sleep_guard.py` — `SleepGuard.start()`, `LidCloseGuard.start()`,
  `LidCloseGuard.stop()`
- `tests/unit/test_sleep_guard_platform.py` — new file

No other files touched.

## Requirements Addressed
- FR-7, FR-8 (partial — sleep only)
- SC-9 (partial), SC-10, SC-16, SC-19

## Technical Context

### SleepGuard Linux implementation
`systemd-inhibit` blocks a category of sleep while a child process it wraps is alive.
The analogous invocation to `caffeinate -i -w <pid>` is:

```
systemd-inhibit --what=idle --who="Leap Monitor" --why="Leap session active" \
    --mode=block sleep infinity
```

Note: unlike `caffeinate -w <pid>`, `systemd-inhibit` wraps a command rather than
watching a PID. The simplest equivalent is to use `sleep infinity` as the wrapped
command and hold the `Popen` handle — terminating it releases the inhibit lock.
`shutil.which('systemd-inhibit')` determines availability; if absent, `start()`
returns without setting `self._proc`.

Updated `SleepGuard.start()` pseudo-code:
```python
def start(self) -> None:
    if self.is_active:
        return
    if sys.platform == 'darwin':
        cmd = [self._CAFFEINATE_PATH, '-i', '-w', str(os.getpid())]
    else:
        inhibit = shutil.which('systemd-inhibit')
        if not inhibit:
            logger.debug("SleepGuard: systemd-inhibit not found, skipping")
            return
        cmd = [inhibit, '--what=idle', '--who=LeapMonitor',
               '--why=Leap session active', '--mode=block', 'sleep', 'infinity']
    try:
        self._proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                      stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)
        logger.info("SleepGuard active (pid=%d)", self._proc.pid)
    except OSError:
        logger.exception("Failed to spawn SleepGuard")
        self._proc = None
```

`stop()` is unchanged — it just terminates `self._proc` regardless of platform.

### LidCloseGuard Linux implementation
On Linux, `sudo pmset` is replaced with:
```
systemd-inhibit --what=sleep --who=LeapMonitor --why="Lid close disabled" \
    --mode=block sleep infinity
```
Same pattern as SleepGuard: hold the Popen handle; terminating it releases the lock.
`SudoManager` is macOS-only and must NOT be called on Linux. `LidCloseGuard.start()`
and `stop()` both need `sys.platform == 'darwin'` guards around the pmset path.

The `LidCloseGuard._forget()` helper that marks the guard inactive without running
pmset also needs a platform guard (it's only ever called from the pmset error paths,
which are macOS-only anyway, but guard it for clarity).

### `sys` import
`sys` is already imported in `sleep_guard.py`. `shutil` needs to be added to the
top-level imports.

## Acceptance Criteria
- AC-1: On macOS (`sys.platform == 'darwin'`), `SleepGuard.start()` spawns
  `caffeinate` exactly as before. (Verified by test macOS branch.)
- AC-2: On Linux with `systemd-inhibit` present, `SleepGuard.start()` spawns
  `systemd-inhibit ... sleep infinity`.
- AC-3: On Linux with `systemd-inhibit` absent, `SleepGuard.start()` returns without
  setting `_proc` and without raising.
- AC-4: On macOS, `LidCloseGuard.start()` calls `pmset` exactly as before.
- AC-5: On Linux, `LidCloseGuard.start()` uses `systemd-inhibit --what=sleep` when
  available; no-ops when absent.
- AC-6: `SleepGuard.stop()` works on both platforms (terminates whatever `_proc` was
  set to).
- AC-7: `test_sleep_guard_platform.py` passes all four cases (SC-19).
- AC-8: `make test` passes on macOS.

## Dependencies
- Depends on: Subtask 1 (environment); Subtask 2 not required
- Must not break: `SleepGuard` and `LidCloseGuard` behaviour on macOS; `SudoManager`
  interaction (pmset + saved password) on macOS

## Estimated Complexity
S — one file, additive platform branching.
