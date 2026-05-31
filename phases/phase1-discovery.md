# Phase 1 — Discovery

Discovers local businesses within a target area using Google Maps and outputs a deduplicated lead list. The only geographic input is a single bounding box drawn at project creation.

---

## How It Works

```
[Draw bounding box] → [Adaptive quadtree coverage] → [gosom jobs per cell] → [Leads in SQLite]
```

Our Python layer drives gosom against individual cells via its REST API and handles all coverage logic. gosom itself is stateless — it receives one cell per job and returns results.

**We do NOT use gosom's own grid mode.** All subdivision is handled in our code.

---

## Stage 1: gosom/google-maps-scraper

**Repo:** https://github.com/gosom/google-maps-scraper  
**Licence:** MIT · **Run via:** Docker · **Cost:** Free

gosom runs headless Chromium against maps.google.com. No API key required. Deduplicates results by Google CID.

### Docker Run (gosom in REST API mode)

Start gosom once — it stays running and accepts jobs:

```bash
docker run -p 8080:8080 \
  -v $PWD/data:/data \
  gosom/google-maps-scraper \
  -web \
  -data-folder /data
```

The `-web` flag exposes a REST API at `localhost:8080`. Our Python layer calls this for every cell.

### How Our Python Layer Calls gosom

Three calls per cell:

```python
import httpx, time

GOSOM_BASE = "http://localhost:8080/api/v1"

def run_gosom_cell(query, bbox):
    """Submit one cell job and return results list."""
    # 1. Submit job
    resp = httpx.post(f"{GOSOM_BASE}/jobs", json={
        "query": query,
        "bbox": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
        "zoom": 16,
        "depth": 1,
        "concurrency": 4,
        "email": True,
        "exit_on_inactivity": "3m"
    })
    job_id = resp.json()["id"]

    # 2. Poll until complete
    while True:
        status = httpx.get(f"{GOSOM_BASE}/jobs/{job_id}").json()["status"]
        if status == "complete":
            break
        elif status == "failed":
            return []
        time.sleep(5)

    # 3. Download results
    results = httpx.get(f"{GOSOM_BASE}/jobs/{job_id}/download").json()
    return results
```

### queries.txt (one query per run)

```
plumbers in Swansea
electricians in Swansea
roofers in Swansea
builders in Swansea
decorators in Swansea
```

One niche per project. Secondary terms (e.g. "drainage engineer", "emergency plumber") are deduplicated by CID within the project.

---

## Adaptive Quadtree Coverage

Google Maps caps results at 120 per viewport. A fixed grid wastes time on empty countryside and can still miss dense city-centre areas. The solution: let business density drive cell size automatically.

**The rule:** if a cell returns ≥ 120 results and is above the minimum size, split into 4 quadrants and re-run each. If a cell returns < 120, it's exhausted — move on.

**Coverage is objectively complete** when zero cells return 120 results.

### Algorithm

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
    queue = [initial_bbox]                  # start with the full target area
    while queue:
        cell = queue.pop(0)
        results = run_gosom_cell(query, cell)
        save_results(project_id, cell, results)
        if len(results) >= 120 and cell_size(cell) > min_cell_degrees:
            queue.extend(subdivide(*cell))  # hit the cap → split into 4
        # if < 120, this cell is exhausted — done

def cell_size(bbox):
    minLat, minLon, maxLat, maxLon = bbox
    return min(maxLat - minLat, maxLon - minLon)
```

**Minimum cell size:** `0.005` degrees ≈ 500 metres. Prevents infinite subdivision. Configurable per project.

**What this looks like in practice:**
- Large cells over countryside and industrial estates — fast
- Small cells over city centre and retail strips — thorough
- The Leaflet map shows the quadtree visually as it runs

### Swansea Initial Bounding Box

```
51.5900,-4.0300,51.6700,-3.8900
```

---

## Checkpoint / Resume

Every cell carries a status field. If coverage is interrupted, it resumes from remaining cells on next start.

**Cell statuses:** `pending → running → completed / failed`

On startup, any cells in `running` state are reset to `pending` — nothing is assumed complete unless `completed_at` is set.

---

## Fields Extracted

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

| Bug | GitHub issue | Impact |
|---|---|---|
| `open_hours` only returns Wednesday | #233 | Minor — not used in v1 |
| `user_reviews` empty | #234 | Minor — not used in v1 |
| `reviews_count` returns 0 | #232 | Minor — not used in v1 |

Core lead fields (name, phone, website, address, CID) are unaffected.

### Performance

~120 places/minute at `-c 8`. Full Swansea multi-niche run: ~40–90 minutes. `-c 4` is safer without proxies.

---

## Stage 2: Yell.com Top-Up — DEFERRED to v2

Research done, scraper chosen, merge logic defined.

**Scraper:** `abdalrhman-abas-0/yell-scrper` — handles bot detection, pauses for manual CAPTCHA. Gets name, phone, website, address.

**Merge key:** normalised business name + first 4 chars of postcode (not phone — businesses can have multiple numbers). CID unavailable from Yell.

**Expected uplift:** +50–100 leads per niche — tradespeople with Yell presence but no Google Maps listing.

Plugs into the existing pipeline in v2 without redesigning Phase 1.

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
    result_count INTEGER,      -- results returned by gosom for this cell
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
    website_status TEXT DEFAULT 'pending',
    ai_fallback_status TEXT DEFAULT 'pending',
    whois_mx_status TEXT DEFAULT 'pending',
    companies_house_status TEXT DEFAULT 'pending',
    smtp_status TEXT DEFAULT 'pending',
    output_status TEXT DEFAULT 'pending',
    primary_email TEXT,
    primary_phone TEXT,
    primary_person TEXT,
    outreach_ready INTEGER DEFAULT 0,
    first_seen_cell TEXT,
    last_updated TEXT
);
```

Leads are deduplicated by `cid` within a project at insert time — if a CID already exists for the project, the new result is skipped.

---

## REST API Endpoints (Phase 1)

| Method | Endpoint | What it does |
|---|---|---|
| `POST` | `/api/projects` | Create project (name, primary_term, extra_terms, bbox) |
| `GET` | `/api/projects/{id}` | Full project state + per-stage counts |
| `POST` | `/api/projects/{id}/coverage/start` | Start adaptive quadtree coverage run |
| `GET` | `/api/projects/{id}/coverage/status` | Cell counts, cap hits, completion flag |
| `GET` | `/api/projects/{id}/cells` | Quadtree cells for the active project as GeoJSON (for Leaflet) |

Coverage status response example:

```json
{
  "cells_completed": 312,
  "cells_running": 0,
  "cells_queued": 0,
  "cells_failed": 2,
  "cap_hits": 47,
  "coverage_complete": true,
  "leads_found": 1240
}
```

`coverage_complete: true` means zero cells returned 120 results — objectively exhausted.

---

## File Structure

```
scraper-ui/
├── pipeline/
│   └── phase1_discovery.py  # quadtree runner + gosom REST API calls
├── coverage.py              # subdivide() + cell_size() + run_coverage()
├── gosom_client.py          # submit_job(), poll_job(), download_results()
└── database.py              # save_cell(), save_lead(), upsert_by_cid()
```

---

## Output

A list of unique leads in SQLite (`leads` table), scoped to the project, with `raw_data` populated and all enrichment status fields set to `pending` — ready for Phase 2.

---

## What Comes Next

Phase 2 (Enrichment) picks up every lead where `website_status = pending` and runs the enrichment stack: deterministic website extraction → optional Groq fallback → WHOIS + MX → Companies House → SMTP verification.
