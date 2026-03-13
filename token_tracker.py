#!/usr/bin/env python3
"""
Claude Code Token Tracker — macOS Menu Bar App
Reads live token usage from ~/.claude/projects/ session files.
No API calls. Works offline. Auto-launches with Claude Code via ~/.zshrc.

Features:
- Real-time context % with color indicator
- Handoff prompt copied to clipboard when context is high
- Multi-session awareness (shows other active projects)
"""

import rumps
import json
import os
import glob
import time
import threading
import subprocess
from datetime import datetime
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
POLL_INTERVAL  = 10       # seconds between polls
CONTEXT_LIMIT  = 262144   # stepfun/step-3.5-flash:free
ACTIVE_WINDOW  = 1800     # seconds — session shown if modified within 30 min
WARN_PCT       = 60       # yellow threshold
CRITICAL_PCT   = 85       # red threshold


# ── Session helpers ───────────────────────────────────────────────────────────
def _clean_name(folder: str) -> str:
    """Turn a hashed Claude project folder name into a readable project name."""
    name = folder
    for prefix in [
        "-Users-nicolasaguirre-Development-light-projects-",
        "-Users-nicolasaguirre-Development-light-projects",
        "-Users-nicolasaguirre-Development-",
        "-Users-nicolasaguirre-",
    ]:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    cleaned = name.strip("-").replace("-", " ").strip()
    return cleaned or "unknown"


def _read_tokens(path: str):
    """Read (input_tokens, output_tokens, cwd) from most recent non-zero usage entry."""
    inp = out = 0
    cwd = ""
    try:
        with open(path, "r", errors="replace") as f:
            lines = f.readlines()
        for line in reversed(lines):
            try:
                e = json.loads(line.strip())
                if not cwd:
                    cwd = e.get("cwd", "")
                msg = e.get("message", {})
                if not isinstance(msg, dict):
                    continue
                u = msg.get("usage", {})
                if not u:
                    continue
                i = u.get("input_tokens", 0) or 0
                o = u.get("output_tokens", 0) or 0
                if i or o:
                    inp, out = i, o
                    break
            except (json.JSONDecodeError, KeyError):
                continue
    except OSError:
        pass
    return inp, out, cwd


def get_sessions():
    """
    Return all sessions modified within ACTIVE_WINDOW, sorted by recency.
    Falls back to the single most recent session if none are within the window.
    """
    pattern = str(CLAUDE_PROJECTS_DIR / "**" / "*.jsonl")
    files = [f for f in glob.glob(pattern, recursive=True) if "subagents" not in f]
    if not files:
        return []
    files.sort(key=os.path.getmtime, reverse=True)
    now = time.time()

    sessions = []
    seen = set()
    for path in files:
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        inp, out, cwd = _read_tokens(path)
        label = Path(cwd).name if cwd else _clean_name(Path(path).parent.name)
        if label in seen:
            continue
        seen.add(label)
        sessions.append({
            "label": label,
            "input_tokens": inp,
            "output_tokens": out,
            "cwd": cwd,
            "pct": (inp / CONTEXT_LIMIT * 100) if inp else 0.0,
            "mtime": mtime,
            "active": (now - mtime) <= ACTIVE_WINDOW,
        })

    # Always return at least the most recent session even if outside window
    active = [s for s in sessions if s["active"]]
    return active if active else sessions[:1]


# ── Handoff prompt ────────────────────────────────────────────────────────────
def build_handoff_prompt(session: dict) -> str:
    cwd  = session["cwd"] or "unknown"
    pct  = session["pct"]
    inp  = session["input_tokens"]
    out  = session["output_tokens"]
    now  = datetime.now().strftime("%Y-%m-%d %H:%M")
    handoff_path = str(Path(cwd) / "SESSION_HANDOFF.md") if cwd != "unknown" else "SESSION_HANDOFF.md"
    return (
        f"Context is at {pct:.0f}% ({inp:,} / {CONTEXT_LIMIT:,} tokens). "
        f"Please update {handoff_path} with:\n"
        f"- Date: {now}\n"
        f"- Project: {session['label']} | cwd: {cwd}\n"
        f"- Context: {pct:.0f}% ({inp:,} in / {out:,} out)\n"
        f"- What was accomplished this session\n"
        f"- Current git branch and last commit\n"
        f"- Files changed or created\n"
        f"- Open items and exact next steps\n"
        f"- Commands the next session needs to run first\n\n"
        f"Prepend this block above any existing entries. Do NOT delete old content.\n"
        f"Then run /compact to free context."
    )


def copy_to_clipboard(text: str) -> bool:
    """Copy text to macOS clipboard using pbcopy. Returns True on success."""
    try:
        result = subprocess.run(
            ["pbcopy"],
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=3,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[token-tracker] clipboard error: {e}")
        return False


# ── Display helpers ───────────────────────────────────────────────────────────
def format_tokens(n):
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def format_limit(n):
    """Always show context limit in compact form e.g. 262k."""
    return f"{n // 1000}k"


def pct_bar(pct, width=12):
    """Smooth proportional bar using half-block characters for cleaner look."""
    filled = int(width * pct / 100)
    filled = max(0, min(width, filled))
    return "▓" * filled + "░" * (width - filled)


def icon(pct):
    if pct >= CRITICAL_PCT:
        return "🔴"
    if pct >= WARN_PCT:
        return "🟡"
    return "🟢"


# ── App ───────────────────────────────────────────────────────────────────────
class TokenTrackerApp(rumps.App):
    """
    Menu items are created ONCE in __init__ and their .title is updated
    from the background polling thread. rumps is thread-safe for .title updates.
    No menu.add() or menu.clear() calls after init — that causes crashes.
    """

    def __init__(self):
        super().__init__("⏳", quit_button=None)

        # All menu items declared once
        self.item_tokens   = rumps.MenuItem("In: —   Out: — tokens")
        self.item_ctx      = rumps.MenuItem("Context: —")
        self.item_project  = rumps.MenuItem("Project: —")
        self.item_others   = rumps.MenuItem(" ")           # secondary sessions
        self.item_tip      = rumps.MenuItem("💡 Run /compact to free context")
        self.item_handoff  = rumps.MenuItem("📋 Copy handoff prompt", callback=self._on_handoff)
        self.item_updated  = rumps.MenuItem("Updated: —")
        self.item_refresh  = rumps.MenuItem("Refresh now", callback=self._on_refresh)
        self.item_quit     = rumps.MenuItem("Quit", callback=rumps.quit_application)

        self.menu = [
            self.item_tokens,
            self.item_ctx,
            self.item_project,
            None,
            self.item_others,
            None,
            self.item_tip,
            self.item_handoff,
            None,
            self.item_updated,
            self.item_refresh,
            None,
            self.item_quit,
        ]

        self._primary = None  # set by polling thread, read by callbacks
        threading.Thread(target=self._poll_loop, daemon=True).start()

    # ── Polling ───────────────────────────────────────────────────────────────
    def _poll_loop(self):
        while True:
            try:
                self._update()
            except Exception as e:
                self.title = "❌"
                print(f"[token-tracker] poll error: {e}")
            threading.Event().wait(POLL_INTERVAL)

    def _update(self):
        sessions = get_sessions()
        now_str  = datetime.now().strftime("%H:%M:%S")

        if not sessions:
            self.title             = "⚪ idle"
            self.item_tokens.title = "No Claude sessions found"
            self.item_ctx.title    = "Context: —"
            self.item_project.title= "Project: —"
            self.item_others.title = " "
            self.item_tip.title    = "💡 Run /compact to free context"
            self.item_handoff.title= "📋 Copy handoff prompt"
            self.item_updated.title= f"Updated: {now_str}"
            self._primary          = None
            return

        # Hottest session = highest context usage
        primary = max(sessions, key=lambda s: s["pct"])
        self._primary = primary
        pct   = primary["pct"]
        inp   = primary["input_tokens"]
        out   = primary["output_tokens"]
        label = primary["label"]
        bar   = pct_bar(pct)

        # Menu bar — show usage/total clearly
        self.title = f"{icon(pct)} {format_tokens(inp)}/{format_limit(CONTEXT_LIMIT)}"

        # Dropdown
        self.item_tokens.title  = f"In: {inp:,}   Out: {out:,} tokens"
        self.item_ctx.title     = (
            f"Context: {bar} {pct:.0f}%"
            f"  ({format_tokens(inp)}/{format_tokens(CONTEXT_LIMIT)})"
        )
        self.item_project.title = f"Project: {label}"

        # Other active sessions
        others = [s for s in sessions if s["label"] != label]
        if others:
            parts = [f"{s['label']} {s['pct']:.0f}%" for s in others[:3]]
            self.item_others.title = "Also active: " + " | ".join(parts)
        else:
            self.item_others.title = " "

        # Tip + handoff button
        if pct >= CRITICAL_PCT:
            self.item_tip.title     = f"⛔ Run /compact NOW — context critical"
            self.item_handoff.title = f"📋 Copy handoff prompt"
        elif pct >= WARN_PCT:
            self.item_tip.title     = f"⚠️  Context high — consider /compact"
            self.item_handoff.title = f"📋 Copy handoff prompt"
        else:
            self.item_tip.title     = "💡 Run /compact to free context"
            self.item_handoff.title = "📋 Copy handoff prompt"

        self.item_updated.title = f"Updated: {now_str}"

    # ── Callbacks ─────────────────────────────────────────────────────────────
    def _on_handoff(self, _):
        session = self._primary
        if not session:
            return
        prompt = build_handoff_prompt(session)
        success = copy_to_clipboard(prompt)
        original = self.item_handoff.title
        self.item_handoff.title = "✅ Copied! Paste into Claude" if success else "❌ Copy failed — check terminal"
        threading.Timer(2.5, lambda: setattr(self.item_handoff, "title", original)).start()

    def _on_refresh(self, _):
        self.title = "⏳"
        threading.Thread(target=self._update, daemon=True).start()


# ── Entry ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    TokenTrackerApp().run()
