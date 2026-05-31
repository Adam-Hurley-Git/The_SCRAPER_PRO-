# Scraper Pro — Next Session Handoff
*Prepared 2026-06-01*

---

## Current Checkpoint

Implementation has started.

The latest session completed the first two **Track B** tasks after the foundation block:

- project CRUD API implemented
- UI shell and HTMX navigation implemented
- API/UI tests added for the new project lifecycle layer

No live gosom validation run has been completed yet, and no Phase 1 discovery logic has been wired beyond the skeleton.

**Last confirmed finish point:** `A1`, `A2`, `A3`, `A4`, `B1`, and `B2` complete.

**Exact next action:** begin `docs/ops/IMPLEMENTATION-TASK-LIST.md` at **Track C — Task C1: gosom REST client**.

Do not reopen planning unless the user explicitly changes scope. Resume from code.

---

## State of the Project

Application foundation code now exists.

The design is mature and internally consistent across:

- `docs/planning/PROJECT-GOAL.md`
- `docs/planning/PIPELINE-MASTER.md`
- `docs/planning/UI-SPEC.md`
- `phases/phase1-discovery.md`
- `phases/phase2-enrichment-design.md`
- `phases/phase3-normalise-dedup.md`

The initial scaffold now also exists across:

- `main.py`
- `config.py`
- `database.py`
- `coverage.py`
- `gosom_client.py`
- `pipeline/`
- `templates/`
- `static/`
- `tests/`

The next session should be treated as the **second implementation session**, not another planning pass.

The completed foundation block is:

1. `A1` — Create project skeleton
2. `A2` — Dependencies and environment contract
3. `A3` — SQLite schema bootstrap
4. `A4` — Basic test harness

The next active block is:

1. `C1` — gosom REST client
2. `C2` — Coverage cell model and queue logic
3. `C3` — Lead ingestion and dedup
4. `C4` — Coverage endpoints

---

## What Has Been Locked

- v1 scope is only Phase 1, Phase 2, Phase 3
- Phase 4 and Phase 5 remain deferred
- gosom is the discovery engine
- FastAPI + SQLite is the orchestration layer
- HTMX + Alpine + Jinja2 + Leaflet is the UI contract
- deterministic website extraction runs before Groq fallback
- dedup key is Google CID
- output contract is `leads.xlsx`

---

## Important Build Risks Already Accounted For

### SMTP verification

Do not implement SMTP as a binary truth oracle.

Required behavior:

- 1 probe/second global cap
- 5 second backoff on refusal/disconnect
- no same-run retries for one address
- tri-state result: true / false / unverifiable
- confidence is reduced on SMTP block, not dropped to invalid

### Companies House matching

Do not implement naive fuzzy matching.

Required behavior:

- normalized exact match first
- postcode/domain-supported narrowing
- conservative fuzzy fallback only after stronger methods fail
- explicit `match_method` and `match_confidence`
- ambiguous cases remain unmatched

---

## Primary Execution Document

Use `docs/ops/IMPLEMENTATION-TASK-LIST.md` as the working task plan.

That file is now the practical build order and acceptance checklist for agents.

## Git And Documentation Rule

When work is completed:

- update the relevant docs in `docs/`
- commit with clear action, reason, and decision context
- push the checkpoint to GitHub unless the user says otherwise

---

## Required First Actions Next Session

1. Complete `C1` — gosom REST client wiring.
2. Complete `C2` — coverage cell model and queue logic.
3. Complete `C3` — lead ingestion and dedup.
4. Complete `C4` — coverage endpoints.
5. Complete `C5` — Phase 1 UI binding to live coverage data.
6. Stand up gosom locally and prove a single REST cell run works.
7. Complete `C6` before beginning Phase 2 implementation.
8. Build deterministic Phase 2 extraction before Groq fallback.
9. Build Companies House matching and SMTP verification conservatively.
10. Complete Phase 3 export.
11. Run tests and one live end-to-end sample project.
12. Update docs/logs based on real implementation results.

---

## Definition of "Ready To Continue"

The next session should proceed directly into implementation if the user says `continue`.

There should be no need to:

- revisit architecture
- re-decide the stack
- re-scope v1
- redesign phases
- argue about API shape
- argue about UI framework

The remaining work is execution and verification from `Track C` onward.

---

## Final Instruction For The Next Agent

Build to the existing contract and continue from the scaffold already in the workspace.

Do not read `archive/` unless explicitly asked.
Do not implement deferred phases.
Do not widen the schema for speculative future features.
Do not over-trust SMTP failures.
Do not over-trust loose Companies House matches.

If tradeoffs are required, bias toward:

- resumability
- observability
- conservative data correctness
- not attaching wrong company/person data
- not discarding potentially valid emails because a mail server is hostile
