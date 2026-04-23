---
name: simplify-and-commit
description: Simplify the current scoped changes and then create a git commit. Use when the user asks to run simplify + commit in one flow, save cleanup changes immediately, or runs /simplify-and-commit.
---

# Simplify And Commit

## Goal
Run a two-step flow: simplify the selected code scope, then commit the resulting changes.

## Workflow
1. Execute the same workflow as `/simplify` on the requested scope:
   - determine scope from user input or local diff;
   - run parallel read-only review agents (quality, performance, reuse);
   - apply targeted cleanup fixes without broad refactors;
   - run lightweight checks for touched files when practical.
2. Present a short simplify summary (fixed vs skipped recommendations).
3. Execute the same workflow as `/commit`:
   - inspect `git status` and diffs;
   - stage only files relevant to the simplify scope;
   - write a concise imperative commit message;
   - create commit and report hash + post-commit status.

## Safety Rules
- Never commit unless the user explicitly requested this combined flow.
- Preserve unrelated dirty-tree changes; do not revert user work.
- Do not stage secrets (`.env`, credentials, tokens) unless explicitly requested.
- Do not push unless explicitly requested.
- If there are no changes after simplify, stop before commit and report it.

## Output
Return:
- simplify summary (what changed, what was skipped)
- commit hash
- commit message used
- short summary of staged files
- post-commit `git status`
