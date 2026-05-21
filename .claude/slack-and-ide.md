# Slack Integration & IDE Setup

Details for Slack bot data flow and IDE-specific configuration. Load when working on the Slack integration or IDE hook/config setup (JetBrains, VS Code/Cursor, iTerm2, WezTerm).

## Slack Integration

Optional Slack app for bidirectional Leap ↔ Slack communication. Each session gets a thread in the user's DM.

```bash
make install-slack-app   # Install deps + guided setup wizard
leap --slack                 # Start the bot daemon
```

**Data flow**: Claude finishes → hook reads transcript JSONL → writes to signal file → `OutputCapture` writes `.last_response` → `OutputWatcher` posts to Slack. Replies: Slack thread → `MessageRouter` → queue or direct message via socket.

Bot can also be started/stopped from the monitor's **Slack Bot** button. Dependencies: `slack-bolt`, `slack-sdk` (optional poetry group).

## IDE Setup

All IDEs are **automatically configured during `make install`**. Run `leap --reconfigure` after installing a new IDE post-Leap.

### JetBrains (PyCharm, IntelliJ, etc.)
Terminal Engine set to Classic, "Show application title" enabled. Restart IDEs after installation.

### VS Code / Cursor
Terminal selector extension auto-installed, tabs show numbered labels. Extension also configures Shift+Enter to send a distinct CSI u sequence so the client can distinguish it from plain Enter. Cursor (VS Code fork) is detected separately via `__CFBundleIdentifier` and uses its own CLI (`cursor`), settings path, and AppleScript app name. The same `.vsix` extension is installed into both editors.

### iTerm2
CSI u (Kitty keyboard protocol) enabled in all profiles so Shift+Enter sends a distinct sequence. Restart iTerm2 after installation for the change to take effect.

### WezTerm
`enable_csi_u_key_encoding = true` added to Lua config (`~/.wezterm.lua` or `~/.config/wezterm/wezterm.lua`) so Shift+Enter sends a distinct CSI u sequence. Creates a new config file if none exists. Restart WezTerm after installation for the change to take effect. Full monitor navigation support via `wezterm cli` (navigate, close, open tabs).
