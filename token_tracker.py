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
from storage import get_storage

# ── Config ────────────────────────────────────────────────────────────────────
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
HANDOFF_ROOT_ENV = os.getenv("HANDOFF_ROOT")
HANDOFF_ROOT = Path(HANDOFF_ROOT_ENV) if HANDOFF_ROOT_ENV else None
POLL_INTERVAL  = 10       # seconds between polls
CONTEXT_LIMIT  = 262144   # stepfun/step-3.5-flash:free
ACTIVE_WINDOW  = 1800     # seconds — session shown if modified within 30 min
WARN_PCT       = 60       # yellow threshold
CRITICAL_PCT   = 85       # red threshold
TAIL_READ_BYTES = 512 * 1024  # read tail first for large logs
MAX_SESSION_ITEMS = 5         # max sessions shown in the picker
MAX_FILES_TO_SCAN = 50        # maximum session files to examine per poll (prevents hanging on huge file systems)
POLL_BUDGET_SEC = 8           # maximum seconds to spend in a single poll cycle (timeout safeguard)
FILE_OP_TIMEOUT = 5           # seconds timeout for file read operations

# Cache token parsing by file signature (mtime, size)
_TOKEN_CACHE = {}


# ── Session helpers ───────────────────────────────────────────────────────────
def _clean_name(folder: str) -> str:
    """Turn a hashed Claude project folder name into a readable project name."""
    name = folder
    home_parts = str(Path.home()).strip("/").split("/")
    home_prefixes = []
    if home_parts:
        joined = "-".join(home_parts)
        home_prefixes = [f"-{joined}-", f"-{joined}"]
    for prefix in home_prefixes:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    if name.startswith("-"):
        parts = name.strip("-").split("-")
        if len(parts) >= 3 and parts[0] == "Users":
            # Trim "/Users/<username>" style prefixes for portability.
            name = "-".join(parts[2:])
    cleaned = name.strip("-").replace("-", " ").strip()
    return cleaned or "unknown"


def _project_slug_from_cwd(cwd: str) -> str:
    """Derive a project slug from cwd, preferring the segment after light-projects."""
    if not cwd:
        return "unknown"
    parts = Path(cwd).parts
    try:
        idx = parts.index("light-projects")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    except ValueError:
        pass
    return Path(cwd).name or "unknown"


def _read_tokens(path: str):
    """Read (input_tokens, output_tokens, cwd) from most recent non-zero usage entry."""
    inp = out = 0
    cwd = ""
    sig = (0, 0)
    try:
        stat = os.stat(path)
        sig = (stat.st_mtime, stat.st_size)

        # Skip extremely large files to avoid memory/time issues (unlikely but safe)
        if stat.st_size > 100_000_000:  # 100 MB
            print(f"[token-tracker] skip large file: {path} ({stat.st_size} bytes)")
            return 0, 0, ""

        cached = _TOKEN_CACHE.get(path)
        if cached and cached[0] == sig:
            return cached[1], cached[2], cached[3]

        def parse_lines(lines):
            nonlocal inp, out, cwd
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
                        return True
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
            return False

        with open(path, "rb") as f:
            size = stat.st_size
            start = max(0, size - TAIL_READ_BYTES)
            f.seek(start)
            chunk = f.read().decode("utf-8", errors="replace")
            if start > 0:
                parts = chunk.splitlines()
                lines = parts[1:] if len(parts) > 1 else []
            else:
                lines = chunk.splitlines()
            found = parse_lines(lines)

            if not found and start > 0:
                # Rare: the non-zero entry might be before the tail; read whole file as fallback
                # But only if file isn't huge (already checked)
                f.seek(0)
                full_lines = f.read().decode("utf-8", errors="replace").splitlines()
                parse_lines(full_lines)
    except Exception as e:
        # Comprehensive catch: OSError, JSON errors, etc.
        # Do not propagate; just return zeros and log minimal message to avoid spam
        # Use print since logging may not be configured.
        print(f"[token-tracker] error reading {path}: {e}")
    finally:
        # Always update cache with what we found (could be zeros)
        _TOKEN_CACHE[path] = (sig, inp, out, cwd)
    return inp, out, cwd


def get_sessions():
    """
    Return all sessions modified within ACTIVE_WINDOW, sorted by recency.
    Falls back to the single most recent session if none are within the window.
    Implements resilience: limits files scanned, enforces poll budget timeout.
    """
    pattern = str(CLAUDE_PROJECTS_DIR / "**" / "*.jsonl")
    try:
        all_files = [f for f in glob.glob(pattern, recursive=True) if "subagents" not in f]
    except Exception as e:
        print(f"[token-tracker] glob error: {e}")
        return []

    if not all_files:
        return []

    # Sort by modification time (newest first) and limit scan to protect against huge filesystems
    all_files.sort(key=os.path.getmtime, reverse=True)
    files = all_files[:MAX_FILES_TO_SCAN]

    now = time.time()
    newest = files[0]

    sessions = []
    seen = set()
    start_time = time.time()

    for path in files:
        # Budget check: if we've spent too much time, stop scanning
        if time.time() - start_time > POLL_BUDGET_SEC:
            print(f"[token-tracker] poll budget exhausted after processing {len(sessions)} sessions")
            break

        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if path != newest and (now - mtime) > ACTIVE_WINDOW:
            continue
        try:
            inp, out, cwd = _read_tokens(path)
        except Exception as e:
            # Don't let one bad file break the whole poll
            print(f"[token-tracker] skip {path}: {e}")
            continue
        label = Path(cwd).name if cwd else _clean_name(Path(path).parent.name)
        session_key = cwd or str(Path(path).parent)
        if session_key in seen:
            continue
        seen.add(session_key)
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
    if HANDOFF_ROOT:
        slug = _project_slug_from_cwd(cwd).lower().replace(" ", "-")
        handoff_path = str(HANDOFF_ROOT / "projects" / f"{slug}.md")
    else:
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
    """Colored emoji block bar — green/yellow/red matching context thresholds."""
    filled = int(width * pct / 100)
    filled = max(1, min(width, filled)) if pct > 0 else 0
    empty  = width - filled
    if pct >= CRITICAL_PCT:
        block = "🟥"
    elif pct >= WARN_PCT:
        block = "🟨"
    else:
        block = "🟩"
    return block * filled + "⬜" * empty


def icon(pct):
    if pct >= CRITICAL_PCT:
        return "🔴"
    if pct >= WARN_PCT:
        return "🟡"
    return "🟢"


# ── App ───────────────────────────────────────────────────────────────────────
class TokenTrackerApp(rumps.App):
    """
    Menu items are created ONCE in __init__.
    Background thread only computes state; UI updates happen in timer callback.
    No menu.add() or menu.clear() calls after init — that causes crashes.
    """

    def __init__(self):
        super().__init__("⏳", quit_button=None)

        # All menu items declared once
        self.item_tokens   = rumps.MenuItem("In: —   Out: — tokens")
        self.item_ctx      = rumps.MenuItem("Context: —")
        self.item_project  = rumps.MenuItem("Project: —")
        self.item_tip      = rumps.MenuItem("💡 Run /compact to free context")
        self.item_handoff_target = rumps.MenuItem("Handoff target: —")
        self.item_graphs = rumps.MenuItem("📊 Usage Graphs...", callback=self._on_show_graphs)
        self.item_sessions_header = rumps.MenuItem("Active sessions: —")
        self._session_items = [
            rumps.MenuItem(" ", callback=self._make_session_select_handler(i))
            for i in range(MAX_SESSION_ITEMS)
        ]
        self.item_handoff  = rumps.MenuItem("📋 Copy handoff prompt", callback=self._on_handoff)
        self.item_updated  = rumps.MenuItem("Updated: —")
        self.item_refresh  = rumps.MenuItem("Refresh now", callback=self._on_refresh)
        self.item_quit     = rumps.MenuItem("Quit", callback=rumps.quit_application)

        self.menu = [
            self.item_tokens,
            self.item_ctx,
            self.item_project,
            None,  # separator
            self.item_handoff_target,
            self.item_handoff,
            self.item_graphs,
            None,
            self.item_sessions_header,
            *self._session_items,
            None,
            self.item_tip,
            self.item_updated,
            self.item_refresh,
            None,
            self.item_quit,
        ]

        self._primary = None
        self._handoff_target = None
        self._handoff_target_key = None
        self._latest_sessions = []
        self._latest_state = None
        self._state_lock = threading.Lock()
        self._refresh_requested = threading.Event()
        self._handoff_flash_until = 0.0
        self._storage = get_storage()
        self._last_cleanup = time.time()
        threading.Thread(target=self._poll_loop, daemon=True).start()
        self._ui_timer = rumps.Timer(self._drain_updates, 1)
        self._ui_timer.start()

    # ── Polling ───────────────────────────────────────────────────────────────
    def _poll_loop(self):
        while True:
            try:
                sessions = get_sessions()
                now_str = datetime.now().strftime("%H:%M:%S")

                # Record historical snapshot (with sampling)
                try:
                    self._storage.record_snapshot(sessions)
                    # Periodic cleanup: once per day
                    if time.time() - self._last_cleanup > 86400:
                        deleted = self._storage.cleanup_old_data()
                        if deleted:
                            print(f"[token-tracker] cleanup: removed {deleted} old records")
                        self._last_cleanup = time.time()
                except Exception as e:
                    print(f"[token-tracker] storage error: {e}")

                with self._state_lock:
                    self._latest_state = {"sessions": sessions, "now_str": now_str, "error": None}
            except Exception as e:
                print(f"[token-tracker] poll error: {e}")
                with self._state_lock:
                    self._latest_state = {
                        "sessions": [],
                        "now_str": datetime.now().strftime("%H:%M:%S"),
                        "error": str(e),
                    }
            self._refresh_requested.wait(POLL_INTERVAL)
            self._refresh_requested.clear()

    def _drain_updates(self, _):
        state = None
        with self._state_lock:
            if self._latest_state is not None:
                state = self._latest_state
                self._latest_state = None
        if state:
            self._apply_state(state["sessions"], state["now_str"], state["error"])
        self._maybe_clear_handoff_flash()

    def _maybe_clear_handoff_flash(self):
        if self._handoff_flash_until and time.time() >= self._handoff_flash_until:
            self._handoff_flash_until = 0.0
            self.item_handoff.title = "📋 Copy handoff prompt"

    def _apply_state(self, sessions, now_str, error=None):
        if error:
            self.title = "❌"

        if not sessions:
            self.title             = "⚪ idle"
            self.item_tokens.title = "No Claude sessions found"
            self.item_ctx.title    = "Context: —"
            self.item_project.title= "Project: —"
            self.item_tip.title    = "💡 Run /compact to free context"
            self.item_handoff_target.title = "Handoff target: —"
            self.item_sessions_header.title = "Active sessions:"
            self.item_sessions_header.hidden = True
            for item in self._session_items:
                item.hidden = True
                item.enabled = False
                item.title = ""
            self.item_handoff.title= "📋 Copy handoff prompt"
            self.item_updated.title= f"Updated: {now_str}"
            self._primary          = None
            self._handoff_target    = None
            self._handoff_target_key = None
            self._latest_sessions = []
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

        # Select handoff target (explicit picker)
        self._latest_sessions = sessions
        target = None
        if self._handoff_target_key:
            for s in sessions:
                if (s["cwd"] or s["label"]) == self._handoff_target_key:
                    target = s
                    break
        if not target:
            target = sessions[0]
            self._handoff_target_key = target["cwd"] or target["label"]
        self._handoff_target = target
        self.item_handoff_target.title = f"Handoff target: {target['label']} ({_short_cwd(target['cwd'])})"

        has_sessions = len(sessions) > 0
        self.item_sessions_header.title = "Active sessions:"
        self.item_sessions_header.hidden = not has_sessions
        for i, item in enumerate(self._session_items):
            if i < len(sessions):
                s = sessions[i]
                is_selected = (s["cwd"] or s["label"]) == self._handoff_target_key
                prefix = "✓ " if is_selected else "  "
                item.title = f"{prefix}{s['label']} ({_short_cwd(s['cwd'])})"
                item.hidden = False
                item.enabled = True
            else:
                item.hidden = True
                item.enabled = False
                item.title = ""

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
        session = self._handoff_target or self._primary
        if not session:
            return
        prompt = build_handoff_prompt(session)
        success = copy_to_clipboard(prompt)
        self.item_handoff.title = "✅ Copied! Paste into Claude" if success else "❌ Copy failed — check terminal"
        self._handoff_flash_until = time.time() + 2.5

    def _on_show_graphs(self, _):
        """Placeholder for future graph window."""
        # TODO: Implement graph window with matplotlib or similar
        # For now, just show an info message
        rumps.alert(
            title="Usage Graphs",
            message="Graph feature is coming soon!\n\nHistorical data is being collected. The next phase will add visualization."
        )

    def _on_refresh(self, _):
        self.title = "⏳"
        self._refresh_requested.set()

    def _make_session_select_handler(self, index: int):
        def _handler(_):
            if index >= len(self._latest_sessions):
                return
            session = self._latest_sessions[index]
            self._handoff_target_key = session["cwd"] or session["label"]
        return _handler


def _short_cwd(cwd: str) -> str:
    if not cwd:
        return "unknown"
    home = str(Path.home())
    display = cwd.replace(home, "~", 1)
    parts = display.split(os.sep)
    if len(parts) <= 3:
        return display
    return os.sep.join(["…", parts[-2], parts[-1]])


# ── Entry ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    TokenTrackerApp().run()
