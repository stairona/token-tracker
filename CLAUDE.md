# Token Tracker — Development Rules

This file applies to this folder and everything below it.

## File Safety (Hard Rule)
- No file or folder deletions.
- No destructive commands (`rm`, `git clean`, `git reset --hard`, etc.).
- Allowed: edit, move, rename, copy, and create files.

## End-of-Session Report (Required)
- "Moved/Renamed Files": old path, new path, reason.
- "Deletion Candidates": path, reason, risk level, and suggested command for manual deletion (user-run only).

## Git Safety
- Always verify current repository before staging/committing.
- Never mix changes across repositories.
- Keep commits small and well-described.
