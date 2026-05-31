# Scraper Pro — Workspace Entry Point

## Workspace Layout

Application and runtime files stay at the repository root:

- `main.py`, `config.py`, `database.py`, `coverage.py`, `gosom_client.py`
- `pipeline/`, `templates/`, `static/`, `tests/`, `data/`

Planning, agent, and operating documents are separated under `docs/`:

- `docs/agent/AGENT.md` — canonical agent context
- `docs/planning/PROJECT-GOAL.md`
- `docs/planning/PIPELINE-MASTER.md`
- `docs/planning/UI-SPEC.md`
- `docs/ops/IMPLEMENTATION-TASK-LIST.md`
- `docs/ops/HANDOFF-NEXT-SESSION.md`
- `docs/ops/SESSION-LOG.md`
- `docs/GIT-WORKFLOW.md`

Do not move planning or logging files back into the app/code root.

## Operating Rules

1. Build against the existing v1 contract. Do not reopen settled architecture without explicit user direction.
2. Keep app/code changes separate from planning/ops docs by storing those documents under `docs/`.
3. Update the relevant docs when work changes implementation state, decisions, or the next checkpoint.
4. Use git as the running project ledger:
   - commit related changes together
   - push meaningful checkpoints to GitHub
   - make commit history readable without opening the diff first
5. Every non-trivial commit should state:
   - what changed
   - why it changed
   - what decision or constraint it reflects
6. Use the local commit template in `.gitmessage.txt` when creating commits.

## Start Here

Read `docs/agent/AGENT.md` first, then use `docs/ops/IMPLEMENTATION-TASK-LIST.md` and `docs/ops/HANDOFF-NEXT-SESSION.md` to resume execution.
