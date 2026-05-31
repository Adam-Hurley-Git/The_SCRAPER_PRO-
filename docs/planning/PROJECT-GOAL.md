# Project Goal

## Canonical Goal

Scraper Pro exists to systematically capture as close to the full population of real local businesses as possible for a chosen niche and geography, then turn that raw market coverage into a clean, outreach-ready lead list.

The key objective is not to collect a sample. The objective is comprehensive coverage.

For that reason, the discovery layer is built around an adaptive quad grid approach over Google Maps results. The grid exists to work around result caps and progressively subdivide areas until coverage is exhausted, so the system can find every business it can realistically surface rather than only the first visible batch. This is a core part of the product goal, not an implementation detail.

In v1, Scraper Pro should:

- Discover businesses for a given niche and target area with maximum practical coverage
- Enrich each business with the best available contact data using deterministic methods first and AI fallback only when needed
- Normalise and deduplicate the resulting records
- Export a clean spreadsheet that is immediately usable for outreach
- Run inside a self-hosted, low-cost, checkpointed pipeline that can be resumed safely
- Be operable in the same way by a human through the UI or by an AI agent through the API

## What Success Means

Success in v1 means the system can take a search term and region, run the full pipeline end to end, and produce a deduplicated `leads.xlsx` containing the broadest practical set of businesses in that market plus the best verified contact data the enrichment stack can recover.

The standard is:

- Coverage-first discovery
- Structured and resumable execution
- Outreach-ready output
- Minimal manual cleanup
- Low operating cost

## Core Principle

The project is built on this assumption:

> If the market contains relevant businesses, the pipeline should aim to find all of them, not just enough of them.

That is why the quad grid coverage model is fundamental. Scraper Pro is intended to function as a market-exhaustion machine for local lead generation, not a lightweight scraper that returns partial results.

## Scope of v1

Included in v1:

- Phase 1: Discovery via Google Maps using adaptive spatial subdivision
- Phase 2: Enrichment of websites, emails, phones, owner/company data, and verification signals
- Phase 3: Normalisation, deduplication, and spreadsheet export

Explicitly deferred to v2:

- Phase 4: Web and presence audit
- Phase 5: Lead scoring

These later phases improve prioritisation and analysis, but they are not part of the current core goal. The current goal is complete discovery plus practical outreach readiness.

## Non-Goal

Scraper Pro is not trying to be a generic web scraping platform.

It is a purpose-built local business lead generation system designed to:

- maximise market coverage within a target niche and geography
- enrich records into usable prospects
- hand off a clean final dataset for outreach

## Short Reference Version

Scraper Pro is a self-hosted local lead generation pipeline whose primary goal is maximum practical market coverage, not partial sampling. It uses an adaptive quad grid over Google Maps to exhaust discovery for a niche and area, enriches the resulting businesses with verified contact data, then normalises, deduplicates, and exports an outreach-ready spreadsheet. Human users and AI agents should both be able to run the same pipeline reliably through shared state, checkpoints, and APIs.
