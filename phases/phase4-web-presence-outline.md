# Phase 4 — Web & Presence Pipeline — Outline
**Status: Placeholder — to be designed after enrichment is locked**

This pipeline runs as a separate stage after enrichment is complete. It takes the enriched record (specifically `web.url_final`) as its starting point and produces a detailed web and online presence report for each business.

---

## Inputs (from enrichment record)
- `web.url_final` — confirmed live URL, no need to re-check
- `web.https` — known
- `company.name_registered` / `name_trading`
- `social.google_place_id` — for review analysis
- `company.sic_code` — for sector-appropriate benchmarking

---

## Scope (to be designed)

### Website Technical Audit
- Full site crawl (Scrapy or similar)
- Tech stack detection (Wappalyzer)
- Page speed + Core Web Vitals (PageSpeed Insights API or Lighthouse CLI)
- Mobile friendliness
- HTTPS depth (mixed content, certificate validity/expiry)
- Broken links
- Sitemap + robots.txt presence

### SEO Audit
- Title tags, meta descriptions, heading structure
- Keyword presence vs. sector
- Image alt tags
- Schema.org coverage
- Internal linking structure
- Indexability signals

### Content Quality
- Number of pages
- Word count / content depth
- Last updated signals
- Blog / news presence
- Service pages vs. single-page site

### Social & Online Presence
- Facebook — page exists, follower count, last post date
- Instagram — exists, last active
- Google Business — claimed, verified, post activity
- Review platforms — Trustpilot, Checkatrade, TrustATrader (sector-relevant)
- Directory presence — Yell, Thomson Local, 192, FreeIndex

### Competitive Signals (optional, later)
- Estimated traffic (SimilarWeb free tier or alternative)
- Backlink count (free tools TBD)

---

## Output
A structured `web_presence` report object attached to the business record, covering scores/findings across each category above. Designed to feed into outreach personalisation ("your site loads slowly on mobile") and sales intelligence.

---

## Notes
- This pipeline is intentionally separate from enrichment — it's slower, heavier, and not always needed
- Can be triggered on-demand per lead or batched nightly
- Results stored separately so enrichment record stays clean and fast
- To be fully designed once enrichment module is built and tested
