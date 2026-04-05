# token-tracker — Plan
# Created: 2026-04-04

## Current Task
Pending user testing and commit. Code changes complete: handoff path resolution fixed, handoff_root config option added, custom session names implemented, token counts in dropdown, active_window and include_subagents config options added. Documentation updated. User config upgraded with handoff_root pointing to central handoff folder.

## Completed (last session)
- Fixed handoff path to use new flat structure: /Users/nicolasaguirre/zprojects/claude/session-handoffs/{slug}.md
- Added [handoff] section with handoff_root config option (default ""), falls back to HANDOFF_ROOT env var then project-local SESSION_HANDOFF.md
- Added active_window and include_subagents config options (active_window default 1800, include_subagents default False)
- Implemented persistent custom session names via JSON storage at ~/.config/token-tracker/session_names.json
- Added "Rename Selected Session..." menu item with Tkinter dialog
- Session dropdown now shows token counts: "Label — 123/456 tokens (cwd)"
- Updated Preferences dialog to write new defaults when creating config
- README.md fully updated with new features and config options
- Central handoff files placed in correct location
- Syntax validated with py_compile; config loading tested

## Next Task
Test all new features on macOS before committing:
1. Restart token-tracker and verify token counts display in dropdown
2. Test rename session functionality and persistence
3. Test active_window setting (adjust to show more/fewer sessions)
4. Test include_subagents setting
5. Verify handoff prompt still works with new path
6. Check custom names persistence across restarts
7. Verify no errors in log
After successful testing, commit changes with comprehensive commit message and push to origin main.

## Open Risks
- Must test on actual macOS environment (graph dependencies)
- Need to ensure no regressions in existing functionality
- Config file format upgrade may affect existing users (handled by config.py defaults)

## Deletion Candidates
| Path | Reason | Risk | Command |
|------|--------|------|---------|
| ~/.claude/session-handoffs/ (old folder) | Safe to delete after confirming config points to zprojects | Low | rm -rf ~/.claude/session-handoffs/ |
