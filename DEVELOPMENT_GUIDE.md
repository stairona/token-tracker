# Development Guide

Master reference for the full Development workspace.

## Workspace Map

| Path | Purpose |
|---|---|
| /Users/nicolasaguirre/Development | Parent workspace and safety policy docs |
| /Users/nicolasaguirre/Development/light-projects | Main projects container |
| /Users/nicolasaguirre/Development/light-projects/music-organizer | Python CLI to organize music libraries by genre |
| /Users/nicolasaguirre/Development/light-projects/bird-simulation | Bird collision and mortality simulation toolkit |
| /Users/nicolasaguirre/Development/light-projects/token-tracker | macOS menu bar tracker for Claude token usage |
| /Users/nicolasaguirre/Development/random | Scratch folder (currently only system metadata file) |

## Environment

| Item | Value |
|---|---|
| Machine | MacBook Air de Nicolas (MacBook Air M4, 16GB) |
| Username | nicolasaguirre |
| Python executable | /opt/anaconda3/bin/python |
| Python version | 3.13.5 |
| Node executable | /opt/homebrew/bin/node |
| Node version | v25.8.0 |
| Conda | conda 25.5.1 |
| Ollama models path | /Volumes/SSD/ollama-models |
| Claude model alias | stepfun/step-3.5-flash:free |

## Key Paths

| Key | Path |
|---|---|
| Development root | /Users/nicolasaguirre/Development |
| Projects folder | /Users/nicolasaguirre/Development/light-projects |
| Token tracker script | /Users/nicolasaguirre/Development/light-projects/token-tracker/token_tracker.py |
| Token tracker README | /Users/nicolasaguirre/Development/light-projects/token-tracker/README.md |
| Claude config root | /Users/nicolasaguirre/.claude |
| Claude global safety policy | /Users/nicolasaguirre/.claude/CLAUDE.md |
| Claude project-scope safety policy | /Users/nicolasaguirre/.claude/projects/CLAUDE.md |
| Ollama models | /Volumes/SSD/ollama-models |

## Shell Setup (zsh)

Expected entries in /Users/nicolasaguirre/.zshrc:

function claude() {
    pkill -f token_tracker.py 2>/dev/null
    /opt/homebrew/bin/python3.11 /Users/nicolasaguirre/Development/light-projects/token-tracker/token_tracker.py &
    command claude "$@"
    pkill -f token_tracker.py 2>/dev/null
}

alias tokenbar='/opt/homebrew/bin/python3.11 /Users/nicolasaguirre/Development/light-projects/token-tracker/token_tracker.py'
alias claude='claude --model stepfun/step-3.5-flash:free'

Apply changes with:
source /Users/nicolasaguirre/.zshrc

## Safety Rules

Source of truth:
- /Users/nicolasaguirre/.claude/CLAUDE.md
- /Users/nicolasaguirre/.claude/projects/CLAUDE.md
- /Users/nicolasaguirre/Development/CLAUDE.md
- /Users/nicolasaguirre/Development/light-projects/CLAUDE.md

Core policy:
- No direct file or folder deletion by agents.
- No destructive commands.
- If cleanup is needed, provide Deletion Candidates instead of deleting.
- End each session with moved or renamed paths and rationale.

## Git Conventions

- Treat each project as its own git repository.
- Always verify current directory before git add or commit.
- Never mix files from multiple repos in one commit.
- Use clear commit messages with a scope prefix when possible.
- Avoid force push unless explicitly approved.
- Commit before major refactors or multi-file changes.

## Session Handoff Convention

At the end of each coding session, create or update SESSION_HANDOFF.md in the active project folder.

Recommended sections:
1. Session Date and Branch
2. What Was Changed
3. Commands Run
4. Validation Performed
5. Open Risks or TODOs
6. Next Recommended Step
7. Moved or Renamed Files
8. Deletion Candidates (if any)

Minimal template:

SESSION HANDOFF
Date:
Project:
Branch:

Changes Completed:
- 

Commands Executed:
- 

Validation:
- 

Open Items:
- 

Moved or Renamed Files:
- 

Deletion Candidates:
- None

## Maintenance Cadence

Weekly:
- Check git status and branch alignment in each project.
- Ensure token tracker path in zshrc still points to light-projects/token-tracker.
- Review README updates for active projects.

Monthly:
- Review safety policy files for consistency.
- Archive inactive projects into a dedicated archive folder only after explicit review.
