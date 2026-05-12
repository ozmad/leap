# Subtask 7: Shell Config — ~/.leap.zshrc / ~/.leap.bashrc

## Parent Task
linux-compatibility

## Description
Refactor `configure-shell-helper.sh` to write all Leap shell configuration to
`~/.leap.zshrc` (or `~/.leap.bashrc`), and add only a single idempotent
`source "$HOME/.leap.zshrc"` line to the user's main rc file. Migrate the legacy
`# ===== Leap Configuration START =====` block on first run.
Add `tests/unit/test_shell_config.py`.

## Scope
- `src/scripts/configure-shell-helper.sh` — full refactor
- `tests/unit/test_shell_config.py` — new file (uses subprocess to run the script
  against a tmp $HOME)

No other files touched. The Makefile calls `configure-shell-helper.sh` via the
`configure-shell` target — that call site is unchanged.

## Requirements Addressed
- FR-21
- SC-12, SC-22

## Technical Context

### New configure-shell-helper.sh behaviour

```
~/.leap.zshrc    ← entire Leap config block (regenerated on every run)
~/.zshrc         ← only: [ -f "$HOME/.leap.zshrc" ] && source "$HOME/.leap.zshrc"
```

**Step 1 — Detect shell and set file names:**
```bash
SHELL_NAME=$(basename "$SHELL")
if [ "$SHELL_NAME" = "zsh" ]; then
    RC_FILE="$HOME/.zshrc"
    LEAP_RC="$HOME/.leap.zshrc"
elif [ "$SHELL_NAME" = "bash" ]; then
    RC_FILE="$HOME/.bashrc"
    LEAP_RC="$HOME/.leap.bashrc"
else
    echo "⚠ Unknown shell: $SHELL_NAME — please source ~/.leap.zshrc manually"
    exit 0
fi
```

**Step 2 — Write `~/.leap.zshrc` (atomically):**
Write to a tmp file in the same dir, then `mv` to `$LEAP_RC` so the file is never
partially written. Content is identical to the current START/END block content, minus
the marker comments.

**Step 3 — Add source line to main rc (idempotent):**
```bash
SOURCE_LINE="[ -f \"\$HOME/.leap.zshrc\" ] && source \"\$HOME/.leap.zshrc\""
if ! grep -qF '.leap.zshrc' "$RC_FILE" 2>/dev/null; then
    echo "" >> "$RC_FILE"
    echo "$SOURCE_LINE" >> "$RC_FILE"
fi
```

**Step 4 — Migrate legacy START/END block:**
If the main rc contains `Leap Configuration START`, remove the entire block (already
done by existing code) and print a one-line migration notice:
```
ℹ Migrated Leap config → ~/.leap.zshrc
```
The migration notice is only printed once (when the block was found and removed).

**Step 5 — Remove legacy `LEAP_*_FLAGS` exports** (already done by current script,
keep this step unchanged).

### Atomic write for ~/.leap.zshrc
```bash
TMP_RC=$(mktemp "${LEAP_RC}.XXXXXX")
# ... write content to TMP_RC ...
mv "$TMP_RC" "$LEAP_RC"
```
This prevents a partial `~/.leap.zshrc` if the script is interrupted.

### Test approach
The test runs `configure-shell-helper.sh` in a subprocess with `HOME` set to a
`tmp_path` directory and `SHELL=/bin/zsh` (or /bin/bash). Checks:
(a) `~/.leap.zshrc` exists and contains `export LEAP_PROJECT_DIR`
(b) `~/.zshrc` contains exactly one `source ... .leap.zshrc` line
(c) Re-running doesn't duplicate the source line
(d) A `~/.zshrc` with the legacy `Leap Configuration START/END` block: after running,
    block is gone, source line is present, migration notice was printed to stdout
(e) `SHELL=/bin/fish` (unknown shell): exits 0, prints warning, neither rc file changed

## Acceptance Criteria
- AC-1: After install, `~/.leap.zshrc` (or `.bashrc`) contains all Leap config
  (`export LEAP_PROJECT_DIR`, the `leap()` function, tab completions).
- AC-2: `~/.zshrc` contains exactly one `source "$HOME/.leap.zshrc"` line after
  any number of re-runs.
- AC-3: Legacy `START/END` block in `~/.zshrc` is removed and replaced with the source
  line on first run; migration notice printed.
- AC-4: `SHELL=/bin/fish` (unknown shell): script exits 0, prints a warning, no files
  modified.
- AC-5: `~/.leap.zshrc` is written atomically (tmp + mv).
- AC-6: `test_shell_config.py` passes all five cases (SC-22).
- AC-7: `make test` passes on macOS (SC-13).

## Dependencies
- Depends on: none (shell script, independent of Python changes)
- Must not break: existing users' shell on macOS (the source line is functionally
  equivalent to the old inline block; `LEAP_PROJECT_DIR` and the `leap()` function
  are still set)

## Estimated Complexity
M — shell script refactor with migration path; test requires subprocess + tmp $HOME.
