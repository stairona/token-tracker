#!/usr/bin/env python3
"""
Claude Code Token Tracker — macOS Menu Bar App
- Tracks ALL active Claude sessions (modified within 5 min) across terminals
- Labels each session clearly by project name derived from cwd
- Generates a SESSION_HANDOFF update prompt + copies to clipboard near limit

THREADING RULE: Menu items are created ONCE in __init__.
Only .title is mutated from the background poll thread — the only
thread-safe pattern for rumps/NSMenu. Never call menu.add/clear from a thread.
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
POLL_INTERVAL = 10        # seconds between polls
CONTEXT_LIMIT = 262144    # stepfun/step-3.5-flash:free — DO NOT CHANGE
ACTIVE_WINDOW = 300       # seconds — session "active" if file modified within this
WARN_PCT = 60             # yellow threshold
CRITICAL_PCT = 85         # red threshold
MAX_SESSIONS = 4          # max tracked sessions shown in "Also active" summary


# ── Session reading ───────────────────────────────────────────────────────────
def _clean_project_name(folder_name: str) -> str:
    name = folder_name
    for prefix in [
        "-Users-nicolasaguirre-Development-light-projects-",
        "-Users-nicolasaguirre-Development-light-projects",
        "-Users-nicolasaguirre-Development-",
        "-Users-nicolasaguirre-",
    ]:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return name.strip("-").replace("-", " ").strip() or "Development"


def _read_tokens(path: str):
    """Return (input_tokens, output_tokens, cwd) from most recent non-zero usage entry."""
    inp = out = 0
    cwd = ""
    try:
        with open(path, "r", errors="replace") as fh:
            lines = fh.readlines()
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


def get_active_sessions():
    """Return list of active session dicts, sorted freshest-first, de-duped by label."""
    pattern = str(CLAUDE_PROJECTS_DIR / "**" / "*.jsonl")
    files = [f for f in glob.glob(pattern, recursive=True) if "subagents" not in f]
    files.sort(key=os.path.getmtime, reverse=True)
    now = time.time()
    seen, sessions = set(), []
    for path in files:
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if now - mtime > ACTIVE_WINDOW:
            continue
        inp, out, cwd = _read_tokens(path)
        label = Path(cwd).name if cwd else _clean_project_name(Path(path).parent.name)
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
        })
        if len(sessions) >= MAX_SESSIONS:
            break
    return sessions


# ── Handoff prompt ────────────────────────────────────────────────────────────
def build_handoff_prompt(session: dict) -> str:
    cwd = session["cwd"] or "unknown"
    pct = session["pct"]
    inp = session["input_tokens"]
    out = session["output_tokens"]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    handoff_path = str(Path(cwd) / "SESSION_HANDOFF.md") if cwd != "unknown" else "SESSION_HANDOFF.md"
    return (
        f"=== SESSION HANDOFF UPDATE — paste into Claude ===\n\n"
        f"Context is at {pct:.0f}% ({inp:,} / {CONTEXT_LIMIT:,} tokens).\n\n"
        f"1. Update {handoff_path} with the current session state.\n"
        f"   Include:\n"
        f"   - Date: {now}\n"
        f"   - Project: {session['label']}\n"
        f"   - Working directory: {cwd}\n"
        f"   - Context at handoff: {pct:.0f}% ({inp:,} in / {out:,} out)\n"
        f"   - What was done this session (summarize from conversation history)\n"
        f"   - Current git branch and last commit hash\n"
        f"   - Files changed or created\n"
        f"   - Open items / next steps\n"
        f"   - Commands the next session needs to run first\n\n"
        f"2. After updating SESSION_HANDOFF.md, run /compact to free context.\n\n"
        f"Do NOT delete any existing SESSION_HANDOFF.md content.\n"
        f"Prepend the new session block above previous entries.\n\n"
        f"=== END PROMPT ==="
    )


def copy_to_clipboard(text: str):
    try:
        subprocess.run(["pbcopy"], input=text.encode(), check=True)
    except Exception:
        pass


# ── Helpers ───────────────────────────────────────────────────────────────────
def format_tokens(n):
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def pct_bar(pct, width=10):
    filled = int(width * pct / 100)
    return "█" * filled + "░" * (width - filled)


def icon_for_pct(pct):
    if pct >= CRITICAL_PCT:
        return "🔴"
    if pct >= WARN_PCT:
        return "🟡"
    return "🟢"


# ── Menu Bar App ──────────────────────────────────────────────────────────────
class TokenTrackerApp(rumps.App):
    """
    Fixed menu structure — items created ONCE, only .title mutated from thread.
    Primary session: shown in full detail (topmost active session by recency).
    Secondary sessions: compact one-line summary.
    Handoff button: appears when primary session >= WARN_PCT.
    """

    def __init__(self):
        super().__init__("⏳", quit_button=None)

        # ── Fixed menu items (created once, titles updated in poll thread) ──
        self.primary_tokens = rumps.MenuItem("In: —  Out: — tokens")
        self.primary_ctx    = rumps.MenuItem("Context: — ")
        self.primary_proj   = rumps.MenuItem("Project: —")
        self.others_item    = rumps.MenuItem("")           # "Also active: ..."
        self.compact_tip    = rumps.MenuItem("💡 Run /compact to free context")
        self.handoff_btn    = rumps.MenuItem("📋 Copy handoff prompt", callback=self._copy_handoff)
        self.updated_item   = rumps.MenuItem("Updated: —")
        self.refresh_item   = rumps.MenuItem("Refresh now", callback=self.refresh_now)
        self.quit_item      = rumps.MenuItem("Quit", callback=rumps.quit_application)

        self.menu = [
            self.primary_tokens,
            self.primary_ctx,
            self.primary_proj,
            None,
            self.others_item,
            None,
            self.compact_tip,
            self.handoff_btn,
            None,
            self.updated_item,
            self.refresh_item,
            None,
            self.quit_item,
        ]

        self._hottest_session = None   # safe to read from main thread callback
        self._start_polling()

    # ── Polling (background thread — only mutates .title, never menu structure) ──
    def _start_polling(self):
        threading.Thread(target=self._poll_loop, daemon=True).start()

    def _poll_loop(self):
        while True:
            self._update()
            threading.Event().wait(POLL_INTERVAL)

    def _update(self):
        sessions = get_active_sessions()
        now_str = datetime.now().strftime("%H:%M:%S")

        if not sessions:
            self.title = "⚪ idle"
            self.primary_tokens.title = "No active sessions"
            self.primary_ctx.title    = ""
            self.primary_proj.title   = ""
            self.others_item.title    = ""
            self.compact_tip.title    = "💡 Run /compact to free context"
            self.handoff_btn.title    = ""
            self.updated_item.title   = f"Updated: {now_str}"
            self._hottest_session     = None
            return

        # Primary = hottest (highest pct) session
        primary = max(sessions, key=lambda s: s["pct"])
        self._hottest_session = primary
        pct  = primary["pct"]
        inp  = primary["input_tokens"]
        out  = primary["output_tokens"]
        icon = icon_for_pct(pct)
        bar  = pct_bar(pct)
        label = primary["label"]

        # Title bar: icon + compact token count + project name
        self.title = f"{icon} {format_tokens(inp)} — {label}"

        # Dropdown rows
        self.primary_tokens.title = f"In: {inp:,}   Out: {out:,} tokens"
        self.primary_ctx.title = (
            f"Context: {bar} {pct:.0f}%  "
            f"({format_tokens(inp)}/{format_tokens(CONTEXT_LIMIT)})"
        )
        self.primary_proj.title = f"Project: {label}"

        # Secondary sessions compact summary
        others = [s for s in sessions if s["label"] != label]
        if others:
            parts = [f"{s['label']} {s['pct']:.0f}%" for s in others]
            self.others_item.title = "Also active: " + "  |  ".join(parts)
        else:
            self.others_item.title = ""

        # Compact tip + handoff button
        if pct >= CRITICAL_PCT:
            self.compact_tip.title = f"⛔ STOP — run /compact NOW in {label}"
            self.handoff_btn.title = f"🚨 Copy URGENT handoff prompt ({label})"
        elif pct >= WARN_PCT:
            self.compact_tip.title = f"⚠️  Run /compact soon in {label}"
            self.handoff_btn.title = f"📋 Copy handoff prompt ({label})"
        else:
            self.compact_tip.title = "💡 Run /compact to free context"
            self.handoff_btn.title = ""

        self.updated_item.title = f"Updated: {now_str}"

    # ── Callbacks (main thread — safe to read _hottest_session) ──────────────
    def _copy_handoff(self, _):
        session = self._hottest_session
        if not session:
            return
        prompt = build_handoff_prompt(session)
        copy_to_clipboard(prompt)
        rumps.notification(
            title="Handoff Prompt Copied",
            subtitle=session["label"],
            message="Paste into Claude, then run /compact",
            sound=True,
        )

    @rumps.clicked("Refresh now")
    def refresh_now(self, _):
        self.title = "⏳"
        threading.Thread(target=self._update, daemon=True).start()


# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    TokenTrackerApp().run()
