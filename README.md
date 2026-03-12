# Claude Code Token Tracker

**Real-time token usage monitoring for Claude Code — right in your macOS menu bar.**

---

## What It Does

Claude Code Token Tracker displays your current token usage in the macOS menu bar, giving you instant visibility into how much of your context window you're using while working with Claude Code.

The app reads your live Claude Code session data directly from local files (`~/.claude/projects/`) and updates every 10 seconds. No API calls, no network traffic — completely offline and private.

---

## Why It's Useful

Claude Code models have finite context windows. When you exceed these limits, you start losing conversation history and may need to restart sessions. This tool helps you:

- **Monitor usage in real-time** without interrupting your workflow
- **Know when to run `/compact`** to free up context before hitting limits
- **Avoid surprise session resets** due to context overflow
- **Track token consumption** across different projects

---

## How It Works

1. Polls the `~/.claude/projects/` directory for the most recently modified `.jsonl` session file
2. Extracts `input_tokens` and `output_tokens` from the latest non-zero usage entry
3. Calculates the percentage of your context limit being used
4. Displays the information in the menu bar with color-coded indicators

All processing happens locally on your machine. No data is sent to any external server.

---

## Requirements

- **macOS only** (uses the `rumps` library for menu bar integration)
- **Python 3.11** (installed via Homebrew at `/opt/homebrew/bin/python3.11`)
- **Python libraries:** `rumps` and `requests`

---

## Installation

```bash
# Install required Python packages
pip install rumps requests

# Clone or download this repository
cd /path/to/claude-token-tracker

# Run the app
/opt/homebrew/bin/python3.11 token_tracker.py &
```

To stop it: `pkill -f token_tracker.py`

---

## Auto-Launch with Claude Code

Add this function to your `~/.zshrc` so the tracker launches automatically every time you run `claude` and stops when you exit:

```zsh
function claude() {
  pkill -f token_tracker.py 2>/dev/null
  /opt/homebrew/bin/python3.11 /path/to/claude-token-tracker/token_tracker.py &
  command claude "$@"
  pkill -f token_tracker.py 2>/dev/null
}
```

Replace `/path/to/claude-token-tracker/` with the actual path. Restart your shell or run `source ~/.zshrc` to activate.

---

## Menu Bar Indicators

| Icon | Usage | Action |
|------|-------|--------|
| 🟢 | **Under 60%** | Comfortable — no action needed |
| 🟡 | **60% - 85%** | Consider running `/compact` soon |
| 🔴 | **Above 85%** | Run `/compact` immediately |

Click the app's dropdown menu to see detailed statistics and a "Refresh now" button.

---

## Context Window Limits

Different Claude Code models have different context sizes. The default limit in the code is set for `stepfun/step-3.5-flash:free`:

| Model | Context Limit |
|-------|---------------|
| stepfun/step-3.5-flash:free | 262,144 tokens |
| qwen/qwen3-coder:free | 131,072 tokens |
| openrouter/free | varies (check provider) |

---

## Changing the Context Limit

Edit `token_tracker.py` at line 19:

```python
CONTEXT_LIMIT = 262144  # Change this to your model's limit
```

For example, for `qwen/qwen3-coder:free`:
```python
CONTEXT_LIMIT = 131072
```

You can also adjust the poll interval (line 18) if you want more or less frequent updates.

---

## License

MIT

---

**Happy coding!** May your context windows stay spacious and your sessions uninterrupted.
