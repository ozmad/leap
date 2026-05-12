# Subtask 1: pyproject.toml — Platform Markers

## Parent Task
linux-compatibility

## Description
Add `markers = "sys_platform == 'darwin'"` to every pyobjc-* and py2app dependency in
`pyproject.toml` so that `poetry install` on Linux does not attempt to install
macOS-only packages. Add a unit test that parses `pyproject.toml` and asserts the
markers are present.

## Scope
- `pyproject.toml` — lines 29–31 (pyobjc-*) and line 41 (py2app)
- `tests/unit/test_pyproject_markers.py` — new file

No other files touched.

## Requirements Addressed
- FR-1, FR-16
- SC-1, SC-23

## Technical Context
Current state (pyproject.toml, monitor group):
```toml
pyobjc-framework-cocoa = "^12.1"
pyobjc-framework-applicationservices = "^12.1"
pyobjc-framework-quartz = "^12.1"
...
py2app = "^0.28"
```

Target state:
```toml
pyobjc-framework-cocoa = {version = "^12.1", markers = "sys_platform == 'darwin'"}
pyobjc-framework-applicationservices = {version = "^12.1", markers = "sys_platform == 'darwin'"}
pyobjc-framework-quartz = {version = "^12.1", markers = "sys_platform == 'darwin'"}
...
py2app = {version = "^0.28", markers = "sys_platform == 'darwin'"}
```

After editing `pyproject.toml`, run `poetry lock --no-update` to regenerate the
lockfile without upgrading any deps.

The test uses `tomllib` (stdlib in Python 3.11+) or the `tomli` fallback (already a
dev dep) to parse `pyproject.toml` directly — no import of `leap` package required.

## Acceptance Criteria
- AC-1: `poetry install` (core group only) exits 0 on Linux (no pyobjc attempt).
- AC-2: `poetry install --with monitor` on Linux exits 0 (pyobjc and py2app skipped).
- AC-3: `poetry lock --no-update` exits 0 after the pyproject.toml change.
- AC-4: `test_pyproject_markers.py` passes: every dependency whose name starts with
  `pyobjc-` or equals `py2app` has a `markers` field containing `sys_platform == 'darwin'`.
- AC-5: Existing `make test` passes on macOS (no lockfile drift).

## Dependencies
- Depends on: none
- Must not break: existing macOS install (`poetry install --with monitor` still installs
  pyobjc on macOS)

## Estimated Complexity
S — config-only change + one test file.
