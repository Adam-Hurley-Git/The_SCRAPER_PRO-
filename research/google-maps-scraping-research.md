# Google Maps Scraping Research Summary
*Session: May 2026 — for continuation in next session*

---

## The Core Problem

Google Maps caps search results at ~120 per query regardless of tool used. A single search for "plumbers in Swansea" will never return the full picture. The solution is **geographic grid searching**: divide the target area into a grid of small cells, run one search per cell, deduplicate results by Google's unique business ID (`cid`). This is what separates a real comprehensive scrape from a partial one.

---

## Chosen Tool: gosom/google-maps-scraper

**Repo:** https://github.com/gosom/google-maps-scraper  
**Licence:** MIT — fully free, no hidden costs  
**Language:** Go  
**Docker image:** `gosom/google-maps-scraper`  
**Stars:** 4.2k | **Forks:** 626 | **Open issues:** ~54 (May 2026)  

### How it works

Runs a headless Chromium browser via Playwright. No API key required. No Google Maps API, no SerpAPI, no third-party dependency. It opens maps.google.com like a human would, scrolls through results, and parses the DOM.

### Grid mode (the key feature)

`-grid-bbox "minLat,minLon,maxLat,maxLon"` combined with `-grid-cell 0.5` (km) splits the bounding box into cells and runs one search per cell. For Swansea, bbox is approximately `51.5900,-4.0300,51.6700,-3.8900`. This is what enables complete coverage of a geographic area.

### Data extracted (33 fields)

Core reliable fields: business name, address, phone, website URL, GPS coordinates (lat/lon), Google CID (unique ID), category, rating, review count, price range, status (open/closed), opening hours, thumbnail, descriptions.

Optional: emails from business websites (add `-email` flag — visits each website and extracts emails via regex).

### Known issues (as of May 2026)

Active regressions in open issues: `open_hours` only returns Wednesday (#233, #241), `user_reviews` returning empty arrays (#234, #256), `reviews_count` = 0 (#232), Docker failing on unsupported OS configurations (#230). All broken fields are secondary enrichment fields. **Core lead gen fields — name, phone, website, address, coordinates — have no reported regressions.**

### Resource usage

Runs a headless Chromium browser — not lightweight. Official Kubernetes suggestion: 512MB RAM + 0.5 CPU per worker. Practical reality: `-c 4` on a standard 8GB laptop works fine for city-scale scrapes. `-c 8` or `-c 16` for faster runs on capable hardware. Higher concurrency = higher block risk without proxies.

### Performance

~120 places/minute at `-c 8 -depth 1`. A full Swansea grid scrape with 0.5km cells takes 20–40 minutes on modest hardware.

### Interfaces available

- CLI (Docker one-liner)
- Web UI (browser interface at localhost:8080, via `-web` flag)
- REST API (full OpenAPI 3.0 spec, job creation/polling/download endpoints)
- AI Agent Skill (`npx skills add gosom/google-maps-scraper`)

### Example command for Swansea plumbers

```bash
docker run \
  -v "$PWD/queries.txt:/queries.txt:ro" \
  -v "$PWD/output:/out" \
  gosom/google-maps-scraper \
  -input /queries.txt \
  -results /out/results.csv \
  -grid-bbox "51.5900,-4.0300,51.6700,-3.8900" \
  -grid-cell 0.5 \
  -zoom 16 \
  -depth 1 \
  -c 4 \
  -email \
  -exit-on-inactivity 5m
```

`queries.txt` content: `plumbers in Swansea`

---

## Orchestration: n8n

**Self-hosted n8n** (free) can call gosom's REST API to automate the full scrape-to-output pipeline. gosom runs in REST API mode (`-web` flag), n8n calls it as an HTTP service.

### n8n template landscape

The n8n template library has many Google Maps-related workflows. They fall into two camps:

**Avoid — require paid external APIs:**
- Template 2063: Uses SerpAPI (paid)
- Template 5743: Uses Apify + GPT + Airtable (paid)
- Template 6634: Uses Apify (paid)

**Relevant — free approaches:**
- Template 2567 ("Scrape emails without third-party APIs"): Uses raw HTTP requests + JavaScript regex against Google Maps HTML. Free but fragile, no grid mode, limited to ~20–60 results per query. Useful as inspiration for n8n code nodes.
- Template 5385 ("Lead gen to Google Sheets"): Similar approach with Google Sheets output.

The recommended integration is gosom REST API as the scraping engine + n8n as the workflow layer, rather than using n8n templates as the scraper itself.

---

## Alternatives Evaluated

### omkarcloud/google-maps-scraper
**Repo:** https://github.com/omkarcloud/google-maps-scraper  
Python-based, claims 50+ data points and 200+ results, includes enrichment features. Less battle-tested at scale than gosom, fewer integration points (no clean REST API mode). Viable alternative, not the primary recommendation.

### ScrapeGraphAI (Scrapegraph-ai)
**Repo:** https://github.com/ScrapeGraphAI/Scrapegraph-ai  
**Stars:** 23.9k — much larger repo  
General-purpose LLM-based web scraper. Not a Google Maps scraper. Requires an LLM (OpenAI API or local Ollama). Designed to extract structured data from arbitrary websites given a natural language prompt. **Not suited for the discovery/listing step**. Potentially relevant later in the pipeline for enriching individual business websites (extracting contact details from a business's own site).

### SerpAPI, Outscraper, Apify
All require paid subscriptions beyond small free tiers. Not aligned with the free/open-source goal.

---

## Key Technical Facts

- Google Maps hard limit: ~120 results per search query
- Grid mode solution: each cell = up to 120 results, deduplicate by `cid`
- No proxy needed for small city-scale scrapes; needed for large-scale or high-concurrency runs
- Webshare offers a free residential proxy tier (useful for scale-up)
- gosom is a living tool — Google DOM changes periodically break secondary fields; expect ~2–4 week fix lag
- The `-email` flag significantly increases run time as it visits every business website

---

## Status

Research complete. Tool selected. Next session: set up Docker + test run against Swansea bbox, then build n8n REST API orchestration workflow.
