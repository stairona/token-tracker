# AI Tools Rules

This file defines permissions and guardrails for AI coding tools in the Development workspace.

## Claude Code — RESTRICTED

### Hard Rules
- Never run destructive commands such as rm, rm -rf, rmdir, find -delete, git clean, or git reset --hard.
- Never delete files or folders directly.
- Never overwrite files without presenting a diff first.
- Never modify files outside the active project scope without explicit approval.
- Never perform broad refactors without first explaining plan and impact.

### Required Workflow
1. List files first with ls.
2. Read relevant files before editing.
3. Explain intended change before applying it.
4. Ask for explicit confirmation for destructive or high-impact operations.

## VS Code Agent Mode — FULL PERMISSION

- Full permission to read, edit, create, rename, move, and copy files.
- Destructive actions still require explicit user approval.
- Must report all moved or renamed files at end of session.

## Cursor — FULL PERMISSION

- Full permission to read, edit, create, rename, move, and copy files.
- Destructive actions still require explicit user approval.
- Must report all moved or renamed files at end of session.

## General Rules For All Tools

- Respect repository boundaries; treat each project as an independent git repo.
- Confirm current working directory before any git add or commit.
- Keep commits small, scoped, and clearly named.
- Do not force push unless explicitly approved.
- End each work session with:
  - Moved or Renamed Files summary
  - Deletion Candidates summary with reason and risk

## Emergency File Recovery Steps

1. Stop all write operations immediately.
2. Check git status in the affected repository.
3. Recover tracked files with git restore or checkout from known commit.
4. Check local history and editor history.
5. Check Trash and available backups.
6. If needed, re-clone repository and re-apply uncommitted changes from history.
7. Document incident in session handoff with impacted paths and recovery actions.
