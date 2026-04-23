---
name: commit-and-push
description: Commit current git changes and push to remote branch. Use when the user asks to commit and push, publish current work, sync branch to origin, or runs /commit-and-push.
---

# Commit And Push

## Goal
Create a git commit from the current working tree and push it to the tracked remote branch.

## Workflow
1. Check `git status` and verify there are changes to commit.
2. Review staged and unstaged changes to confirm commit scope.
3. Draft a concise commit message aligned with the current changes.
4. Stage relevant files.
5. Create the commit.
6. Verify current branch and upstream tracking.
7. Push to remote (`git push` or `git push -u origin <branch>` when upstream is missing).
8. Report commit hash, pushed branch, and final status.

## Safety Rules
- Never commit or push unless the user explicitly asks.
- Never push secrets (`.env`, credentials, tokens) unless explicitly requested.
- Never use force push unless explicitly requested.
- Do not push directly to protected branches unless explicitly requested.
- If there are no changes, report it and stop.

## Commit Message Style
- Keep message short, specific, and in imperative mood.
- Focus on intent, not file dumps.

## Output
Return:
- commit hash
- commit message
- pushed branch and remote
- push result summary
- post-push `git status`
