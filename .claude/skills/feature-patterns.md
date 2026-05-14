# Feature Patterns

Rules and gotchas for adding new Leap components. Load this when adding a new CLI provider, monitor dialog, storage subdirectory, theme, asset, or third-party dependency.

## New CLI Provider

See `.claude/skills/add-cli-provider.md` for the full step-by-step guide. Key constraints:

- Create `cli_providers/<name>.py`, register in `registry.py`
- Implement `configure_hooks()` and `hooks_installed()` — the latter must be the **symmetric inverse** of the former (both halves checked, never raises)
- The CLI selector, monitor table, ASCII banner, and shell flags are all dynamic — no changes needed there

**All custom CLIs must be variants of one of the four base CLIs** (Claude / Codex / Cursor Agent / Gemini). `CustomCLIProvider` (in `registry.py`) wraps a base provider and delegates everything via `__getattribute__` — including `hooks_installed()` and `base_type`. Pass `base_provider=ClaudeProvider()` (or another) to `CustomCLIProvider.__init__`; `base_type` follows automatically. The session-start gate uses `get_provider(provider.base_type).hooks_installed()` so custom CLIs share their base's hook setup automatically. There is no path for a custom CLI that's not built atop one of the four.

## New Monitor Dialog / Window

See `.claude/skills/add-dialog.md` for the full guide. Critical non-obvious rules:

**Geometry persistence** — all new resizable dialogs (except simple warning/error/info popups) must save/restore their size using `load_dialog_geometry(key)` / `save_dialog_geometry(key, w, h)` from `monitor/pr_tracking/config.py`. Call `load_dialog_geometry()` in `__init__` to restore. For persistence: if the dialog closes via `accept()`/`reject()`, save in `done()`. If it closes via `close()` or the X button, save in `closeEvent()` instead — `done()` is **not** called for `close()`/X.

**Prefs persistence model** — `MonitorWindow._DIALOG_OWNED_KEYS` and why `save_monitor_prefs(self._prefs)` must NOT be called outside `_save_prefs`. Skipping that is the most common way dialog state silently gets clobbered.

**Font zoom (Cmd+scroll / Cmd+±/0)** — every new dialog must inherit from `ZoomMixin` (`monitor/dialogs/zoom_mixin.py`) and call `_init_zoom(...)` at the end of `__init__`. Two forms:

- **Single-target** — form dialogs with no distinct content area (inputs, combos, checkboxes, buttons only):

  ```python
  class MyDialog(ZoomMixin, QDialog):
      def __init__(self, ...):
          super().__init__(...)
          # ... build UI ...
          self._init_zoom('my_dialog_font_size')
  ```

- **Split-target** — REQUIRED when the dialog has a primary content area (QTextEdit, QListWidget, QTreeView, QTableWidget, message cards, diff viewer, etc.) so the user can enlarge content without blowing up buttons/chrome:

  ```python
  class MyDialog(ZoomMixin, QDialog):
      def __init__(self, ...):
          super().__init__(...)
          self._editor = QTextEdit()
          self._list = QListWidget()
          # ... build UI ...
          self._init_zoom(
              pref_key='my_dialog_font_size',             # buttons/chrome
              content_pref_key='my_dialog_text_font_size',  # content area
              content_widgets=[self._editor, self._list],
          )
  ```

  For dialogs that rebuild content widgets dynamically (e.g. message cards recreated on save), pass a **callable** as `content_widgets` — the mixin calls it on every event — and call `self._zoom_reapply_content()` at the end of the rebuild so new widgets render at the current content size.

**Close hooks** — font sizes are flushed by `done()` automatically. If your dialog closes via `closeEvent()` instead of `done()`, call `self._zoom_flush()` explicitly in `closeEvent()`. Font sizes are NOT cleared by the "reset window sizes" button.

**Hint labels** — any inline `setStyleSheet(... font-size: ... )` on a hint/label overrides the dialog's cascade and won't scale with zoom. Leave `font-size` out of the inline stylesheet (set only `color:`) so ZoomMixin's cascade applies.

**Popups** (QMessageBox / QInputDialog / QMenu / QFileDialog / tooltips) — handled globally by `PopupZoomManager` (`monitor/popup_zoom.py`), one shared `popup_font_size` pref. No action needed for popups shown from your dialog.

## New `.storage` Subdirectory

Update **three** places every time:

1. Add the constant in `utils/constants.py` (next to `QUEUE_DIR`, `SOCKET_DIR`, `HISTORY_DIR`)
2. Add a `.mkdir()` call in `ensure_storage_dirs()` in `utils/constants.py`
3. Add the path to the `ensure-storage` target in `Makefile`

## Theming

Use `current_theme()` from `monitor/themes.py` to access colors. Never hardcode colors in monitor code — use theme properties (e.g. `t.accent_green`, `t.text_primary`). Theme colors are applied via `QPalette` (preserves native macOS widget rendering) + minimal QSS. Cell button styles use `close_btn_style()` / `active_btn_style()` / `menu_btn_style()` from `table_helpers.py`. Theme persists as `"theme"` in `monitor_prefs.json` (default: `"Midnight"`). Nine built-in themes: Leap, Amber, Midnight, Cosmos, Ocean, Monokai, Nord, Solarized Dark, Dawn.

## New Assets (Images, Icons, Themed Variants)

Any new asset file in `assets/` that the monitor uses at runtime **must** also be added to `DATA_FILES` in `setup.py`. The py2app bundle only includes explicitly listed files — assets missing from `setup.py` will work in `make run-monitor` (dev mode) but silently fail in the installed app. Logo text variants use `glob('assets/leap-text*.png')` so new theme logos are auto-included, but other new assets need manual addition.

## Socket Communication

Use `send_socket_request()` from `utils/socket_utils.py` for any new code that needs to talk to a Leap server via Unix socket. Do not duplicate the connect/send/recv pattern. Incoming messages are capped at `MAX_MESSAGE_SIZE` (1 MB) in `socket_handler.py`; larger payloads are rejected.

## New Third-Party Dependencies

Add to `pyproject.toml` under the appropriate group: `[tool.poetry.dependencies]` for core, `[tool.poetry.group.monitor.dependencies]` for GUI-only deps. Run `poetry lock && poetry install` after.

## Where to Add Code

- **Utils** → `src/leap/utils/`
- **Server** → `src/leap/server/`, update `LeapServer`
- **Client** → `src/leap/client/`, update `LeapClient`
- **Monitor** → `src/leap/monitor/`, update `MonitorWindow`
