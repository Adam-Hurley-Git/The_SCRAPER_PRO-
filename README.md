# Scraper Pro

Scraper Pro is a FastAPI + SQLite local business lead-generation pipeline with a server-rendered HTMX UI.

## Repo Structure

- App/code: `main.py`, `config.py`, `database.py`, `coverage.py`, `gosom_client.py`, `pipeline/`, `templates/`, `static/`, `tests/`
- Runtime/output: `data/`
- Planning/docs: `docs/planning/`
- Agent operations: `docs/agent/`, `docs/ops/`
- Phase specs: `phases/`
- Research and archived material: `research/`, `archive/`

## Working Rules

- Keep planning and operational docs under `docs/`, not mixed with app files.
- Use `docs/GIT-WORKFLOW.md` for commit and push standards.
- Use `docs/ops/IMPLEMENTATION-TASK-LIST.md` as the execution plan.
- Use `docs/ops/HANDOFF-NEXT-SESSION.md` and `docs/ops/SESSION-LOG.md` to preserve checkpoint continuity.
