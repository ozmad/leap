# PR Tracking Internals

Deep reference for the monitor's SCM Polling & PR Tracking subsystem. Load when working on GitLab/GitHub integration, polling, comment routing, pinned session lifecycle, row management, or the change-indicator logic.

## Polling Overview

The monitor polls GitLab/GitHub for PR status updates and user notifications. Key timeouts:

- **GitLab client timeout**: 15s per HTTP request
- **Poll cycle timeout**: 30s for all `ThreadPoolExecutor` futures
- **Stuck-poll safeguard**: Force-resets `_scm_polling` after 60s
- **Poll interval**: Configurable via `poll_interval` in config (default: 30s)

Polling flow: `_scm_poll_timer` → `_start_scm_poll()` → `SCMPollerWorker` (QThread) → `get_pr_status()` per session → `_on_scm_results()` → `_update_pr_column()`.

## Sending PR Comments to Leap

Left-click the PR status label (when any comment is unresponded) for a 2-item menu: **Go to first comment** (opens the comment in the browser) and **Send comment/s to session** (opens `SendCommentsDialog`). The dialog exposes two binary choices — filter (`all` / `leap`-tag-only) and mode (`each` message / `combined`) — plus a single-message "PR context preset" combo that's persisted via `save_selected_preset_name()` in `.storage/leap_selected_preset` (same file that `leap_sender.send_to_leap_session` reads to prepend context to every outgoing comment). When `auto_fetch_leap` is on, the whole "Which comments to send" section is omitted from the dialog — the filter is effectively forced to `all` since `/leap`-tagged comments are already auto-queued. Picks persist via `send_comments_filter` / `send_comments_mode` in `monitor_prefs.json`. On dispatch, `IndicatorLabel._open_send_comments_dialog()` does a pre-flight dead-server check (clear popup, no worker launched) and routes to one of four `_send_*_to_leap()` handlers by `(filter, mode)` pair. All four share `CollectThreadsWorker` (Phase 1), then diverge: `SendThreadsWorker` (one-by-one) or `SendThreadsCombinedWorker` (concatenated). All modes acknowledge comments on SCM side after send.

## /leap Auto-Fetch

"Auto '/leap' fetch" checkbox: when ON, `SCMPollerWorker` auto-scans for `/leap` tags each poll cycle. A `/leap` comment does **not** count as a user response — only the bot ack (`[Leap bot] on it!`) marks a comment as handled. When auto-fetch is on, the `SendCommentsDialog` hides its entire "Which comments to send" section (those comments are already queued automatically). Setting persisted as `auto_fetch_leap` in monitor prefs.

**Auto-fetch preset**: a separate preset combobox sits next to the checkbox in the main window (visible only while the checkbox is on). Its selection — persisted in `.storage/leap_auto_fetch_preset` — is loaded by `load_auto_fetch_leap_preset()` and passed through `send_to_leap_session(tag, msg, preset=…)` in `scm_polling._handle_leap_commands`. This is **independent** of `.storage/leap_selected_preset` which is used by manual sends from `SendCommentsDialog`. The combo's popup refreshes itself on open (`_RefreshableComboBox.showPopup`) so preset edits made elsewhere show up next time the user opens the dropdown; it also self-heals a stale saved selection if the preset was deleted or grew to multi-message.

## Environment Variable Token Mode

SCM tokens support two modes: `token_mode: "direct"` (stored in config) or `"env_var"` (resolved from `os.environ`). Resolution via `resolve_scm_token()` in `config.py`. On startup, env var tokens are validated — invalid ones disable the provider until re-tested via the setup dialog. Tracked rows survive provider disconnection (they retain `pr_tracked: True` in `pinned_sessions.json` and auto-reconnect once the provider is restored).

## User Notifications

Per-provider enable/disable via setup dialog. Polls `get_user_notifications()` each cycle. Seen IDs deduplicated via `.storage/notification_seen.json`. First-run seeds all existing notifications as seen. 403 errors auto-disable notifications for that provider.

## Persistent Rows & Pinned Sessions

Rows persist via `pinned_sessions.json`. Key rules:
- Every active session is auto-pinned on discovery
- Row survives if it has a running server OR `pr_tracked: True` set in pinned data OR pinned PR Branch data (`remote_project_path` + non-empty `branch`, mirroring the PR Branch column display rule — Stop PR Tracking leaves these in the pin so the X-to-clear UI still works) OR an in-flight transient flag (`_tracked_tags`, `_checking_tags`, `_starting_tags`, `_moving_tags`)
- Dead rows that are no longer being tracked AND have no displayed PR Branch are auto-removed on the next merge tick (so a row with no PR + no PR Branch + no server never appears in the table)
- PR auto-reconnects on monitor restart for rows with `pr_tracked: True` — that flag is also what keeps the row alive across the startup window before `_auto_track_pr_pinned` populates `_tracked_tags`/`_checking_tags`
- `_deleted_tags` set prevents auto-refresh from re-pinning just-deleted rows

## Add Row (+ Button)

Three options:
- **From Git URL** — PR URLs or plain project URLs → parse, pin, clone/track.
- **From Local Path** — clone to repos dir or open directly.
- **From Resume** — GUI does only the picking + already-running guard, then hands off to a new terminal. `_add_row_from_resume()` (in `pr_tracking_mixin.py`) opens `ResumeSessionDialog`; when the user picks `(cli, tag, SessionRecord)`, refuses if the same CLI session UUID is already running under another live Leap tag, then calls `ServerLauncher.open_resume_in_terminal(cli=…, tag=…, session_id=…)` which spawns a terminal running `leap --resume --cli=<X> --tag=<Y> --session=<Z>`. From there the CLI flow takes over: `leap-resume.py` skips its picker (pre-pick mode), runs the live-owners + `_server_alive` checks, prompts the user for cwd choice if `provider.requires_cwd_bound_resume` is True and the recorded cwd ≠ the terminal's cwd, then execs `leap-main.sh` with `LEAP_RESUME_*` env vars set. The server reads those and prepends `provider.resume_args(<id>)` to the CLI argv. The monitor row appears via auto-discovery once the server starts.

Tag validation via shared `_ask_tag()` helper.

## New Change Indicator

A fire icon (🔥) appears on the far right of the Status and PR columns when the value recently changed. Controlled by `new_status_seconds` in monitor prefs (default: 60, 0 = disabled). Click the indicator to dismiss it; dismissal resets when the value changes again.

- **Status column**: Never shown for `running` or `interrupted` states. Tracked in `_state_changed_at` and `_dismissed_new_status` on `MonitorWindow`.
- **PR column**: Triggers on changes to PR state, unresponded count, approval status, or who approved. First-time discovery is seeded with epoch 0 (no fire on startup). Tracked in `_pr_changed_at` and `_dismissed_pr_new_status` on `MonitorWindow`.

## Branch Mismatch & Server Startup Validation

- **Runtime mismatch**: Monitor shows `⚠ Server` in orange when live branch differs from expected PR branch
- **Startup validation** (`_validate_pinned_session()` in `server.py`): Checks repo match, branch match, behind-remote status. Fails 1-3 block startup; ahead/dirty is a warning only. Skipped for non-PR-pinned rows

## Row Ordering (Drag-and-Drop)

Rows are ordered by insertion time (not alphabetical). Users can drag any cell to reorder rows; the order is persisted as a `row_order` list in `monitor_prefs.json`. New sessions are appended at the end.

- **Drag detection**: App-level event filter (`eventFilter` in `app.py`) intercepts `MouseButtonPress`/`MouseMove` on cell widgets to initiate a `QDrag`
- **Drop indicator**: A 2px theme-colored line shows the drop position during drag
- **Auto-refresh paused** during drag (`timer.stop()` / `timer.start()`) to prevent table rebuilds from interrupting the gesture
- **Cleanup**: When rows are deleted, `_remove_from_row_order()` in `session_mixin.py` removes the tag from the persisted list

## Row Colors

Per-row background colors selectable via a droplet icon button in the Tag column. Persisted as `row_colors: {tag: "#hex"}` in `monitor_prefs.json`.

- **Picker**: `ColorPickerPopup` (in `table_helpers.py`) — 4x4 grid of muted color swatches + Clear button, opened via `_show_color_picker()` in `table_builder_mixin.py`
- **Rendering**: `SeparatorDelegate.paint()` reads `_row_colors` / `_row_tags` table properties and `fillRect`s the row background before the hover overlay
- **Text contrast**: `ensure_contrast()` adjusts text foreground against the row color for both `QTableWidgetItem` cells and child `QLabel`s in widget cells (skips `PulsingLabel`/`IndicatorLabel`)
- **Cleanup**: `_remove_pinned_session()` in `session_mixin.py` deletes the color entry when a row is removed

## Tag Aliases

Display aliases for tags, set via right-click context menu on the Tag column. Persisted as `aliases: {tag: "display name"}` in `monitor_prefs.json`.

- **Display**: Aliased tags show the alias in *italic*; the real tag is unchanged everywhere else (files, sockets, server, client)
- **Tooltip**: Aliased tags always show "Alias: X / Tag: Y" (regardless of tooltip setting). Regular tags show on hover when truncated or when "Show hover explanations" is on
- **Context menu**: Right-click tag cell → "Set alias" / "Rename alias" / "Remove alias" via `_show_tag_context_menu()` in `table_builder_mixin.py`
- **Cleanup**: `_remove_pinned_session()` and `_merge_sessions()` in `session_mixin.py` delete the alias entry when a row is removed
