# Development Workspace Rules

This file applies to this folder and everything below it.

## Repository Boundaries
- `Development` is its own repository (token-tracker root).
- Projects inside `light-projects/` are independent repositories.
- Never stage nested project folders in the parent repository.

## File Safety (Hard Rule)
- No file or folder deletions.
- No destructive commands (`rm`, `git clean`, `git reset --hard`, etc.).
- Allowed: edit, move, rename, copy, and create files.

## End-of-Session Report (Required)
- "Moved/Renamed Files": old path, new path, reason.
- "Deletion Candidates": path, reason, risk level, and suggested command for manual deletion (user-run only).

## Git Safety
- In each command, verify the current repository before staging/committing.
- Never mix changes across repositories.
