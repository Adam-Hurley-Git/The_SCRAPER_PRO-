# Scraper Pro — Agent Context

## What this is

A fully automated, zero-cost pipeline that discovers local businesses in Swansea/South Wales from Google Maps, enriches each lead with verified contact data (email, phone, owner name), and exports a clean spreadsheet ready for outreach. Everything is self-hosted; the only external dependency with a cost concern is the Groq API fallback used when deterministic extraction is incomplete.

**Foundation and Track B code now exist.** The app scaffold, env contract, SQLite bootstrap, first tests, project CRUD API, and UI shell are in place. The next step is Track C and live Phase 1 wiring, not another planning pass.

---

## Workspace Structure

- App and code files stay at repo root plus `pipeline/`, `templates/`, `static/`, `tests/`, and `data/`.
- Planning and operations files live under `docs/`:
  - `docs/agent/AGENT.md`
  - `docs/planning/PROJECT-GOAL.md`
  - `docs/planning/PIPELINE-MASTER.md`
  - `docs/planning/UI-SPEC.md`
  - `docs/ops/IMPLEMENTATION-TASK-LIST.md`
  - `docs/ops/HANDOFF-NEXT-SESSION.md`
  - `docs/ops/SESSION-LOG.md`
  - `docs/GIT-WORKFLOW.md`

Keep planning and agent files out of the application root.

---

## ⚠️ Archive Folder — DO NOT READ
The `archive/` folder contains outdated documents superseded by the `phases/` folder and `docs/planning/PIPELINE-MASTER.md`.
**Never read files in `archive/` unless the user explicitly asks you to.**
Treat it as write-once storage for historical reference only.

---

## Pipeline at a glance

| Stage | What it does | Status |
|---|---|---|
| 1 — Discovery | gosom/google-maps-scraper via Docker, adaptive quadtree coverage | v1 |
| 2 — Yell top-up | yell-scraper to catch non-Google listings | Deferred to v2 |
| 3 — Website extraction | httpx[http2] + Selectolax + JSON-LD + regex, with Groq fallback when email, phone, or person name is missing | v1 |
| 4 — WHOIS + MX | python-whois + dnspython | v1 |
| 5 — Company enrichment | Companies House API (free UK gov) | v1 |
| 6 — SMTP verification | dns-smtp-email-validator, rate-limited | v1 |
| Normalise & Dedup | phonenumbers → E.164, dedup by Google CID, export leads.xlsx | v1 |
| Lead scoring | 0–10 score, hot lead threshold ≥7 | Deferred to v2 (Phase 5) |
| Web presence audit | Domain age, social profiles, tech stack detection | Deferred to v2 (Phase 4) |
| OSINT expansion | theHarvester experiments for additional public contact discovery | Deferred to v2 / test build |

Orchestration is FastAPI + SQLite. The UI is server-rendered via Jinja2 fragments with HTMX + Alpine.js, plus Leaflet.js for the map. ~40–80 MB idle RAM.

**Checkpoint/resume is universal.** Every lead has a status per stage (`pending / running / done / failed`). Any run only touches `pending`. Interrupted runs reset in-flight records to `pending` on next start.

---

## Key decisions (don't re-litigate these)

**gosom, not self-rolled scraping.** Handles Google's 120-result cap via our adaptive quadtree layer in Python — gosom itself is controlled via its REST API (`-web` flag), not direct Docker flags. Dedup key is Google CID.

**n8n removed.** Originally considered for orchestration. Replaced with FastAPI + SQLite because it's simpler, more controllable, and the REST API design means an AI agent can drive the pipeline identically to a human clicking buttons.

**No local AI.** v1 uses direct Groq API calls as a fallback extractor only after deterministic parsing runs. No ScrapeGraphAI, no Ollama, no local model. The fallback is triggered only if `email`, `phone`, or `person name` is still missing, and any AI-recovered value must include evidence (`snippet + page source label`) from the supplied content.

**Yell deferred deliberately.** The scraper is chosen (abdalrhman-abas-0/yell-scrper), the merge key is name+postcode, the design is done. Deferred because gosom alone should yield sufficient volume for v1.

**Old Option B tools removed from v1.** `EmailFinder` and `email-verifier Docker` are out. `theHarvester` is retained only as an explicit v2/experimental OSINT add-on so it can be tested later without enlarging the minimal v1 core.

**Phase 4 and Phase 5 deferred.** Not cut — placeholders exist in `phases/`. They're fully designed, just not built in v1 to keep scope manageable.

---

## Output schema (leads.xlsx, 14 fields)

`business_name`, `category`, `address`, `postcode`, `phone_raw`, `phone_e164`, `website`, `email`, `email_confidence`, `owner_name`, `company_number`, `google_cid`, `source`, `scrape_date`

---

## What to read for what

| Need | Document |
|---|---|
| Canonical project objective and scope | `docs/planning/PROJECT-GOAL.md` |
| Full implementation detail, API contracts, config | `docs/planning/PIPELINE-MASTER.md` |
| Research behind tool choices | `research/` |
| Deferred phase designs | `phases/phase4-web-presence-outline.md`, `phases/phase5-lead-scoring.md` |
| Enrichment design detail | `phases/phase2-enrichment-design.md` |
| Session history, what was last decided | `docs/ops/SESSION-LOG.md` |

---

## Git Discipline

- Use git as the operational record for the project, not only as backup.
- Push meaningful checkpoints to GitHub on coherent units of work.
- Every non-trivial commit must explain:
  - what changed
  - why it changed
  - what decision, constraint, or tradeoff was locked
- When implementation state changes, update the matching docs in the same change set.
- Follow `docs/GIT-WORKFLOW.md` and the local `.gitmessage.txt` template.

---

## What comes next

1. Wire `C1` — gosom REST client into real project flow
2. Implement `C2` / `C3` — quadtree queueing and lead ingestion
3. Implement `C4` / `C5` — coverage endpoints and live Phase 1 UI binding
4. Stand up gosom locally and prove a real single-cell REST run
5. Complete `C6` before touching Phase 2 orchestration
