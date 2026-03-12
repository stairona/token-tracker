# Projects Organization Playbook

## Current Layout
- `light-projects/music-organizer` - Python CLI project
- `light-projects/bird-simulation` - simulation project
- `light-projects/token-tracker` - menu bar tracker project

## Canonical Structure (Per Project)
- `README.md` - purpose, setup, run commands
- `src/` - implementation
- `tests/` - automated tests
- `docs/` - design notes and decisions
- `.claude/` - local agent/session preferences

## Git Rules
- Each project must keep its own `.git` and remote.
- Parent `Development` repo ignores `light-projects/`.
- Never run cross-project commits from the wrong directory.

## Weekly Maintenance Checklist
- Verify each project branch and remote.
- Run tests in each active project.
- Review untracked files and classify as keep/move/archive candidate.
- Update project README with any new commands or workflows.

## Archive Strategy
- For inactive projects, move to `light-projects/_archive/<project-name>-YYYY-MM`.
- Keep archived projects read-only unless reactivated.
- Do not delete directly; list deletion candidates with reasons first.

## Session Discipline
- Start sessions at the intended project root.
- End sessions with: changed files, moved files, and deletion candidates.
