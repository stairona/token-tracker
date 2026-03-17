# Token Tracker

Real-time token usage for Claude Code in your macOS menu bar.

## What It Does

Token Tracker reads local Claude Code session files (`~/.claude/projects/**/*.jsonl`) and shows live usage in the menu bar. It is offline-only: no API calls, no network traffic.

Key features:
- Multi-session awareness (shows the hottest session and other active projects)
- Context percentage with color indicator
- One-click handoff prompt copied to clipboard when usage is high
- **Usage graphs** with time range selector and CSV export
- **Desktop notifications** when context exceeds thresholds
- **Configuration file** for easy customization
- Simple refresh button in the menu

## How It Works

1. Scans the session files under `~/.claude/projects/`
2. Reads the most recent non-zero token usage entries
3. Calculates usage as a percent of `CONTEXT_LIMIT`
4. Displays a summary in the menu bar and details in the dropdown
5. Records historical snapshots to `~/.cache/token-tracker/usage.db`

## Requirements

- macOS (uses `rumps` for the menu bar)
- Python 3.11+
- Python packages: `rumps` (required), `matplotlib` (optional, for graphs)

## Installation

### From Source

```bash
git clone https://github.com/stairona/token-tracker.git
cd token-tracker
pip install .
```

The `matplotlib` extra is optional: `pip install .[graphs]`

### Run

After installation, start the tracker:

```bash
token-tracker &
```

Or run directly from source:

```bash
/opt/homebrew/bin/python3.11 token_tracker.py &
```

Stop it with:

```bash
pkill -f token_tracker
# or if installed: killall token-tracker
```

## Auto-Launch with Claude Code

Add this to your `~/.zshrc` to run the tracker when you start Claude Code:

```zsh
function claude() {
  pkill -f token_tracker 2>/dev/null
  /opt/homebrew/bin/python3.11 /path/to/token-tracker/token_tracker.py &
  command claude "$@"
  pkill -f token_tracker 2>/dev/null
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

## Usage Graphs

Click **📊 Usage Graphs...** in the menu to open a window with two tabs:

- **Timeline**: Line chart of total token usage over time, with input tokens shaded.
- **Project Totals**: Horizontal bar chart showing total tokens per project.

### Graph Controls

- **Time range dropdown**: Select 7, 30, or 90 days to view different periods.
- **Export CSV...**: Export the timeline data to a CSV file for external analysis. Columns: timestamp, project_slug, input_tokens, output_tokens, total_tokens, context_pct, cwd.

### Graph Requirements

Graphs require `matplotlib` and `tkinter`:

```bash
pip install matplotlib
```

Tkinter is typically included with Python on macOS. If missing, install via Homebrew:

```bash
brew install python-tk
```

Or use a Python distribution that includes Tkinter (python.org installer).

### Data Retention

Historical data is stored in `~/.cache/token-tracker/usage.db` with 90-day retention by default.

## Desktop Notifications

When context usage crosses the warning (60%) or critical (85%) thresholds, the app sends a desktop notification. Notifications can be disabled in the configuration file.

## Configuration

Token Tracker can be customized via `~/.config/token-tracker/config.toml`. If the file doesn't exist, choose **Preferences...** from the menu to create a default one.

Example `config.toml`:

```toml
[display]
poll_interval = 10
context_limit = 262144
warn_pct = 60
critical_pct = 85
# Session label style: "basename", "path2", "full", or "custom"
label_style = "path2"
# Template for custom labels when label_style = "custom"
# Available placeholders: {cwd}, {basename}, {dirname}, {relhome}, {relhome_tilde}, {project}, {pct}
custom_label_template = "{relhome_tilde}"

[storage]
min_tokens_for_snapshot = 5000
retention_days = 90

[graphs]
default_days = 30
enable_notifications = true

[ui]
max_session_items = 5
max_files_to_scan = 50
poll_budget_sec = 8
file_op_timeout = 5
tail_read_bytes = 524288
```

Configuration is reloaded on app restart.

### Session Label Formats

The token tracker displays a label for each active Claude session. You can control the label format:

- **`basename`**: Show only the current directory name (e.g., `project`)
- **`path2`** (default): Show last two path components (e.g., `dev/project` or `work/api-server`)
- **`full`**: Show full path with home abbreviated (e.g., `~/dev/project`)
- **`custom`**: Use `custom_label_template` with placeholders:
  - `{cwd}` — full absolute path
  - `{basename}` — last directory name
  - `{dirname}` — parent directory
  - `{relhome}` — path relative to home (e.g., `dev/project`)
  - `{relhome_tilde}` — same but prefixed with `~` (e.g., `~/dev/project`)
  - `{project}` — Claude project folder name (cleaned)
  - `{pct}` — current context usage percentage (float)

**Example custom template**:
```toml
label_style = "custom"
custom_label_template = "{basename} [{pct:.0f}%]"
# Result: "project [42%]"
```

### Ghostty Integration

If you use Ghostty terminal, you can configure `label_style` to match your `tab-title-format`. For example:

- Ghostty: `tab-title-format = "{{.CWD}}"`
  → Token tracker: `label_style = "full"`

- Ghostty: `tab-title-format = "{{basename .CWD}}"`
  → Token tracker: `label_style = "basename"`

- Ghostty: `tab-title-format = "{{.Host}}/{{.CWD}}"`
  → Token tracker: `label_style = "custom"` with `custom_label_template = "{relhome_tilde}"`

This keeps your token tracker session labels consistent with what you see in Ghostty tabs.

## Multi-Session Behavior

Token Tracker scans all recent Claude Code sessions and highlights the one with the highest context usage. Other active projects appear in a compact "Also active" line so you can see what else is consuming context.

## Handoff Prompt

When your context usage is high (60%+), the menu shows a **Copy handoff prompt** button. This copies a ready-to-paste prompt that tells Claude to update `SESSION_HANDOFF.md` with:

- date/time
- project + cwd
- context usage
- what was accomplished
- current git branch and last commit
- files changed or created
- open items and exact next steps
- commands the next session needs to run first

After pasting the prompt in Claude, run `/compact` to free context.

## Project Layout

```
token-tracker/
├── README.md
├── token_tracker.py
├── config.py
├── storage.py
├── pyproject.toml
└── LICENSE
```

## Development

To install in editable mode for development:

```bash
pip install -e .
```

With graph support:

```bash
pip install -e ".[graphs]"
```

## License

MIT
