# Scraper Pro — Pipeline Master Document
*Synthesised May 2026 from phases/ source of truth. Supersedes all prior master documents.*

> **For individual phase specs see:** `phases/phase1-discovery.md` through `phases/phase5-lead-scoring.md`  
> **Archive folder:** `archive/` — outdated documents, do not read unless explicitly asked.

---

## Overview

A fully automated, free/open-source pipeline that:
1. Discovers local businesses in Swansea / South Wales from Google Maps
2. Enriches each lead with a rich multi-contact record (emails, phones, people, company financials)
3. Outputs a clean, outreach-ready spreadsheet

**Total cost: £0** — self-hosted tools, free APIs, local compute only.

**v1 scope** (this document):
- Phase 1: Discovery via gosom + adaptive quadtree
- Phase 2: Enrichment — deterministic website parse, AI fallback, WHOIS/MX, Companies House, SMTP verification
- Phase 3: Normalise, dedup, export `leads.xlsx`

**Deferred to v2:**
- Phase 4: Web & Presence Audit (placeholder designed, not built)
- Phase 5: Lead Scoring (placeholder designed, not built)
- Stage 2: Yell.com top-up (scraper chosen, merge logic defined, not built)

---

## Pipeline Architecture

```
[Phase 1] DISCOVERY
    gosom — adaptive quadtree coverage (no cap misses)
    Stage 2: Yell.com top-up — DEFERRED v2
              ↓
[Phase 2] ENRICHMENT
    Website parse — httpx[http2] + Selectolax + JSON-LD + regex
    AI fallback — direct Groq API when email, phone, or person name is missing
    WHOIS (python-whois) + MX check (dnspython)
    Companies House API — officers, PSC, financials
    SMTP email verification (dns-smtp-email-validator)
              ↓
[Phase 3] NORMALISE & DEDUP
    Phone normalise (libphonenumber) → deduplicate → leads.xlsx
              ↓
[Phase 4] WEB & PRESENCE AUDIT — DEFERRED v2
              ↓
[Phase 5] LEAD SCORING — DEFERRED v2
```

**Orchestration: FastAPI + SQLite** (no n8n — all logic in Python).

**Checkpoint/resume at every phase.** Each lead carries a status field per stage (`pending / running / done / failed`). Any run only processes `pending`. Interrupted runs reset `running` → `pending` on next start. This pattern is identical across all phases and stages.

**Canonical v1 rule:** deterministic extraction always runs first. AI fallback runs only if `email`, `phone`, or `person name` is still missing. AI may infer labels/roles, but may not invent facts. Any AI-recovered value must carry evidence as `snippet + page source label`.

---

## Phase 1 — Discovery

See full spec: `phases/phase1-discovery.md`

Discovers local businesses within a target area using Google Maps. The only geographic input is a bounding box drawn at project creation.

### gosom/google-maps-scraper

**Repo:** https://github.com/gosom/google-maps-scraper · **Licence:** MIT · **Cost:** Free

Runs headless Chromium against maps.google.com. No API key. Deduplicates by Google CID.

**We do NOT use gosom's own grid mode.** Our Python layer drives gosom per cell via its REST API.

#### Docker Run (REST API mode)

```bash
docker run -p 8080:8080 \
  -v $PWD/data:/data \
  gosom/google-maps-scraper \
  -web \
  -data-folder /data
```

#### Python Client

```python
import httpx, time

GOSOM_BASE = "http://localhost:8080/api/v1"

def run_gosom_cell(query, bbox):
    resp = httpx.post(f"{GOSOM_BASE}/jobs", json={
        "query": query,
        "bbox": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
        "zoom": 16, "depth": 1, "concurrency": 4,
        "email": True, "exit_on_inactivity": "3m"
    })
    job_id = resp.json()["id"]
    while True:
        status = httpx.get(f"{GOSOM_BASE}/jobs/{job_id}").json()["status"]
        if status == "complete": break
        elif status == "failed": return []
        time.sleep(5)
    return httpx.get(f"{GOSOM_BASE}/jobs/{job_id}/download").json()
```

### Adaptive Quadtree Coverage

Google Maps caps at 120 results per viewport. A fixed grid misses dense areas. Solution: business density drives cell size automatically.

**Rule:** if cell returns ≥ 120 results and is above minimum size → split into 4 quadrants and re-run. If < 120 → exhausted. **Coverage is complete when zero cells return 120.**

```python
def subdivide(minLat, minLon, maxLat, maxLon):
    midLat = (minLat + maxLat) / 2
    midLon = (minLon + maxLon) / 2
    return [
        (minLat, minLon, midLat, midLon),  # SW
        (minLat, midLon, midLat, maxLon),  # SE
        (midLat, minLon, maxLat, midLon),  # NW
        (midLat, midLon, maxLat, maxLon),  # NE
    ]

def run_coverage(project_id, initial_bbox, min_cell_degrees=0.005):
    queue = [initial_bbox]
    while queue:
        cell = queue.pop(0)
        results = run_gosom_cell(query, cell)
        save_results(project_id, cell, results)
        if len(results) >= 120 and cell_size(cell) > min_cell_degrees:
            queue.extend(subdivide(*cell))
```

**Minimum cell size:** `0.005°` ≈ 500 metres. Configurable per project.

**Swansea bounding box:** `51.5900,-4.0300,51.6700,-3.8900`

### Fields Extracted

| Field | Notes |
|---|---|
| title | Business name |
| phone | Public Google Maps phone |
| website | Website URL |
| address | Full address |
| latitude / longitude | GPS coords |
| cid | Google unique ID — dedup key |
| category | e.g. "Plumber" |
| rating / reviews_count | Social proof |
| emails | From website (via -email flag) |

### Known Bugs (May 2026)

`open_hours` (only Wednesday, #233), `user_reviews` empty (#234), `reviews_count` = 0 (#232). All minor — core fields unaffected.

### Stage 2 — Yell.com Top-Up (DEFERRED v2)

**Scraper:** `abdalrhman-abas-0/yell-scrper` · **Merge key:** normalised name + first 4 chars postcode · **Expected uplift:** +50–100 leads per niche. Plugs in without redesigning Phase 1.

---

## Phase 2 — Enrichment

See full spec: `phases/phase2-enrichment-design.md`

Extends each lead with a rich multi-contact record. Never discards data — organises it.

### Free Source Stack

| Source | What it gives | Method |
|---|---|---|
| **Companies House API** | Company number, status, SIC codes, incorporation date, officers (names/roles), PSC/beneficial owners (25%+ stake), financials (turnover band, net assets, employee count from filed accounts), charges, insolvency flags | Free API key, 600 req/min |
| **Postcodes.io** | Lat/lng, ward, local authority from postcode | REST, no auth |
| **httpx[http2] + Selectolax** | Live/dead check, HTTPS, final URL, homepage + contact page parse (emails, phones, person names, JSON-LD/Schema.org) | 2 pages max per lead. HTTP/2 enabled, CSS-selector parsing |
| **Groq API** | Fallback extraction from cleaned page content when deterministic extraction is incomplete | Direct API call, schema-constrained JSON output |
| **python-whois** | Domain owner/org, registration date, expiry, registrar | Python lib |
| **dnspython** | MX records — email domain validity | Python lib |
| **dns-smtp-email-validator** | SMTP handshake — confirms address exists at mail server | Python lib |
| **libphonenumber** | Phone format validation, type (mobile/landline) | Python lib |

### Website Checks — Lightweight Only

Two pages max per lead. Enrichment touches the website to complete the business record only.

| Check | Output |
|---|---|
| Live/dead | `status: live/dead/redirect/error` |
| HTTPS | `https: true/false` |
| Final URL after redirects | `url_final` — handed to Phase 4 web audit |
| Response time | `response_time_ms` |
| Homepage + contact page parse | Emails, phones, person names, JSON-LD added to contact arrays |
| WHOIS | `whois_owner`, `domain_expires` |
| MX records | Used for email validation |

Full crawl, tech stack, SEO, page speed → **Phase 4** (separate stage).

### AI Fallback Policy

- Deterministic parsing runs first on homepage and contact page content.
- AI fallback runs only if any of `email`, `phone`, or `person name` is missing.
- AI input = cleaned page content + selected metadata + deterministic partial results.
- AI may infer labels such as `owner`, `director`, `generic`, or `sales`, but may not invent names, emails, phones, or company facts.
- Any accepted AI-recovered field must include evidence: a short snippet plus a page source label such as `homepage`, `contact_page`, `json_ld`, `mailto_link`, or `footer`.

### Multi-Contact Model

A business has multiple legitimate contact points. Different sources give genuinely different — and both valid — data. We never discard; we organise.

```json
{
  "people": [
    {
      "name": "Robert Davies",
      "role_inferred": "director",
      "sources": ["companies_house"],
      "companies_house_role": "Director",
      "appointment_date": "2015-03-12",
      "resigned": false
    },
    {
      "name": "Bob Davies",
      "role_inferred": "owner",
      "sources": ["website_about_page"],
      "flag": "possible_same_person:Robert Davies"
    }
  ],
  "phones": [
    {
      "number": "+441792123456",
      "number_display": "01792 123456",
      "type": "landline",
      "role_inferred": "main_line",
      "sources": ["google_listing", "website_footer", "yell"],
      "source_count": 3,
      "validated": true,
      "primary": true
    }
  ],
  "emails": [
    {
      "address": "info@swanseaplumbing.co.uk",
      "role_inferred": "generic",
      "sources": ["website_footer"],
      "smtp_verified": true,
      "mx_valid": true,
      "primary": true
    },
    {
      "address": "bob@swanseaplumbing.co.uk",
      "role_inferred": "owner_direct",
      "sources": ["website_about_page"],
      "smtp_verified": true,
      "primary": false,
      "linked_person": "Bob Davies"
    }
  ]
}
```

### Role Inference Rules

Heuristics only — always stored as `role_inferred`, never treated as confirmed.

**Phone:** mobile from Companies House filing → `owner_mobile`; landline matching Google main → `main_line`; appears on 3+ sources → `main_line`.

**Email:** `info@`, `hello@`, `contact@` → `generic`; `quotes@`, `enquiries@` → `sales`; first name matches known director → `owner_direct`.

**Person:** Companies House Director → `director`; website About/founder → `owner`; Google owner response → `owner`.

### Source Weighting

Used to rank contacts for outreach — does not delete lower-ranked data.

| Source | Weight |
|---|---|
| Companies House | 0.95 |
| Own website | 0.85 |
| SMTP verified | +0.10 bonus |
| 3+ corroborating sources | +0.10 bonus |
| Google listing | 0.75 |
| Directory (Yell/192) | 0.60 |
| WHOIS | 0.50 (often outdated) |

Primary outreach contact = highest weighted email + highest weighted phone. All others retained.

### Potential Match Flags

When two items could be the same thing, flag — don't auto-merge.

- `possible_same_person` — e.g. "Robert Davies" (CH) + "Bob Davies" (website)
- `review_which_is_primary` — two mobiles both inferred as `owner_mobile`
- `domain_mismatch` — email domain ≠ website domain
- `address_discrepancy` — Companies House registered ≠ trading address (common, usually legitimate)

Flags stored in `review_flags` — visible to reviewer, don't block the record.

### Full Output Schema

```json
{
  "business_id": "uuid",
  "pipeline_version": "1.0",
  "scraped_at": "2026-05-31T09:00:00Z",
  "enriched_at": "2026-05-31T09:05:00Z",
  "enrichment_sources_used": ["companies_house", "postcodes_io", "website_parse", "whois", "smtp_probe"],

  "company": {
    "name_scraped": "Swansea Plumbing",
    "name_registered": "Swansea Plumbing Ltd",
    "name_trading": "Bob's Plumbing Services",
    "companies_house_number": "12345678",
    "companies_house_status": "active",
    "sic_codes": [{ "code": "43220", "description": "Plumbing, heat and air-conditioning installation" }],
    "incorporation_date": "2015-03-12",
    "accounts_overdue": false,
    "confirmation_statement_overdue": false,
    "finances": {
      "accounts_year_end": "2024-06-30",
      "accounts_type": "micro-entity",
      "turnover_band": "£100k–£250k",
      "net_assets": 42000,
      "total_assets": 68000,
      "total_liabilities": 26000,
      "cash_at_bank": 18500,
      "employee_count": 3,
      "employee_band": "1-9"
    },
    "charges": [],
    "insolvency": { "flag": false },
    "pscs": [{ "name": "Robert Davies", "nature_of_control": ["ownership-of-shares-75-to-100-percent"] }]
  },

  "addresses": [
    { "type": "trading", "source": "google_listing", "full": "14 Wind Street, Swansea, SA1 1DP",
      "postcode": "SA1 1DP", "lat": 51.6193, "lng": -3.9437, "local_authority": "City and County of Swansea" },
    { "type": "registered", "source": "companies_house", "full": "c/o Davies Accountants, 55 High Street, Swansea",
      "flag": "address_discrepancy" }
  ],

  "people": [ ... ],
  "phones": [ ... ],
  "emails": [ ... ],

  "web": {
    "url_final": "https://swanseaplumbing.co.uk",
    "status": "live",
    "https": true,
    "response_time_ms": 1840,
    "whois_owner": "Robert Davies / Swansea Plumbing Ltd",
    "domain_expires": "2026-11-02"
  },

  "social": {
    "google_place_id": "ChIJxxxxx",
    "google_rating": 4.3,
    "google_review_count": 27
  },

  "outreach": {
    "primary_email": "info@swanseaplumbing.co.uk",
    "primary_phone": "01792 123456",
    "primary_person": "Robert Davies",
    "ready": true,
    "review_flags": ["address_discrepancy", "possible_same_person:Robert Davies+Bob Davies"]
  }
}
```

---

## Phase 3 — Normalise & Dedup

See full spec: `phases/phase3-normalise-dedup.md`

Runs after Phase 2. Normalises phones to E.164, deduplicates by CID, exports `leads.xlsx`.

### Phone Normalisation

```python
import phonenumbers

def normalise_uk_phone(raw):
    try:
        parsed = phonenumbers.parse(raw, "GB")
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except:
        pass
    return raw  # return original if parse fails

# "01792 123456" → "+441792123456"
# "07911 123456" → "+447911123456"
```

Both `phone_raw` and `phone_e164` written to output — nothing discarded.

### Deduplication

**Primary key: Google CID.** Dedup happens at insert during Phase 1. Phase 3 confirms and catches any that slipped through. Never deduplicate on phone alone.

**Yell merge key** (name + first 4 chars postcode) defined and ready for v2.

### Output Schema (leads.xlsx)

| Field | Source | Notes |
|---|---|---|
| business_name | gosom | |
| category | gosom | e.g. "Plumber" |
| address | gosom | Full trading address |
| postcode | gosom (parsed) | |
| phone_raw | gosom | Original format |
| phone_e164 | Phase 3 | Normalised |
| website | gosom | |
| email | Phase 2 | Primary email from enrichment |
| email_confidence | Phase 2 | low / medium / high / very_high |
| owner_name | Phase 2 | From Companies House or website |
| company_number | Phase 2 | Companies House number |
| google_cid | gosom | Dedup key |
| source | pipeline | "gosom" (yell in v2) |
| scrape_date | pipeline | ISO date |

### Email Confidence Levels

| Level | Meaning |
|---|---|
| `low` | Syntax valid only |
| `medium` | Syntax + MX record found |
| `high` | Syntax + MX + SMTP handshake |
| `very_high` | SMTP 250 response confirmed |

---

## Phase 4 — Web & Presence Audit (DEFERRED v2)

See placeholder: `phases/phase4-web-presence-outline.md`

Runs after Phase 3 (clean, deduplicated lead list). Takes `web.url_final` as input. Produces a detailed web and online presence report for each business.

**Planned scope:** full site crawl (Scrapy), tech stack detection (Wappalyzer), page speed + Core Web Vitals (PageSpeed Insights API / Lighthouse CLI), SEO audit (title tags, meta, headings, keywords vs sector), mobile friendliness, HTTPS depth, broken links, social media audit, review analysis (using `social.google_place_id`), sector benchmarking via `company.sic_code`.

---

## Phase 5 — Lead Scoring (DEFERRED v2)

See placeholder: `phases/phase5-lead-scoring.md`

Runs after Phase 2 and before any future scoring-aware export extension. Assigns each lead a quality score (0–10).

**Planned scoring:**

| Signal | Points |
|---|---|
| Has website | +2 |
| Has email | +3 |
| Verified email (high confidence) | +1 bonus |
| Has owner name | +2 |
| Has phone | +1 |
| Rating ≥ 4.0 | +1 |

Score ≥ 7 = hot lead. When built, it extends the schema and export contract explicitly.

---

## Orchestration

**FastAPI + SQLite.** No n8n. All orchestration is Python — one codebase, debuggable, consistent checkpoint/resume.

```
UI trigger (or REST API call)
  → Phase 1: run_coverage(project) — quadtree cells → gosom jobs → leads saved to SQLite
  → Phase 2: for each lead where website_status = pending:
      → website parse (httpx[http2] + Selectolax + JSON-LD + regex)
      → if email, phone, or person name missing: AI fallback (direct Groq API)
      → WHOIS + MX check (python-whois + dnspython)
      → Companies House lookup (httpx)
      → SMTP email verification (dns-smtp-email-validator, 1 probe/sec hard limit + backoff)
      → write enrichment_data JSON blob → update indexed scalar columns
      → mark phase2_status = done
  → Phase 3: batch Postcodes.io bulk lookup (100/request) → normalise phones → dedup → export leads.xlsx
  → [Phase 4: web presence audit — deferred v2]
  → [Phase 5: lead scoring — deferred v2]
```

Each arrow is a resumable checkpoint.

---

## Master Control UI — Specification

### Purpose

A single self-hosted web app controlling the entire pipeline — discovery, enrichment, export. Organised around **Projects** (one per niche/search term). Operable by a human via browser and by an AI agent via REST API.

### Tech Stack

| Layer | Tool | Why |
|---|---|---|
| Backend | FastAPI (Python) | UI + REST API in one file, minimal RAM |
| Database | SQLite | Single file, zero setup |
| Map | Leaflet.js | Free, no API key, draws quadtree cells |
| Frontend | Jinja2 templates + HTMX + Alpine.js | Server-rendered fragments, minimal JS, no build step |

Total idle RAM: ~40–80MB. No external services. Status updates via polling (every 3s) + manual Refresh button.

### Core Concept: Projects

A **Project** is the top-level unit. Each has:
- A **primary search term** (e.g. "plumbers")
- Optional **secondary terms** (e.g. "drainage engineer") — deduplicated by CID
- A **target region** — one bounding box drawn at project creation (only geographic input ever needed)
- Its own isolated lead list, coverage cells, and pipeline state

Projects are completely separate — Plumbers leads never mix with Landscapers leads.

**Examples:** `plumbers-swansea`, `landscapers-swansea`, `roofers-south-wales`

### UI Layout

```
┌─────────────────────────────────────────────┐
│  SCRAPER PRO        [▶ Run] [⏹ Stop]  ●live │
├──────┬──────────────────────────────────────┤
│ nav  │                                      │
│      │           <main>                     │
│  Map │         (content area)               │
│      │                                      │
│  Pipeline                                   │
│      │                                      │
│  Leads                                      │
│      │                                      │
│  Scrapes                                    │
└──────┴──────────────────────────────────────┘
```

### Header Bar

- Project name
- `Run` / `Stop` control for the active project
- Live status dot, polled from the server

### Map Tab

Coverage map for the active project, with quadtree cells colour-coded by status.

**Cell rendering:**
- Fill opacity = result density for completed cells
- Colour = status: done / running / pending / failed
- Cell size varies naturally — large over sparse areas, small over dense areas

**Map controls:**
- Click any cell → tooltip: bounds, result count, depth, duration, whether subdivided
- Coverage stats sidebar
- Coverage complete indicator when zero cells returned 120 results

### Pipeline Tab

```
PROJECT: Plumbers — Swansea               [▶ Run All]  [↺ Refresh]

┌─────────────────────────────────────────────────────────────────┐
│  PHASE 1 — DISCOVERY                         [▶ Run]  [✓ Done] │
│  Coverage: 312 cells complete, 0 running, 0 queued              │
│  Cap hits subdivided: 47 cells split                            │
│  Coverage status: ✓ COMPLETE — no cells returned 120           │
│  Google Maps (gosom):  1,240 leads found                        │
│  Yell.com top-up:      [deferred — v2]                         │
├─────────────────────────────────────────────────────────────────┤
│  PHASE 2 — ENRICHMENT                        [▶ Run]  [~ Active]│
│  Stage 3 — Website parse:     847 / 1,240  ████████░░  68%     │
│  Stage 4 — WHOIS + MX:        901 / 1,240  ████████░░  73%     │
│  Stage 5 — Companies House:   701 / 1,240  █████░░░░░  57%     │
│  Stage 6 — SMTP verify:       776 / 1,240  ██████░░░░  63%     │
│                                                                  │
│  Email coverage so far: 776 / 1,240 (63%)                      │
│                        [Resume]  [Retry Failed (12)]            │
├─────────────────────────────────────────────────────────────────┤
│  PHASE 3 — NORMALISE & DEDUP                 [▶ Run]  [○ Ready]│
│  Phone normalise + deduplicate + export leads.xlsx              │
│  Last export: —                              [Export Now ↓]    │
├─────────────────────────────────────────────────────────────────┤
│  PHASE 4 — WEB & PRESENCE AUDIT             [deferred — v2]    │
├─────────────────────────────────────────────────────────────────┤
│  PHASE 5 — LEAD SCORING                     [deferred — v2]    │
└─────────────────────────────────────────────────────────────────┘

Icons:  ✓ complete   ~ running   ○ not started   ✗ has failures
```

**Controls:**
- **Run All** — runs Phase 1 → 2 → 3 in sequence; stops if a phase fails
- Each phase has its own **Run** button
- **Resume** — skips `done` leads, picks up `pending`, resets `running` → `pending`
- **Retry Failed (n)** — re-queues only `failed` leads for that stage
- **Refresh** — manual poll; auto-polls every 3s while any job active
- ⚙ per phase → settings: concurrency, rate limits, API keys, layers to enable

### Leads Tab

Filterable, sortable table for the active project.

**Columns:** Name | Category | Phone | Email | Email Confidence | Owner | Website | Phase Reached | Last Updated

**Filters:** Phase reached · Has email · Has owner name · Source

**Actions:**
- Click lead → detail panel: all fields, per-stage history
- Export all → `leads.xlsx`

---

## REST API

Every UI action has a corresponding endpoint. The agent drives the pipeline identically to a human.

### Projects

| Method | Endpoint | What it does |
|---|---|---|
| `GET` | `/api/projects` | List all projects with summary stats |
| `POST` | `/api/projects` | Create project (name, term, extra_terms, bbox) |
| `GET` | `/api/projects/{id}` | Full project state + per-stage counts |
| `DELETE` | `/api/projects/{id}` | Archive project |

### Coverage

| Method | Endpoint | What it does |
|---|---|---|
| `POST` | `/api/projects/{id}/coverage/start` | Start adaptive quadtree coverage run |
| `GET` | `/api/projects/{id}/coverage/status` | Cell counts, cap hits, completion flag |
| `GET` | `/api/projects/{id}/cells` | Quadtree cells for the active project as GeoJSON |

### Pipeline

| Method | Endpoint | What it does |
|---|---|---|
| `POST` | `/api/projects/{id}/run` | Run all phases in sequence |
| `POST` | `/api/projects/{id}/phases/{n}/run` | Run single phase (1, 2, or 3) |
| `POST` | `/api/projects/{id}/phases/{n}/resume` | Resume from checkpoint |
| `POST` | `/api/projects/{id}/phases/{n}/retry` | Retry failed leads only |
| `POST` | `/api/projects/{id}/stop` | Stop the active run for the project |
| `GET` | `/api/projects/{id}/pipeline/status` | Full per-stage status + counts |

### Leads

| Method | Endpoint | What it does |
|---|---|---|
| `GET` | `/api/projects/{id}/leads` | Paginated + filterable lead list |
| `GET` | `/api/projects/{id}/leads/export` | Download leads.xlsx |
| `GET` | `/api/stats` | Global stats across all projects |

### Agent Autonomous Loop

```
POST /api/projects/{id}/coverage/start
→ poll /api/projects/{id}/coverage/status until coverage_complete: true
→ POST /api/projects/{id}/phases/2/run
→ poll /api/projects/{id}/pipeline/status until phase2 complete
→ POST /api/projects/{id}/phases/3/run
→ GET /api/projects/{id}/leads/export
```

---

## SQLite Schema

```sql
-- Projects
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    name TEXT,
    primary_term TEXT,
    extra_terms TEXT,          -- JSON array of secondary search terms
    bbox TEXT,                 -- "minLat,minLon,maxLat,maxLon"
    colour TEXT,               -- hex colour for map display
    min_cell_degrees REAL DEFAULT 0.005,
    created_at TEXT,
    archived INTEGER DEFAULT 0
);

-- Quadtree coverage cells (scoped to project)
CREATE TABLE cells (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    bbox TEXT,                 -- "minLat,minLon,maxLat,maxLon"
    depth INTEGER DEFAULT 0,   -- subdivision depth (0 = original bbox)
    status TEXT,               -- pending/running/completed/failed
    result_count INTEGER,
    cap_hit INTEGER DEFAULT 0, -- 1 if result_count >= 120 (was subdivided)
    gosom_job_id TEXT,
    created_at TEXT,
    completed_at TEXT
);

-- Leads (scoped to project)
CREATE TABLE leads (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    cid TEXT,                       -- Google CID — dedup key within project
    raw_data TEXT,                  -- raw JSON blob from gosom (Phase 1 output)
    enrichment_data TEXT,           -- full Phase 2 JSON record (set after enrichment)
    enrichment_version TEXT,
    source TEXT DEFAULT 'gosom',
    -- Checkpoint statuses per enrichment stage
    website_status TEXT DEFAULT 'pending',          -- deterministic website parse
    ai_fallback_status TEXT DEFAULT 'pending',      -- only used when deterministic extraction is incomplete
    whois_mx_status TEXT DEFAULT 'pending',         -- WHOIS + MX check
    companies_house_status TEXT DEFAULT 'pending',  -- Companies House API
    smtp_status TEXT DEFAULT 'pending',             -- SMTP email verification
    output_status TEXT DEFAULT 'pending',           -- normalise + dedup + export
    -- Indexed scalars extracted from enrichment_data for fast filtering/export
    primary_email TEXT,
    primary_phone TEXT,
    primary_person TEXT,
    outreach_ready INTEGER DEFAULT 0,
    -- score REAL,                   -- deferred: added in Phase 5 (v2)
    first_seen_cell TEXT,
    last_updated TEXT
);

-- Pipeline run log
CREATE TABLE pipeline_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    phase INTEGER,
    stage INTEGER,
    status TEXT,               -- running/completed/failed
    records_total INTEGER,
    records_done INTEGER,
    records_failed INTEGER,
    started_at TEXT,
    completed_at TEXT
);
```

**Schema notes:**
- `raw_data` = gosom JSON blob (Phase 1). `enrichment_data` = full Phase 2 multi-contact JSON record.
- Indexed scalars (`primary_email`, `primary_phone`, `primary_person`, `outreach_ready`) are extracted from `enrichment_data.outreach` after Phase 2 — used for fast SQL filtering and Phase 3 export without parsing the blob every row.
- No score column exists in v1. Scoring is added only when Phase 5 is built.

---

## File Structure

```
scraper-ui/
├── main.py                   # FastAPI — all routes (~300 lines)
├── database.py               # SQLite helpers + schema creation
├── gosom_client.py           # gosom REST API wrapper
├── coverage.py               # subdivide() + cell_size() + run_coverage()
├── pipeline/
│   ├── phase1_discovery.py   # quadtree runner (Yell top-up deferred v2)
│   ├── phase2_enrichment.py  # stages 3–6 with checkpoint loop, produces Phase 2 JSON
│   └── phase3_output.py      # normalise + deduplicate + export (scoring deferred v2)
├── static/
│   ├── index.html            # single page UI shell + layout
│   ├── map.js                # Leaflet — quadtree cells, project colours
│   ├── pipeline.js           # pipeline tab — progress bars, run buttons
│   ├── leads.js              # leads table, filters, export
│   └── app.js                # project switching, polling loop, header
├── data/
│   ├── scraper.db
│   └── jobs/                 # raw JSON per gosom job
└── requirements.txt
```

Phase 3 (web presence) and Phase 5 (lead scoring) files deliberately omitted — separate builds.

---

## Tech Stack Summary

| Component | Tool | Cost | Status |
|---|---|---|---|
| Discovery | gosom/google-maps-scraper | Free | Validated |
| Directory top-up (Yell) | abdalrhman-abas-0/yell-scrper | Free | **Deferred v2** |
| Website parse | httpx[http2] + Selectolax + JSON-LD + regex | Free | Specified |
| AI fallback | Groq API (direct) | Free tier | Specified |
| WHOIS | python-whois | Free | Specified |
| MX check | dnspython | Free | Specified |
| SMTP verification | dns-smtp-email-validator | Free | Specified |
| Companies House | Official UK Gov API | Free | Validated |
| Phone normalisation | phonenumbers (libphonenumber) | Free | Validated |
| Orchestration | FastAPI + SQLite | Free | Specified |
| Output | openpyxl → leads.xlsx | Free | Specified |
| OSINT expansion | theHarvester | Free | **Deferred v2 / test build** |
| Web audit | Scrapy + Wappalyzer + Lighthouse | Free | **Deferred v2** |
| Lead scoring | Custom Python | Free | **Deferred v2 (Phase 5)** |

---

## Open Gaps

| Gap | Status | Workaround |
|---|---|---|
| Yell.com top-up | Deferred v2. Scraper chosen, merge logic defined. | gosom-only in v1 |
| 192.com scraping | No free OSS scraper. Apify only (paid). | Skip |
| Facebook bulk scrape | kevinzg/facebook-scraper stale. Contact needs login. | Manual only for specific targets |
| LinkedIn enrichment | ToS risk, no safe free solution | Out of scope |
| Phase 3 web audit | Deferred v2 — design placeholder in phases/ | Not in v1 export |
| Phase 5 lead scoring | Deferred v2 — scoring approach defined | No score in v1 export |
| Companies House — sole traders | Only covers Ltd companies. ~40–60% hit rate for local tradespeople. | Leave owner blank for misses |

---

## Running It

```bash
# Install dependencies
pip install fastapi uvicorn "httpx[http2]" phonenumbers openpyxl \
            selectolax python-whois dnspython dns-smtp-email-validator groq

# Start the UI + API
python main.py
# Opens at http://localhost:3000

# Start gosom in REST API mode (separate terminal)
docker run -p 8080:8080 \
  -v $PWD/data:/data \
  gosom/google-maps-scraper \
  -web \
  -data-folder /data
```

**Prerequisites:** Docker (for gosom) · Python 3.10+ · Companies House API key (free, register at developer.company-information.service.gov.uk) · Groq API key for AI fallback

---

*Canonical v1 implementation contract: FastAPI + SQLite backend, Jinja2 + HTMX + Alpine.js UI, project-scoped `/api/projects/*` REST API, and the SQLite schema in this document.*  
*Source of truth for individual phase specs: `phases/` folder*  
*Outdated prior documents: `archive/` — do not read unless explicitly asked*
