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
from config import get_config
import csv

# ── Config ────────────────────────────────────────────────────────────────────
_config = get_config()

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
HANDOFF_ROOT_ENV = os.getenv("HANDOFF_ROOT")
HANDOFF_ROOT = Path(HANDOFF_ROOT_ENV) if HANDOFF_ROOT_ENV else None
POLL_INTERVAL = _config.POLL_INTERVAL
CONTEXT_LIMIT = _config.CONTEXT_LIMIT
ACTIVE_WINDOW = 1800     # seconds — session shown if modified within 30 min (hard-coded for now)
WARN_PCT = _config.WARN_PCT
CRITICAL_PCT = _config.CRITICAL_PCT
ENABLE_NOTIFICATIONS = _config.ENABLE_NOTIFICATIONS
TAIL_READ_BYTES = _config.TAIL_READ_BYTES
MAX_SESSION_ITEMS = _config.MAX_SESSION_ITEMS
MAX_FILES_TO_SCAN = _config.MAX_FILES_TO_SCAN
POLL_BUDGET_SEC = _config.POLL_BUDGET_SEC
FILE_OP_TIMEOUT = _config.FILE_OP_TIMEOUT
LABEL_STYLE = _config.LABEL_STYLE
CUSTOM_LABEL_TEMPLATE = _config.CUSTOM_LABEL_TEMPLATE

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


def _make_label(cwd: str, folder_name: str, pct: float = 0.0) -> str:
    """
    Create a clear, distinguishable label for a session.
    Formatting is controlled by config label_style.
    """
    style = _config.LABEL_STYLE
    template = _config.CUSTOM_LABEL_TEMPLATE if style == "custom" else None

    # Gather format variables
    home = str(Path.home())
    abs_cwd = cwd or ""
    p = Path(abs_cwd) if abs_cwd else None
    basename = p.name if p and p.name else ""
    dirname = str(p.parent) if p and p.parent else ""
    relhome = ""
    relhome_parts = ()
    if p:
        try:
            rel = p.relative_to(home)
            relhome = str(rel)
            relhome_parts = rel.parts
        except ValueError:
            # Not under home, use absolute path parts
            relhome_parts = p.parts
            relhome = abs_cwd
    project = _clean_name(folder_name) if folder_name else ""
    # Also provide full relhome with ~ prefix
    relhome_tilde = "~" + (relhome if relhome and not relhome.startswith("~") else relhome.lstrip("~")) if (relhome or cwd) else ""

    format_vars = {
        "cwd": abs_cwd,
        "basename": basename,
        "dirname": dirname,
        "relhome": relhome,
        "relhome_tilde": relhome_tilde,
        "project": project,
        "pct": pct,
    }

    def apply_style(style: str) -> str:
        if style == "basename":
            return basename or project or "unknown"
        elif style == "path2":
            # Use relative path parts if available; fall back to absolute
            if not relhome_parts:
                return project or "unknown"
            if len(relhome_parts) >= 2:
                return str(Path(*relhome_parts[-2:]))
            else:
                # Single component: just show that
                return relhome_parts[0] if relhome_parts else (project or "unknown")
        elif style == "full":
            return relhome_tilde or abs_cwd or (project or "unknown")
        elif style == "custom" and template:
            try:
                return template.format(**format_vars).strip()
            except Exception:
                # Fallback to path2 on template error
                return apply_style("path2")
        else:
            # Unknown style, fallback to path2
            return apply_style("path2")

    return apply_style(style)


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
    """Read (input_tokens, output_tokens, cwd, session_id) from most recent non-zero usage entry."""
    inp = out = 0
    cwd = ""
    session_id = ""
    sig = (0, 0)
    try:
        stat = os.stat(path)
        sig = (stat.st_mtime, stat.st_size)

        # Skip extremely large files to avoid memory/time issues (unlikely but safe)
        if stat.st_size > 100_000_000:  # 100 MB
            print(f"[token-tracker] skip large file: {path} ({stat.st_size} bytes)")
            return 0, 0, "", ""

        cached = _TOKEN_CACHE.get(path)
        if cached and cached[0] == sig:
            return cached[1], cached[2], cached[3], cached[4]

        def parse_lines(lines):
            nonlocal inp, out, cwd, session_id
            for line in reversed(lines):
                try:
                    e = json.loads(line.strip())
                    if not cwd:
                        cwd = e.get("cwd", "")
                    if not session_id:
                        session_id = e.get("sessionId", "")
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
        _TOKEN_CACHE[path] = (sig, inp, out, cwd, session_id)
    return inp, out, cwd, session_id


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
            inp, out, cwd, session_id = _read_tokens(path)
        except Exception as e:
            # Don't let one bad file break the whole poll
            print(f"[token-tracker] skip {path}: {e}")
            continue
        pct = (inp / CONTEXT_LIMIT * 100) if inp else 0.0
        label = _make_label(cwd, Path(path).parent.name, pct)
        # Use (cwd, session_id) as dedup key to allow multiple sessions in same project
        session_key = (cwd, session_id)
        if session_key in seen:
            continue
        seen.add(session_key)
        sessions.append({
            "label": label,
            "input_tokens": inp,
            "output_tokens": out,
            "cwd": cwd,
            "session_id": session_id,
            "pct": pct,
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
        self.item_prefs    = rumps.MenuItem("Preferences...", callback=self._on_preferences)
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
            self.item_prefs,
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
        # Graph window state
        self._graph_window = None
        self._graph_root = None
        self._graph_update_timer = None
        # Notification state tracking
        self._notification_state = None  # None, 'warn', 'critical'
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

    def _maybe_send_notification(self, pct, label):
        """Send desktop notification if threshold crossing is new."""
        if not ENABLE_NOTIFICATIONS:
            return

        # Determine current level
        if pct >= CRITICAL_PCT:
            level = 'critical'
        elif pct >= WARN_PCT:
            level = 'warn'
        else:
            level = None

        # Only notify if we're entering a new threshold zone
        if level != self._notification_state:
            self._notification_state = level
            if level == 'critical':
                rumps.notification(
                    title="Token Tracker — CRITICAL",
                    subtitle=f"{label}",
                    message=f"Context at {pct:.0f}% — run /compact now!",
                    sound=True
                )
            elif level == 'warn':
                rumps.notification(
                    title="Token Tracker — High Usage",
                    subtitle=f"{label}",
                    message=f"Context at {pct:.0f}% — consider /compact",
                    sound=False
                )
            elif level is None and self._notification_state in ('warn', 'critical'):
                # Recovery notification (optional - could be disabled)
                rumps.notification(
                    title="Token Tracker — Normal",
                    subtitle=f"{label}",
                    message=f"Context back to {pct:.0f}%",
                    sound=False
                )

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

        # Check for notification-worthy threshold crossings
        self._maybe_send_notification(pct, label)

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
                if s.get("session_id") == self._handoff_target_key:
                    target = s
                    break
        if not target:
            target = sessions[0]
            self._handoff_target_key = target.get("session_id") or target["cwd"] or target["label"]
        self._handoff_target = target
        self.item_handoff_target.title = f"Handoff target: {target['label']} ({_short_cwd(target['cwd'])})"

        has_sessions = len(sessions) > 0
        self.item_sessions_header.title = "Active sessions:"
        self.item_sessions_header.hidden = not has_sessions
        for i, item in enumerate(self._session_items):
            if i < len(sessions):
                s = sessions[i]
                is_selected = s.get("session_id") == self._handoff_target_key
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
        """Open a window with usage graphs (timeline and project totals)."""
        try:
            import tkinter as tk
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            import matplotlib
            matplotlib.use('TkAgg')
            import matplotlib.pyplot as plt
            from datetime import datetime, timedelta
            from tkinter import ttk
            from tkinter import filedialog
            import csv
        except ImportError as e:
            rumps.alert(
                title="Missing Dependencies",
                message=("Graphs require matplotlib and Tkinter.\n\n"
                         "Install with:\n"
                         "  pip install matplotlib\n\n"
                         "Tkinter is usually included with Python on macOS.\n\n"
                         f"Error: {e}")
            )
            return

        # If window already exists, bring to front
        if self._graph_window is not None:
            try:
                self._graph_window.deiconify()
                self._graph_window.lift()
                self._graph_window.focus_force()
            except Exception:
                self._graph_window = None
            return

        # Create Tkinter root (hidden) and main window
        root = tk.Tk()
        root.withdraw()
        self._graph_root = root

        window = tk.Toplevel(root)
        window.title("Token Usage Graphs")
        window.geometry("920x720")
        window.protocol("WM_DELETE_WINDOW", self._on_graph_window_close)

        # --- Control Frame (time range + export) ---
        control_frame = ttk.Frame(window)
        control_frame.pack(fill='x', padx=10, pady=5)

        ttk.Label(control_frame, text="Time range:").pack(side='left', padx=(0, 5))

        default_days = _config.GRAPHS_DEFAULT_DAYS
        days_var = tk.IntVar(value=default_days if default_days in (7, 30, 90) else 30)
        days_combo = ttk.Combobox(control_frame, textvariable=days_var, values=[7, 30, 90], width=10, state='readonly')
        days_combo.pack(side='left', padx=5)

        ttk.Label(control_frame, text="days").pack(side='left', padx=(0, 10))

        def export_csv():
            try:
                days_export = days_var.get()
                history = self._storage.get_usage_history(days=days_export)
                if not history:
                    rumps.alert("No Data", f"No usage data to export for the last {days_export} days.")
                    return
                file_path = filedialog.asksaveasfilename(
                    parent=window,
                    defaultextension=".csv",
                    filetypes=[("CSV files", "*.csv"), ("All files", "*")],
                    initialfile=f"token-usage-{datetime.now().strftime('%Y-%m-%d')}.csv"
                )
                if not file_path:
                    return
                with open(file_path, 'w', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=['timestamp', 'project_slug', 'input_tokens', 'output_tokens', 'total_tokens', 'context_pct', 'cwd'])
                    writer.writeheader()
                    for row in history:
                        row_copy = dict(row)
                        row_copy['timestamp'] = datetime.fromtimestamp(row_copy['timestamp']).isoformat()
                        writer.writerow(row_copy)
                rumps.alert("Export Complete", f"Exported {len(history)} records to:\n{file_path}")
            except Exception as e:
                rumps.alert("Export Failed", f"Error exporting CSV:\n{e}")

        export_btn = ttk.Button(control_frame, text="Export CSV...", command=export_csv)
        export_btn.pack(side='left', padx=20)

        def reload_graphs():
            try:
                days = days_var.get()
                self._draw_graphs(window, days, fig_tl, ax_tl, canvas_tl, fig_pt, ax_pt, canvas_pt)
            except Exception as e:
                print(f"[token-tracker] graph reload error: {e}")

        days_combo.bind('<<ComboboxSelected>>', lambda e: reload_graphs())

        # --- Notebook (tabs) ---
        notebook = ttk.Notebook(window)
        notebook.pack(fill='both', expand=True, padx=10, pady=10)

        # --- Timeline Tab ---
        frame_tl = ttk.Frame(notebook)
        notebook.add(frame_tl, text="Timeline")
        fig_tl = plt.Figure(figsize=(8, 5), dpi=100)
        ax_tl = fig_tl.add_subplot(111)
        canvas_tl = FigureCanvasTkAgg(fig_tl, master=frame_tl)
        canvas_tl.get_tk_widget().pack(fill='both', expand=True)

        # --- Project Totals Tab ---
        frame_pt = ttk.Frame(notebook)
        notebook.add(frame_pt, text="Project Totals")
        fig_pt = plt.Figure(figsize=(8, 5), dpi=100)
        ax_pt = fig_pt.add_subplot(111)
        canvas_pt = FigureCanvasTkAgg(fig_pt, master=frame_pt)
        canvas_pt.get_tk_widget().pack(fill='both', expand=True)

        # Initial draw (use config default)
        default_days = _config.GRAPHS_DEFAULT_DAYS
        self._draw_graphs(window, default_days, fig_tl, ax_tl, canvas_tl, fig_pt, ax_pt, canvas_pt)

        # Keep references
        self._graph_canvases = (canvas_tl, canvas_pt)
        self._graph_window = window

        # Start a rumps.Timer to call root.update() and keep Tkinter responsive
        self._graph_update_timer = rumps.Timer(lambda _: root.update(), 0.05)
        self._graph_update_timer.start()

        # Bring window to front
        window.lift()
        window.focus_force()

    def _draw_graphs(self, parent_window, days, fig_tl, ax_tl, canvas_tl, fig_pt, ax_pt, canvas_pt):
        """Draw the graphs with data for the specified number of days."""
        # Load historical data
        try:
            timeline_data = self._storage.get_usage_history(days=days)
            project_data = self._storage.get_project_totals(days=days)
        except Exception as e:
            rumps.alert("Data Error", f"Failed to load historical data:\n{e}")
            if parent_window and parent_window.winfo_exists():
                parent_window.destroy()
            return

        # Clear previous plots
        ax_tl.clear()
        ax_pt.clear()

        # Plot Timeline
        if timeline_data:
            times = [datetime.fromtimestamp(d['timestamp']) for d in timeline_data]
            total_vals = [d['total_tokens'] for d in timeline_data]
            input_vals = [d['input_tokens'] for d in timeline_data]

            ax_tl.plot(times, total_vals, label='Total', color='purple', linewidth=2)
            ax_tl.fill_between(times, 0, input_vals, alpha=0.4, label='Input', color='blue')
            ax_tl.set_title(f'Token Usage Over Last {days} Days')
            ax_tl.set_ylabel('Tokens')
            ax_tl.legend(loc='upper left')
            fig_tl.autofmt_xdate()
        else:
            ax_tl.text(0.5, 0.5, f'No usage data yet for the last {days} days.\nStart using Claude Code!',
                       ha='center', va='center', fontsize=12)
            ax_tl.set_axis_off()

        # Plot Project Totals (horizontal bar)
        if project_data:
            names = [d['project_slug'] for d in project_data]
            totals = [d['total_tokens'] for d in project_data]
            ax_pt.barh(names, totals, color='teal')
            ax_pt.set_title(f'Total Tokens by Project (Last {days} Days)')
            ax_pt.set_xlabel('Tokens')
            ax_pt.invert_yaxis()  # highest at top
        else:
            ax_pt.text(0.5, 0.5, 'No project data yet.', ha='center', va='center', fontsize=12)
            ax_pt.set_axis_off()

        # Render
        canvas_tl.draw()
        canvas_pt.draw()

    def _on_graph_window_close(self):
        """Clean up graph window resources."""
        if self._graph_update_timer:
            self._graph_update_timer.stop()
            self._graph_update_timer = None
        if self._graph_root:
            self._graph_root.destroy()
        self._graph_window = None
        self._graph_root = None
        self._graph_canvases = None

    def _on_refresh(self, _):
        self.title = "⏳"
        self._refresh_requested.set()

    def _on_preferences(self, _):
        """Open the config file in the default editor (using 'open' on macOS)."""
        config_path = _config.config_path
        if not config_path.exists():
            # Create directory if missing
            config_path.parent.mkdir(parents=True, exist_ok=True)
            # Write default config
            try:
                with open(config_path, "w") as f:
                    f.write("# Token Tracker Configuration\n")
                    f.write("# Edit this file to customize the app without changing code.\n")
                    f.write("# Changes require app restart to take effect.\n\n")
                    f.write("[display]\n")
                    f.write("poll_interval = 10\n")
                    f.write("context_limit = 262144\n")
                    f.write("warn_pct = 60\n")
                    f.write("critical_pct = 85\n")
                    f.write("# Label style for sessions: basename, path2, full, or custom\n")
                    f.write("label_style = path2\n")
                    f.write("# Template for custom labels (e.g., \"{basename} [{pct:.0f}%]\"; see README)\n")
                    f.write("custom_label_template = \"\"\n\n")
                    f.write("[storage]\n")
                    f.write("min_tokens_for_snapshot = 5000\n")
                    f.write("retention_days = 90\n\n")
                    f.write("[graphs]\n")
                    f.write("default_days = 30\n")
                    f.write("enable_notifications = true\n\n")
                    f.write("[ui]\n")
                    f.write("max_session_items = 5\n")
                    f.write("max_files_to_scan = 50\n")
                    f.write("poll_budget_sec = 8\n")
                    f.write("file_op_timeout = 5\n")
                    f.write("tail_read_bytes = 524288\n")
            except Exception as e:
                rumps.alert("Config Error", f"Failed to create config file:\n{e}")
                return
        try:
            subprocess.run(["open", str(config_path)], check=True)
        except Exception as e:
            rumps.alert("Failed", f"Could not open config file:\n{e}")

    def _make_session_select_handler(self, index: int):
        def _handler(_):
            if index >= len(self._latest_sessions):
                return
            session = self._latest_sessions[index]
            # Use session_id to uniquely identify sessions, even if cwd is same
            self._handoff_target_key = session.get("session_id") or session["cwd"] or session["label"]
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
def main():
    TokenTrackerApp().run()

if __name__ == "__main__":
    main()
