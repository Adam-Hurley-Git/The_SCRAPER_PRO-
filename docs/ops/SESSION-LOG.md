# Session Log
*Newest first. Each entry is a 30-second scan.*

---

## 2026-06-01 — Workspace framework cleanup: docs separated from app root and git workflow formalized

Reorganized the repository so planning and agent-operating documents stop living beside application files.

- moved planning docs into `docs/planning/`
- moved agent and operating docs into `docs/agent/` and `docs/ops/`
- added root `AGENTS.md` as the workspace entry point for future agents
- added `README.md`, `docs/GIT-WORKFLOW.md`, `.gitmessage.txt`, and `.gitignore`
- updated the operating docs so future work explicitly:
  - updates docs when checkpoints or decisions change
  - commits with action, reason, and decision context
  - pushes meaningful checkpoints to GitHub

**Decision locked:** planning/agent files are now structurally separated from app/code files, and git history is part of the project operating framework rather than an optional afterthought.

---

## 2026-06-01 — Second implementation session: Track B scaffold completed

Continued from the locked foundation checkpoint and completed the first core product layer needed before Phase 1 wiring.

- Implemented **Track B1 — Project CRUD API**:
  - added project database helpers for create, list, fetch, and archive
  - exposed:
    - `GET /api/projects`
    - `POST /api/projects`
    - `GET /api/projects/{id}`
    - `DELETE /api/projects/{id}`
  - confirmed archived projects are hidden from default listing
- Implemented **Track B2 — UI shell and navigation**:
  - replaced the placeholder root page with a persistent shell
  - added HTMX navigation targets for:
    - `/ui/map`
    - `/ui/pipeline`
    - `/ui/leads`
    - `/ui/scrapes`
  - made active project context visible in the header
  - added initial Track B placeholder views aligned to the build order
- Added API/UI tests covering:
  - project create/list/get/delete flow
  - archive behavior
  - active project context rendering for UI routes
- Verification target for this session:
  - `python -B -m pytest -p no:cacheprovider tests`

**Finish point for this session:** `B1` and `B2` complete. The next implementation action is **`Track C — Task C1: gosom REST client`**, followed by **`C2: coverage cell model and queue logic`**, then **`C3: lead ingestion and dedup`**.

---

## 2026-06-01 — First implementation session: foundation scaffold completed

Started the actual build and completed the full Track A foundation block so future sessions can resume from code instead of planning docs.

- Created the initial application scaffold:
  - `main.py`
  - `config.py`
  - `database.py`
  - `coverage.py`
  - `gosom_client.py`
  - `pipeline/phase1_discovery.py`
  - `pipeline/phase2_enrichment.py`
  - `pipeline/phase3_output.py`
  - `templates/shell.html`
  - `static/app.css`
  - `static/map.js`
- Added the first environment/dependency contract:
  - `requirements.txt`
  - `.env.example`
  - lazy Phase 2 env validation for `GROQ_API_KEY` and `COMPANIES_HOUSE_API_KEY`
- Implemented SQLite bootstrap from the canonical v1 schema with:
  - idempotent initialization
  - unique `(project_id, cid)` protection
  - core status/scalar indexes
- Added the first test harness:
  - fixture DB bootstrap
  - coverage logic tests
  - duplicate CID protection test
  - sample gosom payload fixture
- Verified the foundation locally:
  - `python -B -m pytest -p no:cacheprovider tests`
  - `python -B -c "from main import app; print(app.title)"`

**Finish point for this session:** `A1`, `A2`, `A3`, and `A4` are complete. Implementation should resume at **`Track B — Task B1: Project CRUD API`**, then **`B2: UI shell and navigation`**, then move into **Phase 1 / Track C**.

---

## 2026-06-01 — Phase 2 spec repair: title normalized and truncation fixed

Cleaned up `phases/phase2-enrichment-design.md` before implementation starts so the enrichment spec is internally usable as a canonical phase doc:

- renamed the outdated document title to `Phase 2 — Enrichment`
- removed the truncated tail ending (`## E`)
- added the missing operational closeout sections:
  - Companies House matching rules
  - SMTP verification rules and confidence mapping
  - checkpoint/resume behavior
  - Phase 2 REST endpoints
  - file structure
  - output contract
  - handoff into Phase 3

**Finish point for this session state:** Phase 2 spec is now structurally consistent with Phase 1 and Phase 3 docs. Implementation still has not started; the next execution task remains `A1 — Create project skeleton`.

---

## 2026-06-01 — Implementation kickoff alignment: canonical start point locked

Reviewed the current execution docs before any code is written so future sessions can resume from one explicit build boundary instead of re-reading the whole design set.

- Reconfirmed the canonical execution set: `HANDOFF-NEXT-SESSION.md`, `SESSION-LOG.md`, `IMPLEMENTATION-TASK-LIST.md`, `PIPELINE-MASTER.md`, `UI-SPEC.md`, and `phases/phase1-discovery.md` through `phases/phase3-normalise-dedup.md`.
- Reconfirmed there is still **no application code** in the workspace and that this is still the first implementation session.
- Reconfirmed the active build contract: v1 is only Phase 1, Phase 2, and Phase 3; Phase 4 and Phase 5 remain deferred.
- Reconfirmed the immediate execution point: start with **Track A — Foundation**, specifically `A1` through `A4`, before any Phase 1/2 feature work.
- Reconfirmed the sequencing guardrail: do not start Phase 2 implementation until the Phase 1 data model and insert path are stable.

**Finish point for this session:** documentation alignment complete; no code started yet; next implementation action remains `Task A1 — Create project skeleton`, followed by `A2`, `A3`, and `A4`.

---

## 2026-06-01 — Build-prep pass: implementation task list and handoff locked

Converted the existing design docs into an execution-ready build plan for the first coding session:

- Added `IMPLEMENTATION-TASK-LIST.md` as the concrete task plan for agents, covering foundation, API/UI shell, Phase 1, Phase 2, Phase 3, orchestration, testing, and sign-off.
- Added `HANDOFF-NEXT-SESSION.md` so the next session can start building immediately instead of re-planning.
- Elevated the two main implementation risks into explicit build requirements:
  - **SMTP verification** must be conservative about false negatives: 1 probe/sec, backoff, tri-state results, confidence downgrade rather than invalidation.
  - **Companies House matching** must be confidence-scored and ambiguity-safe: normalized matching first, postcode/domain-supported narrowing, conservative fuzzy fallback only, leave ambiguous cases unmatched.
- Locked the standard for the next session: the project is ready for direct implementation against the current docs, with verification and live sample runs required before calling v1 working.

Docs added: `IMPLEMENTATION-TASK-LIST.md`, `HANDOFF-NEXT-SESSION.md`.

---

## 2026-06-01 — v1 contract cleanup: Groq fallback kept, theHarvester deferred to v2/test build

Resolved documentation drift through explicit product decisions:

- **Canonical v1 enrichment stack** is now: `httpx[http2] + Selectolax + JSON-LD + regex` with **direct Groq API fallback** only when deterministic extraction misses `email`, `phone`, or `person name`.
- **Removed from v1 core**: `ScrapeGraphAI`, `EmailFinder`, and `email-verifier Docker`.
- **Retained for later testing only**: `theHarvester` moved to **v2 / experimental OSINT expansion**, not part of the v1 build contract.
- **Status fields renamed semantically**: `website_status`, `ai_fallback_status`, `whois_mx_status`, `companies_house_status`, `smtp_status`, `output_status`.
- **Canonical phase numbering confirmed**: Phase 1 discovery, Phase 2 enrichment, Phase 3 normalise/dedup/export, Phases 4-5 deferred.

Docs updated: `AGENT.md`, `PIPELINE-MASTER.md`, `phases/phase1-discovery.md`, `phases/phase2-enrichment-design.md`, `phases/phase3-normalise-dedup.md`.

---

## 2026-06-01 — v1 contract locked: one UI, one API, one schema, no deferred fields in v1 outputs

Locked the implementation contract for the first build:

- **Canonical UI architecture**: FastAPI serves Jinja2 templates and HTML fragments; HTMX handles navigation/polling; Alpine.js handles micro-interactions; Leaflet.js renders the coverage map.
- **Canonical REST API shape**: project-scoped endpoints under `/api/projects/{id}/...`; removed the parallel `/api/run`, `/api/stop`, and flat export contract from the UI spec.
- **Canonical SQLite schema**: the `leads` table uses `raw_data`, `enrichment_data`, `enrichment_version`, indexed `primary_*` fields, and `outreach_ready` as defined in `PIPELINE-MASTER.md`.
- **Deferred-field cleanup**: removed score-related UI/output examples from v1, removed `quality_score` from the v1 enrichment example, and removed `yell_scrape` from v1 `enrichment_sources_used`.
- **Phase numbering fixed**: v1 is now consistently Phase 1 discovery, Phase 2 enrichment, Phase 3 normalise/dedup/export; deferred work is Phase 4 web audit and Phase 5 lead scoring.

Docs updated: `AGENT.md`, `PIPELINE-MASTER.md`, `UI-SPEC.md`, `phases/phase1-discovery.md`, `phases/phase2-enrichment-design.md`, `phases/phase3-normalise-dedup.md`.

---

## 2026-05-31 — Stack improvements: Selectolax, httpx[http2], SMTP rate limiting, Postcodes.io bulk

Four changes adopted from external review — all implementation-level, no architectural impact:

- **Selectolax replaces BeautifulSoup** for website/contact page parsing (Stage 3). CSS selectors, 10–50× faster. `pip install selectolax`.
- **httpx[http2]** — HTTP/2 enabled on all outbound enrichment requests. One shared client, connection pooling. `pip install "httpx[http2]"`.
- **SMTP rate limiting** — hard cap of 1 probe/second with 5s backoff on connection refusal. Prevents IP blacklisting by mail servers. `email_confidence` falls back to `medium` on SMTP block (MX still confirmed).
- **Postcodes.io bulk endpoint** — Phase 3 now batches all postcodes (100 per request) before the export loop instead of one request per lead.

Files updated: `phases/phase2-enrichment-design.md`, `phases/phase3-normalise-dedup.md`, `PIPELINE-MASTER.md`.

---

## 2026-05-31 — Phase renumber: swap Phase 3 ↔ Phase 4

- Normalise & Dedup moved to Phase 3 (runs immediately after enrichment, before web audit)
- Web & Presence Audit moved to Phase 4 (deferred v2, needs clean lead list as input)
- Phase files renamed: phase3-normalise-dedup.md, phase4-web-presence-outline.md
- PIPELINE-MASTER.md updated: architecture diagram, section headers, orchestration flow, pipeline tab mockup, SQLite schema (phase3_status), file structure, REST API endpoints

---

## 2026-05-31 — Master doc rebuild + archive

- New PIPELINE-MASTER.md synthesised from all 5 phase docs (phases/ folder is source of truth)
- Key changes: Phase 2 enrichment is now the authoritative multi-contact JSON model; n8n removed entirely; SQLite schema updated for rich data model; old flat Stages 3-6 approach retired
- Files archived to archive/: scraping-pipeline-master.md, enrichment-module-design.md, enrichment-research.md, web-presence-pipeline-outline.md, scraping-research-summary.md, root phase5-lead-scoring.md
- AGENT.md updated: added explicit prohibition on reading archive/ unless user asks
- phases/ folder unchanged — remains the per-phase source of truth

---

## Session 1 — 2026-05-31
**Research, design, and documentation sprint**

Worked through the full pipeline design from scratch. Selected gosom as the Google Maps scraper and designed an adaptive quadtree layer in Python to handle the 120-result cap. Settled on the enrichment stack: gosom email flag + regex + ScrapeGraphAI/Groq for website email, theHarvester + EmailFinder for OSINT, Companies House API for owner names, and email-verifier Docker for permutation checking. Replaced n8n with FastAPI + SQLite for orchestration after concluding n8n added complexity without benefit. Established the checkpoint/resume pattern that applies uniformly across all stages.

**Decisions made:**
- gosom via REST API (not Docker flags), dedup key = Google CID
- No local AI — Groq free endpoint only
- n8n removed entirely, FastAPI + SQLite + Leaflet.js UI
- Yell.com top-up deferred to v2 (scraper chosen, design complete)
- Phase 3 (web presence audit) and Phase 5 (lead scoring) deferred to v2 with placeholders written
- Phase 4 split: Normalise/Dedup is v1; scoring becomes its own Phase 5

**Left off / next session:** Environment setup. Install Docker, pull gosom and email-verifier images, run a test scrape against the Swansea bbox, get Groq API key, then start building the FastAPI app (SQLite schema first).
