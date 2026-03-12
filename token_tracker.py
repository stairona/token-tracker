#!/usr/bin/env python3
"""
Claude Code Token Tracker — macOS Menu Bar App
Reads live token usage directly from Claude Code local session files.
No API calls needed — works entirely offline.
"""

import rumps
import json
import os
import glob
import threading
from datetime import datetime
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
POLL_INTERVAL = 10  # seconds
CONTEXT_LIMIT = 262144  # stepfun/step-3.5-flash:free


# ── Helpers ───────────────────────────────────────────────────────────────────
def get_latest_session_tokens():
    """
    Find most recently modified .jsonl session file and read
    input + output tokens from message.usage, skipping zero entries.
    """
    try:
        pattern = str(CLAUDE_PROJECTS_DIR / "**" / "*.jsonl")
        files = glob.glob(pattern, recursive=True)
        files = [f for f in files if "subagents" not in f]

        if not files:
            return 0, 0, "No sessions found"

        latest = max(files, key=os.path.getmtime)

        # Clean up project name
        parent = Path(latest).parent.name
        project = parent.replace("-Users-nicolasaguirre-Development-light-projects", "light-projects")
        project = project.replace("-Users-nicolasaguirre-Development-", "")
        project = project.strip("-") or "unknown"

        input_tokens = 0
        output_tokens = 0

        with open(latest, "r") as f:
            lines = f.readlines()

        # Scan in reverse, skip zero entries, read from message.usage
        for line in reversed(lines):
            try:
                entry = json.loads(line.strip())
                msg = entry.get("message", {})
                if not isinstance(msg, dict):
                    continue
                usage = msg.get("usage", {})
                if not usage:
                    continue
                inp = usage.get("input_tokens", 0) or 0
                out = usage.get("output_tokens", 0) or 0
                if inp > 0 or out > 0:
                    input_tokens = inp
                    output_tokens = out
                    break
            except (json.JSONDecodeError, KeyError):
                continue

        return input_tokens, output_tokens, project

    except Exception as e:
        return 0, 0, f"Error: {e}"


def format_tokens(n):
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def pct_bar(pct, width=10):
    filled = int(width * pct / 100)
    return "█" * filled + "░" * (width - filled)


# ── Menu Bar App ──────────────────────────────────────────────────────────────
class TokenTrackerApp(rumps.App):
    def __init__(self):
        super().__init__("⏳", quit_button=None)

        self.session_item = rumps.MenuItem("Reading session...")
        self.context_item = rumps.MenuItem("Context: —")
        self.project_item = rumps.MenuItem("Project: —")
        self.updated_item = rumps.MenuItem("Updated: —")
        self.compact_tip = rumps.MenuItem("💡 Run /compact to free context")
        self.refresh_item = rumps.MenuItem("Refresh now", callback=self.refresh_now)
        self.quit_item = rumps.MenuItem("Quit", callback=rumps.quit_application)

        self.menu = [
            self.session_item,
            self.context_item,
            self.project_item,
            None,
            self.compact_tip,
            None,
            self.updated_item,
            self.refresh_item,
            None,
            self.quit_item,
        ]

        self._start_polling()

    def _start_polling(self):
        thread = threading.Thread(target=self._poll_loop, daemon=True)
        thread.start()

    def _poll_loop(self):
        while True:
            self._update()
            threading.Event().wait(POLL_INTERVAL)

    def _update(self):
        input_tokens, output_tokens, project = get_latest_session_tokens()
        ctx_pct = (input_tokens / CONTEXT_LIMIT) * 100 if input_tokens else 0
        now = datetime.now().strftime("%H:%M:%S")

        if ctx_pct >= 85:
            icon = "🔴"
        elif ctx_pct >= 60:
            icon = "🟡"
        else:
            icon = "🟢"

        self.title = f"{icon} {format_tokens(input_tokens)}"
        self.session_item.title = f"In: {input_tokens:,}  Out: {output_tokens:,} tokens"
        bar = pct_bar(ctx_pct)
        self.context_item.title = (
            f"Context: {bar} {ctx_pct:.0f}%  "
            f"({format_tokens(input_tokens)}/{format_tokens(CONTEXT_LIMIT)})"
        )
        self.project_item.title = f"Project: {project}"

        if ctx_pct >= 60:
            self.compact_tip.title = "⚠️  Run /compact to free context!"
        else:
            self.compact_tip.title = "💡 Run /compact to free context"

        self.updated_item.title = f"Updated: {now}"

    @rumps.clicked("Refresh now")
    def refresh_now(self, _):
        self.title = "⏳"
        threading.Thread(target=self._update, daemon=True).start()


# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    TokenTrackerApp().run()
