# Leap

PTY-based client-server system for managing AI CLI sessions (Claude Code, OpenAI Codex, Cursor Agent, Gemini CLI) with message queueing, image support, and native IDE scrolling.

## Quick Start

```bash
make install                # Install core
make install-monitor        # Install GUI (optional)
source ~/.zshrc             # Reload shell

leap mytag                       # Terminal 1: Select CLI + start server
leap mytag                       # Terminal 2: Connect client
leap                             # Interactive: choose CLI + session name

leap --reconfigure               # After installing a new CLI/IDE/terminal post-Leap
```

**Installed a new CLI / IDE / terminal after Leap?** Run `leap --reconfigure`. The install-time configures (`make install`) skip anything that wasn't on disk at the time, so newly-installed tools have no hook integration. The session-start gate in `leap-server.py` will refuse to spawn the server for a CLI whose hooks aren't wired up, with a stderr error pointing here.

## Reference Files

Load these on demand — they are **not** auto-loaded:

| File | Load when… |
|------|------------|
| `.claude/project-map.md` | Navigating the codebase: file tree, key classes, runtime file paths, client commands, server queue shortcut |
| `.claude/skills/feature-patterns.md` | Adding any new component: CLI provider, monitor dialog (ZoomMixin, geometry, font zoom), storage dir, theme, asset, socket comms, third-party dep |
| `.claude/skills/pr-tracking-internals.md` | Working on monitor PR/SCM features: polling, comment routing, auto-fetch, pinned sessions, row ordering/colors/aliases, change indicators, branch validation |
| `.claude/slack-and-ide.md` | Working on Slack integration or IDE configuration (JetBrains, VS Code/Cursor, iTerm2, WezTerm) |
| `.claude/skills/add-cli-provider.md` | Adding a new CLI provider end-to-end |
| `.claude/skills/add-dialog.md` | Adding a new monitor dialog end-to-end |
| `.claude/skills/add-monitor-theme.md` | Adding a new monitor theme |
| `.claude/skills/add-client-command.md` | Adding a new client command |

## Code Conventions

- **Type hints**: 100% coverage on all function signatures and return types. Use `Optional[X]` (not `X | None`) for consistency.
- **Imports**: **Every `import` and `from X import Y` statement MUST live at the top of the module.** No inline imports inside `def` bodies, methods, class bodies, `if/for/while` blocks, or anywhere other than the module header — not for "lazy loading", not for "avoiding startup cost", not as a hotfix to dodge a circular import. Violating this rule has bitten us multiple times (stale references, import-error masking, duplication of the same import in 15 different methods); treat it as a hard ban.
  - **Only two allowed exceptions**, and both live at module top level:
    1. **Optional-dependency fallback**: a top-level `try: import X except ImportError:` block that sets a sentinel (e.g. `WebClient = None`) so the rest of the module can guard on it. Used today for `prompt_toolkit`, `slack_sdk`/`slack_bolt`, `tomllib`/`tomli`, and `AppKit` when the module needs to import on non-macOS.
    2. **Type-only circular-import break**: a top-level `if TYPE_CHECKING:` block for imports used *only* in type annotations. If you hit a real runtime circular import, the fix is to restructure the modules (extract the shared code) — not to sneak an inline import back in.
  - Before adding a new top-level import, check for an existing one — don't duplicate. When moving an inline alias (e.g. `import time as _time`), replace every `_time.` call site with the bare name.
  - Stdlib → third-party → `leap.*`, each group alphabetized.
- **Client commands**: Each command handler is extracted into a private `_handle_*` method on `LeapClient`. The `_process_command` dispatcher delegates to these handlers.
- **Socket pattern**: `SocketClient._send_request()` is the single source of truth for client→server socket communication. `send_socket_request()` in `utils/socket_utils.py` is the lightweight variant for monitor/session_manager code that doesn't need rate-limited error reporting.

## Testing

```bash
make test                         # All tests (unit + integration)
make test-unit                    # Fast unit tests only (fake clock)
make test-integration             # Real-PTY integration tests (~2 min)
poetry run pytest tests/ -v       # All tests with verbose output
```

- Tests use `pytest` (dev dependency, `poetry install --with dev`)
- `tests/unit/` — fake-clock tracker tests and other in-process units
- `tests/integration/` — real bash-via-pexpect PTY + pyte rendering; shared `PTYFixture` lives in `tests/conftest.py`
- `ClaudeStateTracker` uses an injectable `clock` parameter — tests pass a fake clock (`lambda: t[0]`) for deterministic time control
- Use `tmp_path` fixture for signal files
- Test file naming: `tests/unit/test_<module>.py` or `tests/integration/test_<topic>.py`

## Troubleshooting

**"Another client already connected"** → `rm .storage/sockets/<tag>.client.lock`

**Stale sockets** → `leap-cleanup`

**`✗ Leap's hooks aren't configured for <CLI>` at session start** → The session-start gate (`leap-server.py:_enforce_hooks_installed_or_exit`) ran `provider.base_type`'s `hooks_installed()` and got False. Almost always means the user installed that CLI / IDE / terminal *after* `make install` ran (so install-time hook configuration silently skipped it). Fix: `leap --reconfigure`. Same flag also recovers from "user wiped `~/.<cli>/settings.json`" or any other partial-config drift.

**`⚠ Cert-based signing failed — bundle still has its py2app ad-hoc signature`** during build → `.gen-codesign-cert` ran but `codesign --sign "Leap Self-Signed"` couldn't find the cert. Either the user deleted it from Keychain Access, or the import silently failed last time. Check with `security find-certificate -c "Leap Self-Signed" "$HOME/Library/Keychains/login.keychain-db"`. If missing, just re-run `make install-monitor` — `.gen-codesign-cert` will regenerate it (and will also `tccutil reset` so the user re-grants Accessibility once from the in-app banner).

**Accessibility silently fails after update on a machine that should be cert-signed** → Compare `codesign -dr - "/Applications/Leap Monitor.app"` to the TCC entry: `sudo sqlite3 "/Library/Application Support/com.apple.TCC/TCC.db" "SELECT hex(csreq) FROM access WHERE client='com.leap.monitor' AND service='kTCCServiceAccessibility';"`. The bundle's designated requirement should be `identifier "com.leap.monitor" and certificate leaf = H"<sha1>"` and the TCC csreq should be its byte-identical encoding. Mismatch usually means the bundle was rebuilt with a different cert (e.g., keychain was wiped between installs). Fix: `tccutil reset Accessibility com.leap.monitor` and have the user re-grant once.

## Make Commands

```bash
make install           # Install core + configure shell
make install-monitor   # Build and install GUI app (macOS); prints skip message on Linux
make install-monitor-deps  # Install monitor Python deps without building the app (Linux)
make install-slack-app # Install Slack integration + setup wizard
make reconfigure       # Re-run per-machine integration steps (hooks + IDE/terminal/shell configures); skips deps, monitor, slack, git pull. Use after installing a new CLI/IDE/terminal post-Leap. Same target leap --reconfigure execs into.
make test              # Run the full test suite (unit + integration)
make test-unit         # Run only fast unit tests
make test-integration  # Run only real-PTY integration tests
make run-monitor       # Run monitor from source (no build needed)
make update            # Update to latest version (git pull + rebuild)
make update-deps       # Update Python dependencies only
make uninstall         # Full cleanup (calls uninstall-monitor + uninstall-slack-app)
make uninstall-monitor   # Remove Monitor app only
make uninstall-slack-app # Remove Slack integration only
make clean             # Remove build artifacts
```

## Self-Verification

After writing any fix or feature, **always re-read your own changes and verify there are no bugs** before presenting them as done. Specifically:
- Check edge cases and off-by-one errors
- Verify that conditional branches do what they claim (e.g., a reset that should only trigger on condition A doesn't also trigger on unrelated condition B)
- Trace the flow end-to-end: how is the new code reached, what state does it depend on, and what happens in the common/idle case (not just the interesting case)

## Commit & Push Checklist

**NEVER commit or push without explicit user approval.** Always present the plan and wait for the user to say "commit", "go ahead", or equivalent before running any `git commit` or `git push` command.

When the user asks to commit and push, **before committing**:

1. **Review CLAUDE.md** — Check that it reflects the current codebase. Update any outdated sections (project structure, key classes, features, conventions). Keep it detailed — this is the developer reference.
2. **Review README.md** — Check that it reflects user-facing changes (new features, commands, UI changes). Keep it **concise** — users see this on GitLab. Don't bloat it with implementation details.
3. Only update these files if something actually changed that affects them. Don't touch them for minor internal refactors.
