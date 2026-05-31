# Phase 5 — Lead Scoring
**Status: DEFERRED — v2 build. To be planned and built as a separate phase.**

---

## Overview

Lead scoring runs after Phase 4 (Normalise & Dedup) and assigns each lead a quality score based on how much data was successfully enriched. It produces the final `score` field in `leads.xlsx` and enables hot-lead filtering in the UI.

Deferred to keep v1 scope tight. The scoring logic is researched and the approach is agreed — this document is the placeholder for the full v2 design session.

---

## Planned Scoring (0–10)

| Signal | Points |
|---|---|
| Has website | +2 |
| Has email | +3 |
| Verified email (high confidence) | +1 bonus |
| Has owner name | +2 |
| Has phone | +1 |
| Rating ≥ 4.0 | +1 |

Score ≥ 7 = hot lead — prioritise for outreach.

---

## Schema Change (when built)

The `score REAL` column is currently commented out in the SQLite `leads` table. Phase 5 build adds it back and populates it as the final step before export.

Output schema gains:

| Field | Source | Notes |
|---|---|---|
| score | Phase 5 | 0–10 lead quality score |

`leads.xlsx` export sorted by score descending once Phase 5 is in place.

---

## To Be Designed in v2 Session

- Whether scoring runs as a separate pipeline phase or inline at export time
- UI controls: score range filter in Leads tab, hot-lead badge
- Whether score is recalculated on re-enrichment or stored once
- Weighting adjustments based on real data from v1 runs
