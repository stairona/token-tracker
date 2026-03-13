# Token Tracker

Real-time token usage for Claude Code in your macOS menu bar.

## What It Does

Token Tracker reads local Claude Code session files (`~/.claude/projects/**/*.jsonl`) and shows live usage in the menu bar. It is offline-only: no API calls, no network traffic.

Key features:
- Multi-session awareness (shows the hottest session and other active projects)
- Context percentage with color indicator
- One-click handoff prompt copied to clipboard when usage is high
- Simple refresh button in the menu

## How It Works

1. Scans the session files under `~/.claude/projects/`
2. Reads the most recent non-zero token usage entries
3. Calculates usage as a percent of `CONTEXT_LIMIT`
4. Displays a summary in the menu bar and details in the dropdown

## Requirements

- macOS (uses `rumps` for the menu bar)
- Python 3.11 (Homebrew `/opt/homebrew/bin/python3.11` recommended)
- Python library: `rumps`

## Installation

```bash
pip install rumps

cd /path/to/token-tracker
/opt/homebrew/bin/python3.11 token_tracker.py &
```

Stop it with:

```bash
pkill -f token_tracker.py
```

## Auto-Launch with Claude Code

Add this to your `~/.zshrc` to run the tracker when you start Claude Code:

```zsh
function claude() {
  pkill -f token_tracker.py 2>/dev/null
  /opt/homebrew/bin/python3.11 /path/to/token-tracker/token_tracker.py &
  command claude "$@"
  pkill -f token_tracker.py 2>/dev/null
}
```

Replace `/path/to/token-tracker/` with your actual path.

## Menu Bar Indicators

| Icon | Usage | Action |
|------|-------|--------|
| 🟢 | Under 60% | No action needed |
| 🟡 | 60% - 85% | Consider running `/compact` |
| 🔴 | Above 85% | Run `/compact` immediately |

The dropdown shows:
- Tokens in/out
- Context bar and percent
- Primary project name
- Also active projects (if any)
- Handoff prompt button

## Multi-Session Behavior

Token Tracker scans all recent Claude Code sessions and highlights the one with the highest context usage. Other active projects appear in a compact "Also active" line so you can see what else is consuming context.

## Handoff Prompt

When your context usage is high (60%+), the menu shows a **Copy handoff prompt** button. This copies a ready-to-paste prompt that tells Claude to update `SESSION_HANDOFF.md` with:

- date/time
- project + cwd
- context usage
- what was done
- git branch/last commit
- files changed
- open next steps

After pasting the prompt in Claude, run `/compact` to free context.

## Configuration

Edit [token_tracker.py](token_tracker.py) to adjust:

- `CONTEXT_LIMIT`: model context size (default 262144)
- `POLL_INTERVAL`: refresh interval in seconds (default 10)
- `ACTIVE_WINDOW`: how long a session counts as active (default 1800 seconds)

## License

MIT
