# Leap

**A queueing system and dashboard for managing multiple AI CLI sessions.**

Run AI coding agents (Claude Code, Codex CLI, Cursor Agent, Gemini CLI) in any terminal (JetBrains, VS Code, Cursor, iTerm2, WezTerm, Arduino IDE, and more). Queue messages while the agent is busy, track all sessions from a single monitor, and jump straight to the right terminal with one click.

## Key Features

- **Smart message queueing** — Auto-sends when the CLI is ready
- **Real-time GUI monitoring** — See all sessions, jump across IDEs and projects
- **PR tracking** — GitLab & GitHub comment detection with `/leap` tag support
- **Slack integration** — Bidirectional messaging between Slack and Leap sessions
- **Prevent sleep while busy** — System stays awake until every session is idle (caffeinate on macOS, systemd-inhibit on Linux; optional lid-close override on macOS)

## Installation

**Platform:** macOS and Linux (full support, including the Monitor GUI). On Linux, install monitor dependencies first with `make install-monitor-deps`; on macOS, `make install-monitor` builds and installs the native app.

**Prerequisites:** Python 3.11+, and one or more AI CLIs: [Claude Code](https://docs.anthropic.com/en/docs/claude-code), [Codex CLI](https://github.com/openai/codex), [Cursor Agent](https://cursor.com/docs/cli/overview), [Gemini CLI](https://github.com/google-gemini/gemini-cli)

```bash
git clone https://github.com/nevo24/leap.git
cd leap
make install
source ~/.zshrc  # ~/.bashrc on Linux
```

Already installed? Run `leap --update` to pull the latest version and rebuild. If the update command fails, `cd` into the project directory and run `make update`.

Installed a new CLI / IDE / terminal **after** Leap? Run `leap --reconfigure` so Leap wires its hooks and IDE/terminal settings into the newly-installed tool. (`make install` skips anything that wasn't on disk at the time, so newly-installed tools start without integration.)

### Upgrading from ClaudeQ

The project was renamed from **ClaudeQ** (`claudeq`) to **Leap** (`leap`). If you have an existing ClaudeQ installation:

```bash
cd <path-to-your-claudeq-repo>
git pull
cd ..
mv claudeq leap
cd leap
make install    # runs migration + installs new 'leap' command
source ~/.zshrc  # ~/.bashrc on Linux
```

This migrates your storage, hooks, shell config, and monitor app automatically. The old `cq` / `claudeq` commands are replaced by `leap`.

## Usage

Just run `leap <tag>` — that's it! Leap wraps your AI CLI with queueing and session tracking.

```bash
leap my-feature         # First run starts a server
leap my-feature         # Second run connects a client (queue messages here)
^^hello world           # Type ^^ (quickly) in the server tab to queue directly
^^                      # Inside ^^: save msg to history (↑↓ to browse)
^^!!                    # Inside ^^: force-send next queued msg (Enter to confirm)
leap --resume           # Pick a past Leap tag; for Claude, resumes in your current cwd
                        # (transcript is relocated automatically — no `cd` needed)
```

The **Monitor** is a PyQt5 GUI that runs on both macOS and Linux. On macOS it installs as a native app (`make install-monitor`); on Linux run it directly with `make run-monitor`. See all your sessions at a glance:

![Leap Monitor](assets/leap-monitor.png)

## License

MIT License - see [LICENSE](LICENSE)

---

**Links:** [GitHub](https://github.com/nevo24/leap) • [Claude Code](https://docs.anthropic.com/en/docs/claude-code) • [Codex CLI](https://github.com/openai/codex) • [Cursor Agent](https://cursor.com/docs/cli/overview) • [Gemini CLI](https://github.com/google-gemini/gemini-cli)
