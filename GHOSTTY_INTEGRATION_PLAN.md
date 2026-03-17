# Ghostty Integration Plan — Token Tracker

## Goal

Display the Ghostty tab title (or a customizable label derived from terminal state) for each Claude session in the token tracker menu, making it trivial to identify which session corresponds to which Ghostty tab when multiple sessions are active.

## Background

Ghostty is a modern terminal emulator for macOS. It supports:
- Configurable tab titles via `tab-title-format`
- Standard environment variables: `TERM_PROGRAM=ghostty`
- Shell integration via escape sequences
- Possibly a control protocol/socket for querying state

Token Tracker currently derives labels from the working directory path:
- Uses last 2 path components (e.g., `dev/project`)
- This works but may not match what the user sees in the Ghostty tab title

## Problem Statement

When a user has multiple Ghostty tabs each running Claude Code in different projects, the token tracker menu shows session labels that might not align with the tab titles. For example:
- Ghostty tab title: `api-server` (custom or from prompt)
- Token tracker shows: `dev/project`

The user wants to cross-reference easily, ideally seeing the exact tab title in the token tracker menu.

## Challenges

1. **Tab title is not directly exposed** to external processes. The title lives inside Ghostty's process memory and is set via escape sequences or configuration.
2. **No documented API** for querying tab titles from another process (as of now).
3. **Session mapping**: Even if we could query Ghostty, we'd need to map a Claude process (PID) to the specific Ghostty tab/pane it's running in. Not straightforward.

## Proposed Solutions

### Option 1: Configurable Label Format (Pragmatic, Near-Term)

Allow users to configure a label format template that mimics their Ghostty `tab-title-format`. Since Ghostty titles often include `{{.CWD}}`, `{{.HOST}}`, etc., we provide similar placeholders.

**Implementation**:
- Add config options: `label_style` (`"basename"`, `"path2"`, `"full"`, `"custom"`) and `custom_label_template`.
- Placeholders: `{cwd}`, `{basename}`, `{dirname}`, `{relpath}` (relative to home as `~`), `{hostname}`, `{project}` (Claude project folder).
- Use Python's `str.format()` to render.
- User sets `custom_label_template` to match their Ghostty `tab-title-format` (with appropriate substitutions).

**Pros**:
- No need to reverse-engineer Ghostty internals
- Works for any terminal (iTerm2, Terminal.app, etc.)
- Simple to implement (already partially done with path2 style)
- Immediate user benefit

**Cons**:
- Not automatic; requires manual config alignment
- Ghostty's format syntax differs from Python's `str.format()`

**Example**:
- Ghostty config: `tab-title-format = "{{.CWD}}"`
- User sets token tracker: `custom_label_template = "{cwd}"` (full path with `~`)
- Ghostty config: `tab-title-format = "{{basename .CWD}}"`
- User sets: `custom_label_template = "{basename}"`

### Option 2: Terminal Title Escape Sequence Capture (Advanced)

Claude Code (or the user's shell) may set the terminal title using the standard OSC 0/2 escape sequence: `\033]0;Title\007`. The terminal emulator displays this title. However, this title is not stored anywhere accessible externally. Unless Ghostty writes it to a file or exposes it via a socket, we cannot read it.

**Feasibility**: Low unless Ghostty adds a query interface.

### Option 3: Process Ancestry + Ghostty Control Socket (Speculative)

Ghostty may have a control Unix domain socket (e.g., `~/.local/share/ghostty/ghostty.sock`) that accepts commands like `list-tabs` or `get-tab-title`. If such an interface exists, token tracker could:
1. For each Claude process, find its controlling terminal (tty) and trace through to the Ghostty process.
2. Use the control socket to query the tab/pane associated with that tty.
3. Retrieve the title.

**Research needed**:
- Examine Ghostty source code or documentation for control protocol.
- Check for environment variables like `GHOSTTY_PATH` that point to the socket.
- Check for `ghostty` CLI subcommands like `ghostty list-tabs`.

**Status**: Unknown, requires investigation.

### Option 4: User-Provided Label via Sidecar File (Simple, Manual)

User creates a file in their project directory, e.g., `.claude-session-label`, containing a custom label. Token tracker reads this file when scanning the session. This allows per-project customization without touching config.

**Implementation**:
- In `get_sessions()`, after reading cwd, check for that file and use its contents as the label.
- Strip whitespace, limit length.

**Pros**:
- No global config needed; label lives with project
- Works instantly

**Cons**:
- Manual per-project maintenance
- Not automatically tied to Ghostty tab title

### Option 5: Hybrid Approach

Combine multiple strategies:
1. Default to `label_style = "path2"` (current)
2. Allow `custom_label_template` for power users
3. Add optional sidecar file override (`.claude-session-label`)
4. If `TERM_PROGRAM=ghostty` is detected in the session's environment, automatically switch to a Ghostty-friendly template (like `{basename}`), but only if the user opts in via config `ghostty_automatic = true`.

**This is recommended**.

## Recommended Implementation Plan

### Phase 1: Configurable Label Formatting (Near-Term, High Value)

1. **Update `config.py`**:
   - Add `LABEL_STYLE` (default `"path2"`)
   - Add `CUSTOM_LABEL_TEMPLATE` (default `""`)
   - Add to default config generation in `_on_preferences`

2. **Create label formatter in `token_tracker.py`**:
   - Rename `_make_label` to `_format_label(cwd: str, folder_name: str, ctx_pct: float = None) -> str`
   - Switch on `config.LABEL_STYLE`:
     - `basename`: `Path(cwd).name`
     - `path2`: last two components (current logic)
     - `full`: `cwd` with home → `~`
     - `custom`: `config.CUSTOM_LABEL_TEMPLATE.format(...)` with safe fallback to `path2` if formatting fails.
   - Provide a dict with: `cwd` (absolute), `relhome` (relative to home or empty), `basename`, `dirname`, `project` (from `folder_name`), `pct` (maybe).

3. **Update `get_sessions()`**:
   - Call `_format_label(session["cwd"], Path(path).parent.name)` instead of inline label assignment.

4. **Update documentation** in README:
   - Document the new `[display] label_style` and `custom_label_template` options.
   - Provide examples for Ghostty users: "To match Ghostty's `tab-title-format = \"{{.CWD}}\"`, set `label_style = \"full\"`; for `{{basename .CWD}}`, set `label_style = \"basename`".

5. **Testing**:
   - Unit tests for label formatter with various configs.
   - Manual test: change `label_style` in config and observe menu updates.

### Phase 2: Sidecar File Overlay (Optional, Medium Value)

- Check for `.claude-session-label` in the cwd.
- If exists, use its first line as label (truncated to reasonable length).
- This overrides config `label_style`.
- Document in README.

### Phase 3: Ghostty Automatic Detection (Stretch)

- If config `ghostty_automatic = true` and the session's environment contains `TERM_PROGRAM=ghostty` (we'd need to capture env from the session file? Not currently stored), then apply Ghostty-specific defaults:
  - Suggest using `label_style = "basename"` (typical Ghostty default)
  - Or read Ghostty's config file (`~/.config/ghostty/config`) to extract `tab-title-format` and translate to our template automatically (requires parsing Ghostty's Go-template syntax).

**Research first**: Is there any way to get the actual tab title from Ghostty without guessing? Possibly via the `ghostty` CLI `ghostty -l` or via an RPC interface. Submit issue to Ghostty repo if necessary.

### Risks & Mitigations

- **Risk**: Custom template syntax errors produce unreadable labels.
  - Mitigation: Wrap in try/except, fallback to `path2`, log to console.
- **Risk**: Changing label format could confuse existing users.
  - Mitigation: Keep default `path2` (current behavior). New options opt-in.
- **Risk**: Ghostty integration may not be feasible without changes to Ghostty itself.
  - Mitigation: Focus on configurable format as a user-controlled workaround.

## Dependencies

- Python standard library: `string.Template` or just `str.format`.
- Config already in place; just add new keys.

## Timeline

- Phase 1: 1–2 hours implementation + testing
- Phase 2: +1 hour
- Phase 3: research (1 hour) + implementation if viable (2–3 hours)

## Success Criteria

- User can achieve label consistency between Ghostty tab title and token tracker menu by configuring `label_style` or `custom_label_template`.
- No breaking changes for existing users.
- Clear documentation with examples.

---

*Prepared by Claude Code for token-tracker Ghostty integration.*
