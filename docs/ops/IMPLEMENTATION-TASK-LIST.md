# Scraper Pro — Implementation Task List
*Prepared 2026-06-01 from `docs/planning/PROJECT-GOAL.md`, `docs/planning/PIPELINE-MASTER.md`, `docs/planning/UI-SPEC.md`, and `phases/` specs.*

---

## Purpose

This document converts the agreed design into a concrete build sequence that an agent can execute without re-planning the architecture.

---

## Current Execution Checkpoint

**Updated:** 2026-06-01

Current confirmed position:

- planning/spec alignment is complete
- `A1`, `A2`, `A3`, `A4`, `B1`, and `B2` are complete
- application scaffold, env contract, SQLite bootstrap, first tests, project CRUD API, and UI shell now exist

**Last completed task:** `Track B -> Task B2 — UI shell and navigation`

**Canonical next task:** `Track C -> Task C1 — gosom REST client`

**Current build block to finish before moving on:**

1. `C1` — gosom REST client
2. `C2` — Coverage cell model and queue logic
3. `C3` — Lead ingestion and dedup
4. `C4` — Coverage endpoints

**Current stop point rule for future sessions:** when a session ends, update this section with the exact last completed task and the exact next task. Do not leave the finish point implicit.

It is for **v1 only**:

- Phase 1 — Discovery
- Phase 2 — Enrichment
- Phase 3 — Normalise, dedup, export

Explicitly **out of scope**:

- Phase 4 — Web & Presence Audit
- Phase 5 — Lead Scoring
- Yell top-up
- Experimental OSINT expansion

The source-of-truth docs remain:

- `docs/planning/PROJECT-GOAL.md` — product objective and scope
- `docs/planning/PIPELINE-MASTER.md` — schema, API, orchestration, file structure
- `docs/planning/UI-SPEC.md` — UI contract
- `phases/phase1-discovery.md`
- `phases/phase2-enrichment-design.md`
- `phases/phase3-normalise-dedup.md`

This file is the **execution plan**, not a replacement for those specs.

### Foundation Completed

- `A1` — Create project skeleton
- `A2` — Dependencies and environment contract
- `A3` — SQLite schema bootstrap
- `A4` — Basic test harness

### Track B Completed

- `B1` — Project CRUD API
- `B2` — UI shell and navigation

---

## Build Rules

1. Build the exact v1 contract already documented. Do not widen scope mid-build.
2. Keep checkpoint/resume semantics universal.
3. Deterministic extraction always runs before Groq fallback.
4. Preserve evidence for all AI-recovered values.
5. Deduplicate by Google CID only in v1.
6. Treat uncertain enrichment conservatively. Unknown is acceptable; invented certainty is not.
7. A phase is not complete until it has:
   - implementation
   - API wiring
   - UI visibility
   - verification tests
   - one real run against sample data

---

## Critical Risk Decisions To Implement

These two areas must be implemented deliberately because they can silently degrade output quality.

### 1. SMTP verification: throughput and false negatives

Problem:

- SMTP probing is slow by nature
- Some mail servers greylist, tarp it, refuse VRFY/RCPT checks, or silently drop connections
- A failed SMTP check must not automatically mean the email is invalid

Implementation rules:

1. Hard cap SMTP probes at `1 probe/second` globally for v1.
2. Add `5s` backoff after connection refusal or server disconnect.
3. Never retry the same address in the same run.
4. Distinguish:
   - `smtp_verified_true`
   - `smtp_verified_false`
   - `smtp_unverifiable`
5. Do not downgrade a syntactically valid + MX-valid address to unusable just because SMTP probing was blocked.
6. Preserve separate fields for:
   - syntax validity
   - MX validity
   - SMTP result
   - final confidence
7. Use SMTP to raise confidence, not as the only gate for retaining an email.

Acceptance rules:

- SMTP-disabled or hostile mail servers must not collapse email coverage.
- Emails with `MX=true` and `SMTP blocked/error` must remain usable with lower confidence.
- The pipeline must expose counts for verified vs unverifiable vs rejected.

### 2. Companies House matching: messy business names

Problem:

- Google Maps names are often noisy, branded, shortened, or location-qualified
- Companies House legal entities are often different from trading names
- Bad matching can attach the wrong owner or company number to the lead

Implementation rules:

1. Build a **tiered matcher**, not a one-shot fuzzy search.
2. Match in this order:
   - exact normalized name match
   - normalized match after stripping suffix noise
   - postcode-aware shortlist match
   - website/domain-supported match
   - conservative fuzzy fallback
3. Normalization must strip or standardize:
   - case
   - punctuation
   - `Ltd`, `Limited`, `LLP`, `Limited Liability Partnership`
   - trading prefixes/suffixes like city names where clearly decorative
   - repeated whitespace
4. Prefer candidates that agree on:
   - postcode or locality
   - website/domain clues
   - category plausibility
5. Store a `match_confidence` and `match_method`.
6. If ambiguity remains, leave Companies House data blank and mark the lead for review instead of forcing a match.
7. Never attach officers/PSC/financials from a low-confidence company match.

Acceptance rules:

- Wrong-company attachment rate must be biased toward zero, even if recall drops.
- Ambiguous matches must be visible in UI/API.
- Sample validation against messy local business names must be performed before phase sign-off.

---

## Deliverables

At the end of the build, the repo/workspace should contain:

- FastAPI app skeleton
- SQLite schema creation and migration bootstrap
- gosom client and coverage engine
- Phase 1 implementation
- Phase 2 implementation
- Phase 3 implementation
- Jinja2 + HTMX + Alpine + Leaflet UI
- requirements file
- `.env.example`
- README / run instructions
- test suite
- sample project data in SQLite from at least one live run
- exported `leads.xlsx`

---

## Execution Order

Build in this order. Do not start Phase 2 before the data model and Phase 1 insert path are stable.

### Track A — Foundation

#### Task A1 — Create project skeleton

- Create the file structure defined in `docs/planning/PIPELINE-MASTER.md`
- Add:
  - `main.py`
  - `database.py`
  - `gosom_client.py`
  - `coverage.py`
  - `pipeline/phase1_discovery.py`
  - `pipeline/phase2_enrichment.py`
  - `pipeline/phase3_output.py`
  - `templates/`
  - `static/`
  - `data/`

Done when:

- App boots
- Directories exist
- Import graph is clean

#### Task A2 — Dependencies and environment contract

- Create `requirements.txt`
- Create `.env.example`
- Define env vars for:
  - `GOSOM_BASE_URL`
  - `GROQ_API_KEY`
  - `COMPANIES_HOUSE_API_KEY`
  - app host/port
  - file paths for SQLite and exports

Done when:

- Fresh environment install works
- Missing env vars fail clearly

#### Task A3 — SQLite schema bootstrap

- Implement canonical schema from `docs/planning/PIPELINE-MASTER.md`
- Add indexes for:
  - `project_id`
  - `cid`
  - status fields
  - `primary_email`
  - `primary_phone`
  - `primary_person`
- Enforce unique `(project_id, cid)` at DB level

Done when:

- Schema initializes on first run
- Re-running init is safe
- Duplicate CID insert is prevented

#### Task A4 — Basic test harness

- Add unit test setup
- Add fixture DB creation
- Add sample gosom payload fixture

Done when:

- Tests can run without live APIs

---

## Track B — Core API and Project Lifecycle

#### Task B1 — Project CRUD API

Implement:

- `GET /api/projects`
- `POST /api/projects`
- `GET /api/projects/{id}`
- `DELETE /api/projects/{id}`

Done when:

- Projects can be created from API
- Bounding box persists correctly
- Archived projects are hidden from default listing

#### Task B2 — UI shell and navigation

Implement the shell and views from `docs/planning/UI-SPEC.md`:

- `/ui/map`
- `/ui/pipeline`
- `/ui/leads`
- `/ui/scrapes`

Done when:

- Navigation works without page reloads
- Active project context is visible

---

## Track C — Phase 1 Discovery

#### Task C1 — gosom REST client

- Implement submit, poll, download methods
- Surface job errors cleanly
- Persist raw job payloads under `data/jobs/`

Done when:

- One manual test cell run succeeds against local gosom

#### Task C2 — Coverage cell model and queue logic

- Implement `subdivide()`
- Implement `cell_size()`
- Implement queue processing
- Reset `running` cells to `pending` on resume

Done when:

- Synthetic tests prove cells split correctly
- Resume logic leaves no stranded `running` records

#### Task C3 — Lead ingestion and dedup

- Save gosom output into `leads.raw_data`
- Set all Phase 2 and 3 statuses to `pending`
- Extract/store `cid`, `source`, `first_seen_cell`, timestamps
- Skip duplicates by `(project_id, cid)`

Done when:

- Re-running same cell does not duplicate leads

#### Task C4 — Coverage endpoints

Implement:

- `POST /api/projects/{id}/coverage/start`
- `GET /api/projects/{id}/coverage/status`
- `GET /api/projects/{id}/cells`

Done when:

- Cells can be polled live
- GeoJSON renders in Leaflet

#### Task C5 — Phase 1 UI

- Coverage map
- Coverage stats sidebar
- Cell detail popover
- Discovery phase row in pipeline dashboard

Done when:

- A live run visibly updates map and counts

#### Task C6 — Phase 1 verification

Run a real sample against Swansea bbox or a smaller safe subset first.

Verify:

- cells split when result count hits cap
- no cell marked complete without final status
- dedup by CID works
- coverage complete means zero unsplit cap-hit cells remain

---

## Track D — Phase 2 Enrichment

#### Task D1 — Enrichment record schema in code

- Define the Phase 2 JSON shape from `phase2-enrichment-design.md`
- Include:
  - `people`
  - `phones`
  - `emails`
  - `company`
  - `web`
  - `outreach`
  - evidence metadata
  - match metadata

Done when:

- A typed/validated record can be created from fixtures

#### Task D2 — Deterministic website extraction

- Shared `httpx[http2]` client
- Selectolax parsing
- homepage parse
- contact page parse
- JSON-LD extraction
- regex extraction for emails/phones
- person-name extraction heuristics

Done when:

- Deterministic extraction populates contacts on fixture pages and live sample pages

#### Task D3 — AI fallback integration

- Trigger only when `email`, `phone`, or `person name` is missing
- Pass only cleaned content + metadata + partial deterministic results
- Require evidence fields in model output
- Reject unevidenced values

Done when:

- Fallback can recover at least one missing field in controlled test cases
- Unevidenced output is discarded

#### Task D4 — WHOIS and MX stage

- Domain extraction from final URL
- WHOIS lookup
- MX lookup
- Write results into `web` and email validation metadata

Done when:

- Known domains produce expected MX and WHOIS records

#### Task D5 — Companies House stage

- Search API client
- candidate normalization
- shortlist scoring
- confidence/method recording
- officer/PSC/financial extraction only for confident matches

Done when:

- exact and messy-name fixtures both pass
- ambiguous fixtures remain unmatched rather than wrong-matched

#### Task D6 — SMTP verification stage

- Global rate limiter
- backoff rules
- no same-run retry
- result tri-state storage
- confidence mapping

Done when:

- SMTP stage can process a test batch without overwhelming targets
- blocked/unverifiable domains remain in usable output with lower confidence

#### Task D7 — Phase 2 checkpoint engine

- Per-lead stage runner
- status transitions:
  - `pending -> running -> done/failed`
- reset `running -> pending` on resume
- `retry failed` support by stage

Done when:

- interrupted enrichment run resumes correctly
- failed-only retry affects only failed leads

#### Task D8 — Indexed scalar extraction

- Write `primary_email`
- Write `primary_phone`
- Write `primary_person`
- Write `outreach_ready`

Done when:

- leads filtering/export does not need to parse JSON for common columns

#### Task D9 — Phase 2 endpoints

Implement:

- `POST /api/projects/{id}/phases/2/run`
- `POST /api/projects/{id}/phases/2/resume`
- `POST /api/projects/{id}/phases/2/retry`
- `GET /api/projects/{id}/pipeline/status`

Done when:

- Phase 2 is fully operable through API

#### Task D10 — Phase 2 UI

- pipeline dashboard rows for website, AI fallback, WHOIS/MX, Companies House, SMTP
- throughput panel
- failed-items drill-down
- ambiguous Companies House and SMTP-unverifiable visibility

Done when:

- User can see progress, failure counts, and queue health without opening the DB

#### Task D11 — Phase 2 verification suite

Create a real sample set covering:

- website with obvious email
- website with contact-page-only email
- website with no email but recoverable via AI
- website with dead domain
- email domain with MX but no SMTP cooperation
- messy trading name with correct Companies House match
- ambiguous name that must remain unmatched

Done when:

- enrichment results are reviewed against expected outcomes

---

## Track E — Phase 3 Output

#### Task E1 — Postcodes.io bulk lookup

- batch unique postcodes up to 100/request
- enrich leads before export loop

Done when:

- export path does not call Postcodes.io per row

#### Task E2 — Phone normalisation

- implement E.164 normalization using `phonenumbers`
- preserve raw phone values

Done when:

- sample UK numbers normalize correctly

#### Task E3 — Final dedup confirmation

- confirm no duplicate CIDs slipped through
- log/remediate any that did

Done when:

- export source set is unique by CID

#### Task E4 — XLSX export

- implement `leads.xlsx` output schema exactly as documented
- style header row
- wire export endpoint

Done when:

- exported file opens cleanly
- columns match `docs/agent/AGENT.md` / `phase3-normalise-dedup.md`

#### Task E5 — Phase 3 endpoints and UI

Implement:

- `POST /api/projects/{id}/phases/3/run`
- `POST /api/projects/{id}/phases/3/resume`
- `GET /api/projects/{id}/leads/export`

Done when:

- export can be triggered from API and UI

#### Task E6 — Phase 3 verification

Verify:

- phone formatting
- export row count
- no duplicate CIDs
- output file fields correct

---

## Track F — Full Pipeline Orchestration

#### Task F1 — Run-all orchestration

Implement:

- `POST /api/projects/{id}/run`
- `POST /api/projects/{id}/stop`

Rules:

- run Phase 1 -> Phase 2 -> Phase 3 in sequence
- stop on hard phase failure
- preserve checkpoint state

Done when:

- one command can drive full pipeline end to end

#### Task F2 — Pipeline run logging

- write `pipeline_runs`
- record totals, done, failed, timestamps
- expose live counts to UI

Done when:

- throughput and phase progress are queryable

---

## Track G — Validation and Operations

#### Task G1 — Environment bring-up

- install Python deps
- install Docker
- run gosom container in REST mode
- set API keys

Done when:

- local app and gosom are both reachable

#### Task G2 — Automated tests

Minimum required tests:

- schema init
- CID dedup
- cell subdivision logic
- checkpoint reset logic
- deterministic parser fixtures
- AI evidence validation
- Companies House matcher fixtures
- SMTP confidence mapping
- phone normalization
- export row generation

Done when:

- test suite passes locally

#### Task G3 — Real integration test

Run a small live project end to end.

Required proof:

- Phase 1 completes
- Phase 2 enriches a meaningful subset
- Phase 3 exports `leads.xlsx`
- UI reflects live progress correctly

#### Task G4 — Documentation closeout

Update after implementation:

- `docs/agent/AGENT.md`
- `docs/ops/SESSION-LOG.md`

## Git Closeout Rule

At the end of each coherent work block:

1. update the checkpoint section above
2. update `docs/ops/SESSION-LOG.md`
3. update `docs/ops/HANDOFF-NEXT-SESSION.md` if the resume point changed
4. commit with action, reason, and decision context
5. push the checkpoint to GitHub unless explicitly told not to
- handoff doc
- run instructions

Done when:

- the next agent can start from the built system rather than re-reading all planning docs

---

## Sign-Off Checklist

The build is only considered complete when all items below are true:

- App starts cleanly
- SQLite schema self-initializes
- gosom integration works against a live cell
- Phase 1 coverage completes with visible quadtree state
- Phase 2 deterministic extraction works on live samples
- Groq fallback runs only when required
- SMTP logic is rate-limited and conservative about false negatives
- Companies House matching is confidence-scored and ambiguity-safe
- Phase 3 produces a correct `leads.xlsx`
- UI and API can both drive the same pipeline
- Resume and retry flows work
- Tests pass
- At least one real end-to-end sample run is completed and reviewed

---

## Recommended Build Sequence For Next Session

1. Foundation: A1-A4
2. Core API/UI shell: B1-B2
3. Phase 1: C1-C6
4. Phase 2 data model and deterministic extraction: D1-D4
5. Risk-sensitive enrichment pieces: D5-D6
6. Phase 2 orchestration/UI: D7-D11
7. Phase 3: E1-E6
8. Full orchestration: F1-F2
9. Validation/ops: G1-G4

This is the execution order agents should follow unless the user explicitly changes scope.
