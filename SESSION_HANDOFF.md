# SESSION_HANDOFF.md — Token Tracker

**Last updated: 2026-03-16**

---

## 📅 Session: 2026-03-16 — Phases 3/5/6/7 (Config, Notifications, Graph UX, Packaging)

**Branch:** main
**Remote:** https://github.com/stairona/token-tracker.git

### Changes Completed

#### Phase 3.1 — Time Range Selector
- Graph window now includes a dropdown to select time range (7, 30, 90 days)
- Selection triggers immediate reload and redraw of both Timeline and Project Totals
- Default days respect config `graphs.default_days`

#### Phase 3.2 — CSV Export
- Added "Export CSV..." button below the time range control
- Exports current timeline data (respecting selected days) with full ISO timestamps
- Columns: `timestamp,project_slug,input_tokens,output_tokens,total_tokens,context_pct,cwd`
- Uses macOS save dialog; shows confirmation/error alerts

#### Phase 5 — Desktop Notifications
- Added `rumps.notification` calls when context crosses thresholds
- State tracking (`_notification_state`) prevents spam
- Notifications for:
  - Entry into warning zone (>= WARN_PCT)
  - Entry into critical zone (>= CRITICAL_PCT)
  - Recovery back to normal (optional)
- Configurable via `graphs.enable_notifications` (default True)

#### Phase 6.1 — pyproject.toml
- Created `pyproject.toml` following PEP 621
- Defines `token-tracker` console script entry point (`token_tracker:main`)
- Dependencies: `rumps>=0.2.0`
- Optional dependency `graphs` extra for `matplotlib`
- Ready for `pip install .` and PyPI publishing

#### Phase 7 — Configuration File
- Created `config.py` module to load `~/.config/token-tracker/config.toml`
- Supports sections: `[display]`, `[storage]`, `[graphs]`, `[ui]`
- All hard-coded constants moved to config with safe fallbacks
- Added **Preferences...** menu item to open or create config in default editor
- `storage.py` updated to use config values

#### Refactoring
- Wrapped `TokenTrackerApp().run()` in `main()` for entry point
- Split `_on_show_graphs` to delegate drawing to `_draw_graphs()` (reusability)
- Centralized config loading at module start

### Commands Executed

```bash
# Modified files
token_tracker.py
storage.py
config.py (new)
pyproject.toml (new)
README.md (extensive update)

# Git
git commit -m "feat: add config system, notifications, graph enhancements"
git push origin main
```

### Validation

- Syntax: `python -m py_compile` passes
- Logic: notification state transitioning appears sound
- UI: graph controls (combobox, export) integrated without layout issues
- Config: default config written on first Preferences click
- Backward compatibility: config file optional; app runs with defaults

### Moved or Renamed Files

- **None** — All changes were in-place additions or edits.

### Deletion Candidates

- **None** — No files deleted.

---

## 📅 Session: 2026-03-16 — Phases 1 & 2 Complete (Storage + Graphs + Multi-Session Fix)

**Branch:** main
**Remote:** https://github.com/stairona/token-tracker.git

### Changes Completed

#### Phase 1 — Historical Storage
- **storage.py**: SQLite backend (`~/.cache/token-tracker/usage.db`)
  - Schema: timestamp, project_slug, input/output/total tokens, context_pct, cwd
  - Sampling: only record if total tokens >= 5000
  - Throttling: max 1 snapshot/min per project; skip if <15 min since last
  - Retention: 90 days with daily cleanup

- **token_tracker.py**: integrated storage
  - `self._storage = get_storage()` in init
  - `record_snapshot(sessions)` in `_poll_loop`
  - Daily cleanup: `cleanup_old_data()`

#### Phase 2 — Graphs UI & Multi-Session Fix
- **Graph window** (Tkinter + matplotlib)
  - Menu item "📊 Usage Graphs..." opens a window with two tabs:
    * *Timeline*: line chart of total tokens (purple) over last 30 days, input shaded blue
    * *Project Totals*: horizontal bar chart (teal) of tokens per project
  - Bring-to-front behavior if already open
  - Graceful error alert if dependencies missing
- **Multi-session support** (Ghostty fix)
  - Now distinguishes separate Claude sessions by `sessionId` (UUID)
  - Deduplication key: `(cwd, session_id)` instead of just `cwd`
  - Handoff target selection uses `session_id` for precision
  - Session picker shows distinct entries even when cwd is same
- **README.md** updated:
  - Consolidated "Usage Graphs" section (no longer planned)
  - Documented graph requirements (`pip install matplotlib`, Tkinter)
  - Removed redundant "Historical Data" subsection

### Commands Executed

```bash
# Syntax checks
python -m py_compile token_tracker.py
python -m py_compile storage.py

# Storage unit test
python -c "from storage import SQLiteStorage; ..."  # Verified CRUD

# Git commits
git commit -m "feat: add historical usage storage (Phase 1)"
git commit -m "fix: distinguish concurrent sessions using sessionId"
git commit -m "feat: add usage graphs UI with Tkinter/matplotlib (Phase 2)"

# Push all
git push origin main
```

### Validation

- Storage: independent test passed (create, insert, query, cleanup)
- Syntax: both modules compile cleanly
- UI: graph window opens (requires matplotlib/tkinter); no crashes if missing
- Multi-session: two Claude windows in same project appear as separate menu entries
- Session picker selects correct instance via session_id
- Error handling: storage errors logged, don't break polling; graph import errors show alert
- Menu structure stable (static items pattern)

### Open Items / Next Steps

- **Phase 3 possibilities**:
  - Time range selector in graph window (7d, 30d, 90d)
  - CSV export from graphs
  - Context pressure heatmap (hourly/daily patterns)
  - Desktop notifications when usage exceeds thresholds
- **Distribution**:
  - Add `pyproject.toml` with dependencies (rumps, matplotlib)
  - Explore py2app or Homebrew formula for easier install
  - Test on clean macOS with Python from python.org/Homebrew

### Moved or Renamed Files

- **storage.py** (new, 285 lines)
- **token_tracker.py** (modified extensively)
- **README.md** (restructured graphs section)

### Deletion Candidates

- None

---

## 📅 Session: 2026-03-13 — Prior Work Summary

**Branch:** main
**Remote:** https://github.com/stairona/token-tracker.git

### Changes Completed

- Stabilized menu updates using `rumps.Timer` and static menu items
- Added color indicators (🟩🟨🟥) to context progress bar
- Added exception handling in file parsing and clipboard operations
- Implemented explicit session picker with clean UI (✓ selection indicator)
- Added optional `HANDOFF_ROOT` support for dual-root handoff automation

### Notes

- Working tree clean, up to date with origin/main.
- App uses POLL_INTERVAL=10s, ACTIVE_WINDOW=30min, CONTEXT_LIMIT=262k tokens.
- No destructive commands run.

---

*Handoff generated by Claude Code on 2026-03-16.*
