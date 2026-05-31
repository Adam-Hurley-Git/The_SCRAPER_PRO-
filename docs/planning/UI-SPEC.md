# Scraper Pro — UI Specification
*Pipeline Monitor · HTMX + Alpine.js · May 2026*

> This document owns the UI. `docs/planning/PIPELINE-MASTER.md` owns the pipeline logic.  
> Every screen here maps to a FastAPI endpoint. No screen owns state — the server does.

---

## Philosophy

**One principle: the UI is a window into the database, not a framework.**

- No build step. No npm. No bundler. FastAPI serves one HTML shell plus server-rendered fragments.
- HTMX pulls server-rendered HTML fragments. Alpine.js handles micro-interactions only.
- CSS: custom properties + one micro-framework (`Pico.css` — 10KB, semantic HTML, zero class soup).
- Total page weight target: **< 80KB** (excluding map tiles).
- The map is the hero. Everything else is detail.

---

## Stack

| Layer | Choice | Why |
|---|---|---|
| Markup / interactivity | **HTMX 2.x** | Server pushes HTML; no JSON parsing, no state management |
| Micro-interactions | **Alpine.js 3.x** | Dropdowns, toggles, inline expand — < 15KB |
| Styling | **Pico.css** + CSS custom properties | Semantic, dark-mode-ready, no utility class spam |
| Map | **Leaflet.js** (CDN) | 42KB, battle-tested, draws quadtree rectangles perfectly |
| Backend (existing) | **FastAPI** | Serves both data AND HTML fragments via Jinja2 templates |
| DB (existing) | **SQLite** | All state lives here |

All loaded from CDN. Zero local installs.

---

## Views & Navigation

Single HTML shell. Navigation swaps the `<main>` content area via HTMX `hx-push-url`. No page reloads.

```
┌─────────────────────────────────────────────┐
│  SCRAPER PRO        [▶ Run] [⏹ Stop]  ●live │  ← Top bar
├──────┬──────────────────────────────────────┤
│ nav  │                                      │
│      │           <main>                     │
│  📍  │         (content area)               │
│  Map │                                      │
│      │                                      │
│  📊  │                                      │
│  Pipeline                                   │
│      │                                      │
│  👥  │                                      │
│  Leads                                      │
│      │                                      │
│  🔍  │                                      │
│  Scrapes                                    │
└──────┴──────────────────────────────────────┘
```

**Nav items** (`hx-get`, `hx-target="#main"`, `hx-push-url`):
- `/ui/map` — Coverage Map (default landing)
- `/ui/pipeline` — Pipeline Dashboard
- `/ui/leads` — Leads List
- `/ui/scrapes` — Raw Scrapes

**Top bar** (always visible):
- Project name
- **▶ Run** / **⏹ Stop** button (Alpine toggle, posts to `/api/projects/{id}/run` or `/api/projects/{id}/stop`)
- Live indicator dot — green/amber/red, polled every 5s via `hx-trigger="every 5s"` from `/ui/status-dot`

---

## View 1 — Coverage Map

**Purpose:** See exactly where the quadtree has searched, what's pending, and where density is highest.

### Layout

```
┌─────────────────────────────────────┬───────────────┐
│                                     │  Coverage     │
│         Leaflet map                 │  ──────────── │
│         (fills ~70% viewport)       │  ✅ Done: 142  │
│                                     │  🔄 Running: 3 │
│  Cells colour-coded:                │  ⏳ Pending: 28│
│  🟩 done (opacity = result density) │  ❌ Failed: 1  │
│  🟦 running                         │  ──────────── │
│  ⬜ pending                         │  Total leads  │
│  🟥 failed                          │  2,847        │
│                                     │               │
│  [click cell → cell detail popover] │  Depth stats  │
│                                     │  L1: 4 cells  │
│                                     │  L2: 16       │
│                                     │  L3: 122      │
└─────────────────────────────────────┴───────────────┘
```

### HTMX Behaviour

```html
<!-- Map itself: Leaflet renders once. Cell data refreshes via polling -->
<div id="map" ...></div>
<div id="coverage-stats"
     hx-get="/ui/coverage-stats"
     hx-trigger="every 5s"
     hx-swap="innerHTML">
```

The FastAPI `/ui/coverage-stats` endpoint returns a small HTML fragment (cell counts). The map cells update via a lightweight JS function called from HTMX's `htmx:afterSwap` event — it re-fetches `/api/projects/{id}/cells` (GeoJSON) and redraws only changed rectangles.

### Cell Popover (on click)

Leaflet `onClick` → Alpine `$store.map.selectedCell = id` → small panel slides in from the right (CSS transition, no JS animation library):

```
Cell SW-43 | Status: done
────────────────────────
Bounds: 51.590–51.595, -3.940–-3.933
Results: 38 businesses
Depth: L3 (quadrant of L2-11)
Duration: 14s
Split from: L2-11 (returned 120)
```

---

## View 2 — Pipeline Dashboard

**Purpose:** Understand where the pipeline is right now. Every phase. Every stage. No ambiguity.

### Layout

```
PIPELINE STATUS
────────────────────────────────────────────────

[Phase 1 — Discovery          ] [████████░░] 82%   ● running
  Stage 1: gosom scraping         2,847 / 3,450 leads
  Stage 2: Yell top-up            DEFERRED v2

[Phase 2 — Enrichment         ] [████░░░░░░] 41%   ● running
  Stage 3: Website parse          1,201 done  │  84 failed  │  1,562 pending
  Stage 4: WHOIS + MX             1,101 done  │  12 failed  │  1,734 pending
  Stage 5: Companies House         842 done   │   6 failed  │  1,999 pending
  Stage 6: SMTP verification       611 done   │  44 failed  │  2,192 pending

[Phase 3 — Normalise & Dedup  ] [░░░░░░░░░░]  0%   ○ not started

[Phase 4 — Web Audit          ] DEFERRED v2
[Phase 5 — Lead Scoring       ] DEFERRED v2

────────────────────────────────────────────────
THROUGHPUT (last 60s)
  Discovery:   42 leads/min
  Enrichment:  18 leads/min
  
QUEUE HEALTH
  Failed items needing review: 85   [View →]
  Stalled (running > 10min):    2   [View →]
```

### HTMX Behaviour

The entire phase section polls:

```html
<section id="pipeline-status"
         hx-get="/ui/pipeline-status"
         hx-trigger="every 3s"
         hx-swap="innerHTML">
```

FastAPI renders the Jinja2 template with live DB counts. No JS. The browser just swaps the fragment.

Progress bars are pure CSS: `<progress value="82" max="100">` — Pico.css styles these beautifully out of the box.

**Throughput** is a separate fragment polled every 10s — it queries the DB for records updated in the last 60s.

### Failed Items Drill-Down

`[View →]` links push to `/ui/leads?filter=failed&phase=enrichment` — the leads list pre-filtered.

---

## View 3 — Leads List

**Purpose:** Browse, filter, and inspect every enriched lead. The end product.

### Layout

```
LEADS                                  [ 🔍 Search... ]  [Filters ▾]  Export XLSX

Filters (Alpine collapse, no page reload):
  Phase:     [All ▾]   Status: [All ▾]   Has email: [○ Any ●Yes ○No]
  Has CH:    [○ Any ●Yes ○No]            Category:  [All ▾]
  Review flags: [○ Any ○Has flags]

────────────────────────────────────────────────────────────────────────────────
  Business               Category      Email          Phone         Status
  ─────────────────────────────────────────────────────────────────────────────
  Swansea Plumbing Ltd   Plumber       info@swans…  01792 123456   ✅ done
  Davies Electricals     Electrician   —            07700 900123   🔄 enrich
  Bay Builders           Builder       quotes@bay…  01792 456789   ✅ done
  …
────────────────────────────────────────────────────────────────────────────────
                                                   Showing 1–50 of 2,847  [Next →]
```

### HTMX Behaviour

Search and filters are a `<form>` with `hx-get="/ui/leads"` and `hx-trigger="input delay:300ms, change"`. No submit button needed. The table body swaps on every filter change with a 300ms debounce.

Pagination via `[Next →]`: `hx-get="/ui/leads?page=2&{current_filters}"` swaps the table body only.

Status badges are coloured via CSS custom properties — no inline styles:
- `data-status="done"` → green
- `data-status="enriching"` → amber  
- `data-status="failed"` → red
- `data-status="pending"` → muted

### Lead Detail Panel

Click any row → `hx-get="/ui/lead/{{business_id}}"` → panel slides in from the right (`hx-target="#detail-panel"`, CSS `transform: translateX`).

```
┌─────────────────────────────────────────────────────────────┐
│ Swansea Plumbing Ltd                    ✅ Enriched          │
│ Plumber · SA1 1DP · incorporated 2015                       │
├─────────────────────────────────────────────────────────────┤
│ CONTACTS                                                     │
│                                                              │
│ 📧 info@swanseaplumbing.co.uk    [primary]  ✅ SMTP verified │
│    generic · website_footer                                  │
│ 📧 bob@swanseaplumbing.co.uk     [direct]   ✅ SMTP verified │
│    owner_direct · linked: Bob Davies                        │
│                                                              │
│ 📞 01792 123456   [primary]  landline · 3 sources           │
│ 📞 07700 900123              mobile · owner_mobile · 1 src  │
│                                                              │
│ 👤 Robert Davies   Director  (Companies House)              │
│ 👤 Bob Davies      Owner     (website about page)           │
│    ⚠ possible_same_person: Robert Davies                    │
├─────────────────────────────────────────────────────────────┤
│ COMPANY                                                      │
│ CH: 12345678 · active · SIC 43220                           │
│ Turnover: £100k–£250k · Employees: 1–9 · Assets: £42k      │
│ Accounts: up to date · No charges · No insolvency           │
├─────────────────────────────────────────────────────────────┤
│ WEB                                                          │
│ https://swanseaplumbing.co.uk  ✅ live  1,840ms             │
│ Domain expires: 2026-11-02 · Owner: Robert Davies           │
├─────────────────────────────────────────────────────────────┤
│ REVIEW FLAGS                                                 │
│ ⚠ possible_same_person — Robert Davies / Bob Davies         │
│                                                              │
│ [Copy primary email]  [Copy primary phone]  [Mark reviewed] │
└─────────────────────────────────────────────────────────────┘
```

Alpine handles the copy-to-clipboard buttons (one line each). Everything else is server-rendered HTML.

---

## View 4 — Raw Scrapes

**Purpose:** Inspect the raw gosom output before enrichment. Useful for debugging discovery.

### Layout

Similar to Leads List but simpler — just the raw fields from Phase 1:

```
RAW SCRAPES                                         [ 🔍 Search... ]  [Filters ▾]

Filters: Category [All ▾]  Has website [○Any ●Yes ○No]  Rating [≥ ▾]

────────────────────────────────────────────────
  Business          Cat        Rating  Website    CID         Enriched?
  ────────────────────────────────────────────────────────────────────
  Swansea Plumbing  Plumber    4.8★    ✅          10293847   ✅ done
  Bay Café          Café       4.2★    ✅          10293912   🔄 pending
  …
```

Same HTMX filter + search pattern as Leads List.

---

## FastAPI Endpoints (UI contract)

These return **HTML fragments** (Jinja2), not JSON. Separates UI from data API cleanly.

| Endpoint | Returns | Polling? |
|---|---|---|
| `GET /ui/map` | Full map view shell | — |
| `GET /api/projects/{id}/cells` | GeoJSON of quadtree cells for the active project | Yes, 5s (by JS) |
| `GET /ui/coverage-stats` | HTML fragment: cell count table | Yes, 5s |
| `GET /ui/pipeline` | Full pipeline view | — |
| `GET /ui/pipeline-status` | HTML fragment: all phase rows | Yes, 3s |
| `GET /ui/leads` | Full leads view or table body fragment | — |
| `GET /ui/lead/{id}` | Detail panel HTML | On click |
| `GET /ui/scrapes` | Full scrapes view | — |
| `GET /ui/status-dot` | `<span data-status="running">` | Yes, 5s |
| `POST /api/projects/{id}/run` | 200 OK | On button click |
| `POST /api/projects/{id}/stop` | 200 OK | On button click |
| `GET /api/projects/{id}/leads/export` | XLSX file download | On click |

**JSON API** (for Leaflet, Alpine, clipboard) lives at `/api/*` and is separate from `/ui/*`.

---

## CSS Architecture

No utility classes. Semantic HTML + custom properties.

```css
/* tokens — defined in :root, override for dark mode */
:root {
  --color-bg:        #0f1117;
  --color-surface:   #1a1d26;
  --color-border:    #2a2d3a;
  --color-text:      #e2e4ee;
  --color-muted:     #7a7f9a;
  --color-accent:    #4f8ef7;   /* running / primary */
  --color-success:   #34c97a;   /* done */
  --color-warning:   #f5a623;   /* pending / review */
  --color-danger:    #e05151;   /* failed */
  --radius:          6px;
  --font-mono:       "JetBrains Mono", "Fira Mono", monospace;
}

/* status badges — data-attribute driven, no class per status */
[data-status]::before { display: inline-block; width: 8px; height: 8px; 
                          border-radius: 50%; margin-right: 6px; content: ""; }
[data-status="done"]      { color: var(--color-success); }
[data-status="done"]::before { background: var(--color-success); }
[data-status="running"]   { color: var(--color-accent); }
[data-status="failed"]    { color: var(--color-danger); }
[data-status="pending"]   { color: var(--color-muted); }
```

Pico.css provides: form elements, tables, `<progress>`, `<dialog>`, typography. We override its colour tokens to match above.

Map cells use inline `fillColor` from Leaflet (the only justified inline style — it's dynamic data, not design).

---

## File Structure

```
scraper-ui/
├── main.py
├── database.py
├── pipeline/
│   ├── phase1_discovery.py
│   ├── phase2_enrichment.py
│   └── phase3_output.py
├── templates/
│   ├── shell.html
│   ├── map.html
│   ├── pipeline.html
│   ├── pipeline_status.html
│   ├── leads.html
│   ├── lead_detail.html
│   ├── scrapes.html
│   └── coverage_stats.html
└── static/
    ├── app.css
    └── map.js
```

**Total custom JS: ~80 lines.** Everything else is HTMX attributes in the HTML.

---

## Interaction Patterns (reference)

### Polling fragment

```html
<div hx-get="/ui/pipeline-status"
     hx-trigger="every 3s"
     hx-swap="innerHTML"
     hx-indicator="#spinner">
  <!-- server renders here -->
</div>
```

### Filtered table (live search)

```html
<form hx-get="/ui/leads"
      hx-target="#leads-tbody"
      hx-trigger="input delay:300ms from:#search, change from:.filter-control"
      hx-push-url="true">
  <input id="search" name="q" type="search" placeholder="Search…">
  <select class="filter-control" name="status">…</select>
</form>
<table><tbody id="leads-tbody">…</tbody></table>
```

### Detail panel slide-in

```html
<!-- In the leads row -->
<tr hx-get="/ui/lead/{{id}}"
    hx-target="#detail-panel"
    hx-swap="innerHTML"
    hx-on::after-request="document.getElementById('detail-panel').classList.add('open')">

<!-- In the shell -->
<aside id="detail-panel"><!-- content injected here --></aside>
```

```css
#detail-panel {
  transform: translateX(100%);
  transition: transform 0.2s ease;
}
#detail-panel.open {
  transform: translateX(0);
}
```

### Run / Stop button

```html
<button x-data="{ running: false }"
        @click="running = !running"
        :hx-post="running ? '/api/projects/' + projectId + '/stop' : '/api/projects/' + projectId + '/run'"
        hx-swap="none">
  <span x-text="running ? '⏹ Stop' : '▶ Run'"></span>
</button>
```

---

## Performance Notes

- **Polling is staggered** — coverage (5s), pipeline (3s), status dot (5s) are offset so they don't all fire together.
- **No websockets needed for v1** — polling at 3–5s intervals is imperceptible to a human watching progress, costs ~200 bytes per fragment, and has no persistent connection overhead.
- **Map JS runs only on the map view** — loaded via `hx-on::load` attribute on the map container, not globally.
- **Export** triggers a direct `<a href="/api/projects/{id}/leads/export" download>` — no JS, no fetch, no blob.
- **SQLite query budget**: every polling endpoint should run in < 5ms. Use `COUNT(*) WHERE status = ?` with an index on `(status, phase)`. No JOINs in polling endpoints.

---

## Build Order

1. **Shell + nav** — static `shell.html`, nav links, top bar (no polling yet)  
2. **Pipeline view** — simplest: one polling fragment, no user input  
3. **Map view** — Leaflet init, cell GeoJSON endpoint, coverage stats fragment  
4. **Leads list** — table + search + filters  
5. **Lead detail panel** — slide-in, copy buttons  
6. **Raw scrapes view** — reuses leads list pattern  
7. **Run/Stop wiring** — connects to existing FastAPI orchestrator  

Each step is independently testable. Stop at any step and the app is useful.
