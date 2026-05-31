# Scraper Pro — Git Workflow

## Purpose

Git is the project memory, not just a backup. Commits and pushes should make the build history understandable to a human or agent reviewing it later.

## Required Workflow

1. Check current state before starting:
   - `git status --short --branch`
   - `git diff --stat`
2. Make the code/doc changes for one coherent unit of work.
3. Update any affected operating docs in the same change set:
   - `docs/ops/IMPLEMENTATION-TASK-LIST.md` when the checkpoint or next task changes
   - `docs/ops/SESSION-LOG.md` when work or decisions were completed
   - `docs/ops/HANDOFF-NEXT-SESSION.md` when the next resume point changes
   - `docs/agent/AGENT.md` or planning docs when project rules or architecture change
4. Review the final diff before commit.
5. Commit with a message that explains action, reason, and decision context.
6. Push the checkpoint to GitHub unless the user explicitly says not to.

## Commit Standard

Subject line:

`<area>: <action>`

Examples:

- `docs: separate planning files from app root`
- `phase1: wire gosom REST client`
- `ui: add live coverage stats fragment`

Commit body should include these sections:

```text
Why:
- business or execution reason for the change

Decisions:
- constraints, tradeoffs, or rules locked by this change

Docs:
- docs updated to match the new state

Tests:
- verification run, or "not run" with reason
```

## Push Standard

- Push coherent checkpoints, not random local drift.
- If a push changes behavior, architecture, or workflow, update the related docs in the same push.
- Prefer smaller clear pushes over large ambiguous batches.

## Branching

- Default branch: `main`
- Unless the user asks for a different flow, work directly on `main` and keep commits clean and descriptive.
