# Session Log
*Newest first. Each entry is a 30-second scan.*

---

## 2026-06-01 — Thirteenth implementation session: D6–D10 completed, Phase 2 fully implemented

Continued from D5 and completed the remaining Phase 2 track in a single session.

**D6 — SMTP verification stage:**
- Added 5 DB functions: reset/claim/count/update/retry for smtp_status
- Added `_smtp_rate_limit()` (module-level 1 probe/second global cap), `_resolve_mx_host()` (DNS MX lookup), `smtp_probe_email()` (SMTP RCPT TO handshake, tri-state, never raises, 5s backoff on connection error)
- Added `apply_smtp_verification()`: maps result to confidence, no same-run retry via probed_addresses set, smtp_unverifiable preserves MX-based medium confidence
- Added `run_smtp_stage()`: chains all of the above with DB lifecycle
- 16 tests covering all confidence mapping cases, no-same-run-retry, mocked SMTP handshakes (250/550/connect-error/no-MX), and full DB lifecycle

**D7 + D9 — Phase 2 checkpoint engine and REST endpoints:**
- Added `get_phase2_status()` and `retry_failed_leads_for_stage()` to database.py
- Added `run_phase2_all_stages()` orchestrator: chains website → CH → SMTP, each stage self-resets stranded running rows on resume
- Added `retry_phase2_stage()`: re-queues failed leads for a named stage
- Wired 4 REST endpoints into main.py: POST /phases/2/run, /resume, /retry, GET /pipeline/status
- 14 tests covering orchestrator chaining, resume resets stranded rows for both website and CH stages, retry isolation, and all 4 API endpoints

**D8 — Indexed scalar extraction (already wired, now verified):**
- 4 tests prove primary_email/phone/person/outreach_ready written by each stage update function and queryable without JSON parsing

**D10 — Phase 2 UI:**
- Updated pipeline_status.html partial: live per-stage rows for website extraction, Companies House, SMTP with done/running/failed counts, progress bars, and per-stage Retry buttons via HTMX
- Updated ui_pipeline and ui_pipeline_status routes to pass phase2_status context

All 55 Phase 2 tests pass (D5 through D10). Committed across 4 commits.

**Finish point for this session:** D6, D7, D8, D9, and D10 are all complete. Phase 2 is fully implemented. The exact next implementation action is **`Track E — Task E1: Postcodes.io bulk lookup`**, then E2–E6 (Phase 3 output), then F1–F2 (full orchestration).

---

## 2026-06-01 — Twelfth implementation session: D5 completed — Companies House stage

Continued from the D4 boundary and implemented the full Companies House stage.

- Confirmed D5 contract from existing code: `apply_companies_house_data`, candidate scoring, `select_companies_house_match`, and all CH API helpers were already in `pipeline/phase2_enrichment.py` from prior work; what was missing was the DB lifecycle layer and the stage runner.
- Added 5 DB functions to `database.py`:
  - `reset_running_companies_house_leads` — resets stranded `running` rows to `pending` on resume
  - `claim_next_pending_companies_house_lead` — atomically claims leads where `website_status='done'` and `companies_house_status IN ('pending','retry')`
  - `count_pending_companies_house_leads` — backlog count for the stage result payload
  - `update_lead_companies_house_enrichment` — writes enrichment data + `companies_house_status` and refreshes scalar columns
  - `retry_failed_companies_house_leads` — requeues failed leads into `retry`
- Added `run_companies_house_stage()` to `pipeline/phase2_enrichment.py`:
  - resets stranded running leads first
  - resolves API key from settings if no injectable lookups are provided
  - claims and processes leads that have completed the website stage
  - calls `apply_companies_house_data()` on the existing enrichment record
  - writes CH status and updated enrichment data back via `update_lead_companies_house_enrichment`
  - on exception, marks the lead failed without corrupting the existing enrichment data
- Created `tests/test_phase2_companies_house.py` with 21 tests:
  - normalization: legal suffix stripping, `&`→`and` expansion
  - matching: exact_normalized, suffix_stripped_exact, postcode_supported, domain_supported
  - ambiguous: two identical candidates produce score tie → `select_companies_house_match` returns None
  - empty search: returns None
  - unrelated candidate: no match
  - `apply_companies_house_data`: populates company number/status/match method for confident match; attaches officers and PSCs; leaves ambiguous cases unmatched with no CH data attached; returns `pending` when no lookup is provided
  - DB lifecycle: processes a done-website lead end-to-end; skips leads with pending website stage; resets stranded running rows; retries failed leads; counts pending correctly
- All 21 new tests pass. Pre-existing failures in test_database.py and test_gosom_client.py are unrelated (sqlite3.Row vs tuple comparison and gosom client interface issues from earlier sessions).
- Committed as `feat(D5): Companies House stage — matching, DB lifecycle, and tests` (commit e9481ec).

**Finish point for this session:** `D5` is complete. The exact next implementation action is now **`Track D — Task D6: SMTP verification stage`**.

---

## 2026-06-01 — Eleventh implementation session: D4 completed with live WHOIS/MX proof

Continued from the `D4` boundary and implemented the WHOIS/MX stage as the next coherent Phase 2 slice rather than jumping ahead to Companies House.

- Used a subagent to confirm the exact D4 contract from the docs:
  - derive the domain from the final URL
  - run WHOIS lookup
  - run MX lookup
  - write results into `web` plus email validation metadata
- Implemented the D4 slice in code:
  - added final-domain extraction from `web.url_final`
  - added WHOIS lookup support for `web.whois_owner`, `web.domain_registered`, and `web.domain_expires`
  - added MX lookup support for `emails[*].mx_valid`
  - added `whois_mx_status` persistence through the Phase 2 DB write path
  - aligned email confidence to the spec by starting deterministic emails at `low` and only promoting to `medium` once MX is confirmed
- Added and passed D4 tests proving:
  - domain extraction normalizes expected hosts
  - WHOIS and MX metadata can be applied directly to an enrichment record
  - `run_phase2(...)` persists WHOIS/MX results into the stored lead payload
- Completed the real runtime dependency path:
  - confirmed DNS support already existed in the active Python environment
  - installed `python-whois`
  - added `python-whois==0.9.6` to `requirements.txt`
  - updated the live probe output to include `whois_mx_status`
- Captured a real end-to-end D4 proof:
  - ran `tools/live_phase2_probe.py` against `https://www.greek-flavours.com/`
  - captured output in `data/live_phase4_probe.json` showed:
    - `website_status='done'`
    - `ai_fallback_status='failed'`
    - `whois_mx_status='done'`
    - `mx_valid=true`
    - `confidence='medium'`
    - `whois_owner='REDACTED FOR PRIVACY'`
    - `domain_registered='2025-07-19'`
    - `domain_expires='2026-07-19'`
- Re-ran verification successfully:
  - `python -B -m pytest -p no:cacheprovider tests\test_phase2_deterministic.py tests\test_phase2_models.py tests\test_database.py`
  - `python -B -m pytest -p no:cacheprovider tests`

**Finish point for this session:** `D4` is complete. The exact next implementation action is now **`Track D — Task D5: Companies House stage`**. `C6` remains open but non-blocking.

---

## 2026-06-01 — Tenth implementation session: D3 completed with evidence-gated AI fallback

Continued from the `D3` boundary and implemented the first complete AI fallback stage rather than leaving it as a test-only hook.

- Used a subagent to confirm the exact D3 contract from the docs before integrating:
  - trigger only when deterministic extraction still misses `email`, `phone`, or `person name`
  - pass only cleaned content + metadata + deterministic partials
  - require evidence fields in model output
  - reject unevidenced values
- Implemented the D3 merge path in code:
  - added `needs_ai_fallback(...)`
  - added a cleaned-input builder for homepage/contact-page text plus deterministic partial results
  - added typed AI fallback result validation and evidence-gated merge logic
  - fallback now only fills missing fields instead of overwriting deterministic ones
- Added direct Groq API support:
  - added `GROQ_MODEL` to config and `.env.example`
  - added direct Groq chat-completions calling through `httpx`
  - added JSON extraction/parsing from model output
  - kept the path injectable and testable so controlled tests do not depend on live credentials
- Fixed a real runtime defect uncovered by the live Groq-backed probe:
  - an AI fallback exception previously collapsed the whole website-stage lead to `website_status='failed'` and wiped deterministic output
  - AI failure now only degrades `ai_fallback_status`, while deterministic website-stage output is preserved
- Added and passed D3 tests proving:
  - fallback can recover a missing person with evidence in a controlled test case
  - unevidenced AI output is rejected
  - AI fallback exceptions do not destroy deterministic website-stage results
- Re-ran live proof with the provided Groq key scoped only to the process:
  - the live Groq-backed probe against `https://www.greek-flavours.com/` finished with:
    - `website_status='done'`
    - `ai_fallback_status='failed'`
    - deterministic `primary_email='info@greek-flavours.com'`
    - deterministic `primary_phone='01792381143'`
    - `primary_person=null`
  - this is acceptable for D3 completion because the done condition requires controlled recovery + rejection behavior, not guaranteed recovery on every real site
- Re-ran verification successfully:
  - `python -B -m pytest -p no:cacheprovider tests\test_phase2_deterministic.py tests\test_phase2_models.py tests\test_database.py`
  - `python -B -m pytest -p no:cacheprovider tests`

**Finish point for this session:** `D3` is complete. The exact next implementation action is now **`Track D — Task D4: WHOIS and MX stage`**. `C6` remains open but non-blocking.

---

## 2026-06-01 — Ninth implementation session: D2 completed with live website-stage proof

Continued from the website-stage resume/retry checkpoint and finished the missing D2 proof path rather than broadening scope prematurely.

- Used a subagent to shortlist strong real candidate sites from the existing local gosom payloads while keeping the implementation local
- Added a repo-local live proof harness:
  - created `tools/live_phase2_probe.py`
  - the script creates a temporary project/lead, runs `run_phase2(...)` against a supplied real website, and captures the resulting lead payload to JSON
  - fixed the script so it can run reliably from any working directory by inserting the repo root into `sys.path`
  - hardened the script cleanup path to avoid temp-directory teardown failures
- Fixed a real runtime defect exposed by the live probe:
  - `create_http_client(...)` previously hard-failed if `http2=True` support was unavailable because `h2` was not installed
  - the HTTP client now falls back cleanly to HTTP/1.1 instead of failing the entire website stage
  - added focused test coverage for that fallback behavior
- Tightened deterministic extraction quality based on the live proof output:
  - phone normalization now rejects implausible long local-number strings
  - person-name heuristics are more conservative and filter more navigation/menu noise
  - `outreach.primary_person` is now left `null` unless a stronger person candidate exists, which is preferable to promoting weak text-only guesses before `D3`
- Captured a real end-to-end website-stage proof:
  - ran `tools/live_phase2_probe.py` against `https://www.greek-flavours.com/`
  - captured output showed:
    - `processed=1`
    - `failed=0`
    - `remaining=0`
    - `website_status='done'`
    - `primary_email='info@greek-flavours.com'`
    - `primary_phone='01792381143'`
    - `primary_person=null`
  - this is sufficient for the D2 done condition because deterministic extraction is now proven on fixtures and on a real live sample page path
- Re-ran verification successfully:
  - `python -B -m pytest -p no:cacheprovider tests\test_phase2_deterministic.py tests\test_phase2_models.py tests\test_database.py`
  - `python -B -m pytest -p no:cacheprovider tests`

**Finish point for this session:** `D2` is complete. `C6` remains open but non-blocking. The exact next implementation action is now **`Track D — Task D3: AI fallback integration`**.

---

## 2026-06-01 — Sixth implementation session: C6 backgrounded, D2 deterministic website stage started

Continued from the live gosom + `D1` checkpoint with an explicit strategy change from the user: stop spending active build time chasing a cap-hit proof, queue one dense verification run in the background, and keep the main implementation front moving through Phase 2.

- Started a non-blocking dense verification run through the real app API instead of holding the session on it:
  - created project `Background London Cap Probe`
  - project id: `57ab8ce3-3468-4f3a-ada7-764f2ab83cde`
  - bbox: `51.4800,-0.2600,51.5600,0.0200`
  - primary term: `builders`
  - observed immediately after launch and again before handoff:
    - `cells_running=1`
    - `cells_failed=0`
    - `leads_found=0`
    - `coverage_complete=false`
- Implemented the first executable slice of **Track D2 — Deterministic website extraction**:
  - added deterministic helpers for:
    - regex email extraction
    - regex phone extraction
    - JSON-LD extraction
    - contact-link discovery
    - simple person-name heuristics
  - added optional Selectolax-backed HTML parsing with fallback behavior when the package is not installed locally
  - extended `build_enrichment_record(...)` so homepage/contact-page evidence can populate emails, phones, people, outreach fields, and enrichment-source metadata
  - added a shared `httpx` client factory and page-fetch helper for the Phase 2 website stage
  - replaced the old Phase 2 stub with a first website-stage runner that:
    - pulls pending leads
    - fetches a homepage
    - follows one contact link when available
    - builds deterministic enrichment output
    - writes `enrichment_data`, `enrichment_version`, `website_status`, `primary_email`, `primary_phone`, `primary_person`, and `outreach_ready`
    - marks missing/unfetchable websites as failed instead of silently skipping them
- Added tests covering the new D2 slice:
  - deterministic extraction from homepage/contact-page fixture HTML
  - contact-link filtering to same-domain paths
  - Phase 2 persistence back into the `leads` table through a fake fetcher

Verification completed for this session:

- `python -B -m pytest -p no:cacheprovider tests\test_phase2_models.py tests\test_phase2_deterministic.py tests\test_database.py`
- `python -B -m pytest -p no:cacheprovider tests`
- live check of the background probe status through `/api/projects/57ab8ce3-3468-4f3a-ada7-764f2ab83cde/coverage/status`

Constraints still open after this session:

- `C6` is still not complete because live cap-hit subdivision remains unproven
- `D2` is not yet complete because deterministic extraction is proven on fixtures and persistence, but not yet on a real live sample page run

**Finish point for this session:** `C5` and `D1` remain the last fully signed-off completed tasks. `C6` is now intentionally background-only verification. `D2` has started and its first executable extraction/persistence slice is implemented. The exact next implementation action is still **`Track D — Task D2: deterministic website extraction`**.

---

## 2026-06-01 — Seventh implementation session: D2 contract alignment tightened, live reachability confirmed

Continued from the first `D2` executable slice and tightened the deterministic website stage around the Phase 2 contract rather than broadening scope.

- Used a subagent to audit the current D2 state against the spec while keeping the critical-path edits local:
  - the audit confirmed D2 still should not be marked complete
  - the highest-signal issues were the `website_status` vocabulary mismatch, weak handling of non-2xx homepage outcomes, coarse source attribution, and missing strong live proof
- Fixed the most important D2 contract mismatches in code:
  - `web.url_final` now persists the homepage final URL rather than incorrectly drifting to the contact-page URL
  - homepage `web.status` and `response_time_ms` are now written into the enrichment record
  - `website_status` now uses `done/failed` rather than the earlier `completed` mismatch
  - non-2xx homepage fetches now persist a real `web.status` such as `dead` instead of collapsing into an unstructured stage failure
  - extracted email, phone, and person records now carry page-specific source attribution instead of coarse generic sources
- Expanded deterministic test coverage:
  - updated fixture assertions for the new source metadata and `done` status vocabulary
  - added redirect homepage coverage for `web.url_final` and `web.status`
  - added a dead-homepage case proving that Phase 2 persists `web.status='dead'` while the website stage remains structurally complete
- Re-ran verification successfully:
  - `python -B -m pytest -p no:cacheprovider tests\test_phase2_models.py tests\test_phase2_deterministic.py tests\test_database.py`
  - `python -B -m pytest -p no:cacheprovider tests`
- Checked the non-blocking London cap-hit probe again:
  - final observed status this session was `cells_completed=0`, `cells_failed=1`, `leads_found=0`
  - it did not produce cap-hit evidence, so `C6` remains open and non-blocking
- Improved live D2 evidence without overstating it:
  - direct external fetch to `https://www.gower-plumbing.co.uk/` succeeded
  - direct external fetch to `https://www.gower-plumbing.co.uk/contact` succeeded
  - the fetched live pages contained phone-like contact signals
  - however, a clean end-to-end captured `run_phase2(...)` live proof is still not strong enough in this shell environment to sign `D2` off

**Finish point for this session:** `D2` remains the active task. It now has stronger contract alignment, better test coverage, and live external reachability proof, but it is still not complete because the live end-to-end Phase 2 proof remains partial. `C6` also remains open, but only as non-blocking background verification.

---

## 2026-06-01 — Eighth implementation session: D2 website-stage resume and retry semantics completed

Continued from the D2 contract-alignment checkpoint and focused specifically on making the website stage behave like a real resumable pipeline stage rather than a best-effort batch loop.

- Used a subagent to audit the repo’s status-transition pattern so the main implementation could stay local and targeted:
  - the audit confirmed Phase 1 already has the intended `pending -> running -> terminal` checkpoint loop
  - it also confirmed the next useful D2 slice was website-stage reset/claim/retry behavior, not broader Phase 2 expansion
- Completed the next coherent D2 operational slice in code:
  - added `reset_running_website_leads(...)` coverage and wired `run_phase2(...)` to restart stranded website-stage rows cleanly from `pending`
  - added atomic `claim_next_pending_website_lead(...)` usage inside `run_phase2(...)` so website-stage work is explicitly claimed one row at a time as `running`
  - added `count_pending_website_leads(...)` so the Phase 2 result payload reports a real remaining backlog
  - added `retry_failed_website_leads(...)` so website-stage failures can be re-queued into `retry` rather than remaining terminal forever
- Expanded verification around the website-stage checkpoint model:
  - added database tests for resetting stranded `running` website rows
  - added database tests for atomic website-stage claiming and pending-count reporting
  - added database tests for `failed -> retry` re-queue behavior
  - added a Phase 2 runner test proving reset + single-claim batch behavior on resume
- Re-ran verification successfully:
  - `python -B -m pytest -p no:cacheprovider tests\test_database.py tests\test_phase2_deterministic.py tests\test_phase2_models.py`
  - `python -B -m pytest -p no:cacheprovider tests`

**Finish point for this session:** `D2` is still the active task. The website stage now has deterministic extraction, stronger schema alignment, page-specific sources, and proper reset/claim/retry semantics, all with green tests. `D2` is still not complete because the live end-to-end `run_phase2(...)` proof remains only partial. The exact next implementation action remains **`Track D — Task D2: deterministic website extraction`** through stronger live proof, then **`D3: AI fallback integration`**.

---

## 2026-06-01 — Fifth implementation session: live gosom path corrected and D1 schema layer completed

Continued from the C5 UI checkpoint with two goals: move the live Phase 1 proof forward using real gosom, and avoid dead time by implementing the first stable Phase 2 schema slice.

- Diagnosed the first live gosom failure through direct runtime probing:
  - Docker daemon access was unavailable in the sandbox but worked with elevated access
  - gosom image was not present locally and had to be pulled
  - the first live run failed because our client used the wrong REST payload shape
  - direct probing of gosom's local spec at `/static/spec/spec.yaml` exposed the real contract
- Corrected the gosom runtime integration:
  - submit payload changed from assumed `query/bbox` fields to `name`, `keywords`, `lat`, `lon`, `radius`, and `max_time`
  - gosom download parsing changed from assumed JSON to CSV parsing
  - added gosom client tests for bbox center/radius conversion and CSV result parsing
- Re-ran the live app-backed discovery path after restarting the FastAPI process:
  - the integrated coverage run now enters `running` state against real gosom instead of failing immediately
  - live `/ui/coverage-stats` shows `Running: 1`
  - live `/ui/pipeline-status` shows discovery `0 complete, 1 running`
  - live `/api/projects/{id}/cells` shows the real cell geometry with `status=running`
- Implemented **Track D1 — Enrichment record schema in code**:
  - replaced the Phase 2 stub with typed enrichment record models
  - added a builder that maps raw gosom lead data into the locked Phase 2 contract
  - added tests covering fixture-based record creation, Companies House match metadata, and rejection of invalid match methods

Verification completed for this session:

- `python -B -m pytest -p no:cacheprovider tests`
- direct gosom API submission works locally with corrected payload
- integrated app coverage run reaches live `running` state through gosom

Constraints still open after this session:

- `C6` is still not complete because live cap-hit subdivision has not yet been proven
- real completion and live lead ingestion are now proven, but only on a non-cap-hit sample

Additional live proof reached after the first log pass in this same checkpoint:

- a tiny live discovery sample completed through the real app path
- coverage status reached:
  - `cells_completed=1`
  - `cells_running=0`
  - `cells_failed=0`
  - `leads_found=20`
  - `coverage_complete=true`
- the completed cell persisted `result_count=20` and remained `cap_hit=false`
- a follow-up fix corrected job-id propagation from gosom into the Phase 1 runner for future observability
- a broader `builders` cap-hit probe across the Swansea-Llanelli-Neath-Port Talbot corridor did not finish inside the earlier local wait window
- direct gosom inspection showed the underlying job was still `working`, so the app-side timeout policy was increased to better match long-running dense probes

**Finish point for this session:** `C5` is complete. `D1` is complete. `C6` is partially verified with real completion and ingestion, but still open pending a live cap-hit subdivision proof. The exact next implementation action remains **`Track C — Task C6: Phase 1 verification`**, then **`Track D — Task D2: deterministic website extraction`**.

---

## 2026-06-01 — Third implementation session: Track C1-C4 completed

Continued from the Track B shell checkpoint and implemented the first real Phase 1 discovery path through the backend.

- Implemented **Track C1 — gosom REST client**:
  - added `submit_job`, `poll_job`, `download_results`, and `run_cell`
  - normalized bbox formatting for gosom REST job payloads
- Implemented **Track C2 — coverage cell model and queue logic**:
  - added bbox parsing and formatting helpers
  - added initial-cell creation, pending-cell claiming, running-cell reset, completion, and failure handling
  - added child-cell insertion for cap-hit subdivision
- Implemented **Track C3 — lead ingestion and dedup**:
  - persisted gosom download payloads under `data/jobs/`
  - inserted leads with downstream phase statuses initialized to `pending`
  - preserved `(project_id, cid)` dedup and recorded `first_seen_cell`
- Implemented **Track C4 — coverage endpoints**:
  - added `POST /api/projects/{id}/coverage/start`
  - added `GET /api/projects/{id}/coverage/status`
  - added `GET /api/projects/{id}/cells`
  - bound the map and pipeline views to live coverage summaries and the cell queue
- Added tests covering:
  - bbox parsing
  - running-cell reset
  - lead-ingest duplicate skipping
  - synthetic cap-hit subdivision flow
  - coverage status and GeoJSON API output

Verification completed for this session:

- `python -B -m pytest -p no:cacheprovider tests`
- `python -B -c "from main import app; print(app.title)"`

Constraints still open after this session:

- no live local gosom Docker run has been proven yet
- Phase 1 UI is not yet a full Leaflet coverage map with live redraws
- `git status` could not be used in this sandbox because Git rejected the workspace as an unsafe ownership boundary

**Finish point for this session:** `C1`, `C2`, `C3`, and `C4` complete. The exact next implementation action is **`Track C — Task C5: Phase 1 UI`**, followed by **`C6: Phase 1 verification`** and then **`Track D — Task D1: enrichment record schema in code`**.

---

## 2026-06-01 — Fourth implementation session: C5 UI implementation added, sign-off still pending live proof

Continued from the Track C backend checkpoint and built the first real Phase 1 UI surface rather than leaving discovery as a static placeholder.

- Implemented the first **Track C5 — Phase 1 UI** pass:
  - loaded Leaflet CSS/JS and the map script from the shell
  - replaced the static coverage summary with a real map layout in `ui_map`
  - added `Start Coverage` and `Refresh Map` controls for the discovery view
  - added `/ui/coverage-stats` as a polled sidebar fragment
  - added click-driven cell detail rendering for status, depth, result count, cap-hit, bbox, and gosom job id
  - added `/ui/pipeline-status` as a polled pipeline fragment for the discovery row
  - added completion percent and depth breakdown support to the coverage status model
- Added verification for the new UI surface:
  - API/UI test coverage for the map hooks and new partial endpoints
  - live HTTP smoke against the running FastAPI process showing:
    - `ui/map` renders the coverage map container and start control
    - `ui/coverage-stats` renders the sidebar fragment
    - `ui/pipeline-status` renders discovery progress output

Verification completed for this session:

- `python -B -m pytest -p no:cacheprovider tests`
- live server reachable at `http://127.0.0.1:3000/health`
- live UI smoke confirmed new fragment routes and map hooks render from the running app

Constraint still open after this session:

- `C5` is not signed off yet because there is still no real gosom-driven browser proof that map rectangles and coverage counts visibly change during a live coverage run

**Finish point for this session:** `C4` remains the last fully signed-off task. `C5` has been implemented but is still open pending live gosom/UI proof. The exact next implementation action remains **`Track C — Task C5: Phase 1 UI`** through live proof, then **`C6: Phase 1 verification`**.

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
