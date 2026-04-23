---
name: commit
description: Commit current working tree changes in git. Use when the user asks to commit now, save current code state, create a commit, or runs /commit.
---

# Commit

## Goal
Create a git commit with the current code state requested by the user.

## Workflow
1. Inspect repository status and staged/unstaged changes.
2. Draft a concise commit message that reflects why the current state is being saved.
3. Stage relevant files for the requested scope.
4. Commit using the message.
5. Show the resulting commit hash and final `git status`.

## Safety Rules
- Never commit unless the user explicitly asks.
- Do not include secrets (`.env`, credentials, tokens) unless explicitly requested.
- Do not run destructive git commands.
- Do not push unless explicitly requested.
- If there are no changes, report it and do not create an empty commit.

## Commit Message Style
- Keep it short and specific.
- Prefer intent over raw file list.
- Use imperative mood.

## Output
Return:
- commit hash
- commit message used
- short summary of staged files
- post-commit status
