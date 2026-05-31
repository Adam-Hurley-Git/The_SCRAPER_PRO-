# Phase 3 — Normalise & Dedup

Runs after Phase 2 enrichment. Normalises all phone numbers to E.164 format, deduplicates the lead list, and exports the final `leads.xlsx`. No scoring — that is Phase 5, deferred to v2.

---

## When It Runs

```
Phase 2 complete (all enrichment statuses = done/failed)
  → Phase 3: for each lead where output_status = pending:
      → normalise phone → deduplicate by CID → write row to leads.xlsx
      → mark output_status = done
```

Checkpoint/resume applies identically to every other phase. A lead is only processed if `output_status = pending`. Interrupted runs reset any `running` leads to `pending` on next start.

---

## Phone Normalisation

**Library:** `phonenumbers` (Python port of Google libphonenumber)

```bash
pip install phonenumbers
```

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

# Examples:
# "01792 123456"    → "+441792123456"
# "07911 123456"    → "+447911123456"
# "+44 1792 123456" → "+441792123456"
# "01792123456"     → "+441792123456"
# "garbage"         → "garbage"  (returned unchanged)
```

Both `phone_raw` (original) and `phone_e164` (normalised) are written to the output — nothing is discarded.

---

## Deduplication

**Primary key: Google CID** — set by gosom at discovery time. Unique per business on Google Maps.

Deduplication happens at lead insert during Phase 1 (same CID within a project is skipped). By Phase 3, the lead list is already deduplicated. Phase 3 simply confirms no duplicates slipped through and removes any that did.

**Never deduplicate on phone alone** — a business can have multiple numbers. CID is the only safe key.

**Yell merge key** (name + first 4 chars of postcode) is defined and ready for v2 when Stage 2 is built. Not used in v1.

---

## Postcodes.io Bulk Lookup

The Postcodes.io API supports a bulk endpoint that accepts up to 100 postcodes per request. Use this instead of one request per lead — it reduces the total request count by ~100×.

```python
import httpx

def bulk_postcode_lookup(postcodes: list[str]) -> dict[str, dict]:
    """
    Look up up to 100 postcodes in a single POST.
    Returns a dict keyed by postcode string → result dict (or None if not found).
    """
    if not postcodes:
        return {}

    results = {}
    # Postcodes.io bulk endpoint accepts max 100 per request
    for i in range(0, len(postcodes), 100):
        batch = postcodes[i:i + 100]
        resp = httpx.post(
            "https://api.postcodes.io/postcodes",
            json={"postcodes": batch},
            timeout=10.0
        )
        resp.raise_for_status()
        for item in resp.json().get("result", []):
            postcode = item["query"]
            results[postcode] = item["result"]  # None if not found
    return results


def enrich_addresses_with_geo(leads: list[dict]) -> None:
    """
    Batch all postcodes from the lead list, look them up in bulk,
    then write lat/lng, ward, local_authority back onto each lead.
    """
    postcodes = [
        parse_postcode(json.loads(l["raw_data"]).get("address", ""))
        for l in leads
        if parse_postcode(json.loads(l["raw_data"]).get("address", ""))
    ]
    postcode_data = bulk_postcode_lookup(list(set(postcodes)))

    for lead in leads:
        address = json.loads(lead["raw_data"]).get("address", "")
        pc = parse_postcode(address)
        geo = postcode_data.get(pc)
        if geo:
            lead["_geo"] = {
                "lat": geo["latitude"],
                "lng": geo["longitude"],
                "ward": geo["admin_ward"],
                "local_authority": geo["admin_district"]
            }
```

Call `enrich_addresses_with_geo()` once before the export loop — not inside it. All Postcodes.io calls complete before a single row is written to the spreadsheet.

---

## Export

**Library:** `openpyxl`

```bash
pip install openpyxl
```

```python
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
import json

def export_leads_xlsx(project_id, output_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Leads"

    headers = [
        "business_name", "category", "address", "postcode",
        "phone_raw", "phone_e164", "website", "email",
        "email_confidence", "owner_name", "company_number",
        "google_cid", "source", "scrape_date"
    ]

    # Header row styling
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="1F4E79")
        cell.font = Font(bold=True, color="FFFFFF")

    # Write leads
    leads = get_leads_for_project(project_id)  # SQLite query
    for row_idx, lead in enumerate(leads, 2):
        data = json.loads(lead["raw_data"])
        ws.cell(row=row_idx, column=1, value=data.get("title"))
        ws.cell(row=row_idx, column=2, value=data.get("category"))
        ws.cell(row=row_idx, column=3, value=data.get("address"))
        ws.cell(row=row_idx, column=4, value=parse_postcode(data.get("address", "")))
        ws.cell(row=row_idx, column=5, value=data.get("phone"))
        ws.cell(row=row_idx, column=6, value=lead["phone_e164"])
        ws.cell(row=row_idx, column=7, value=data.get("website"))
        enrichment = json.loads(lead["enrichment_data"]) if lead["enrichment_data"] else {}
        company = enrichment.get("company", {})
        outreach = enrichment.get("outreach", {})
        emails = enrichment.get("emails", [])
        ws.cell(row=row_idx, column=8, value=outreach.get("primary_email"))
        ws.cell(row=row_idx, column=9, value=next((e.get("confidence") for e in emails if e.get("address") == outreach.get("primary_email")), None))
        ws.cell(row=row_idx, column=10, value=outreach.get("primary_person"))
        ws.cell(row=row_idx, column=11, value=company.get("companies_house_number"))
        ws.cell(row=row_idx, column=12, value=lead["cid"])
        ws.cell(row=row_idx, column=13, value=lead["source"])
        ws.cell(row=row_idx, column=14, value=lead["last_updated"][:10] if lead["last_updated"] else None)

    wb.save(output_path)
    return output_path
```

---

## Output Schema (leads.xlsx)

| Field | Source | Notes |
|---|---|---|
| business_name | gosom | |
| category | gosom | e.g. "Plumber" |
| address | gosom | Full trading address |
| postcode | gosom (parsed) | Extracted from address |
| phone_raw | gosom | Original format as scraped |
| phone_e164 | Phase 3 | Normalised: "+441792123456" |
| website | gosom | |
| email | Stage 3/4/6 | Best email found across all stages |
| email_confidence | Stage 6 | low / medium / high / very_high |
| owner_name | Stage 5 | From Companies House (blank if not found) |
| company_number | Stage 5 | Companies House number (blank if not registered) |
| google_cid | gosom | Dedup key |
| source | pipeline | "gosom" (yell added in v2) |
| scrape_date | pipeline | ISO date of discovery |

---

## Email Confidence Levels

Set by Stage 6 (email permutation + SMTP verification):

| Level | What it means |
|---|---|
| `low` | Syntax valid only |
| `medium` | Syntax + MX record found |
| `high` | Syntax + MX + SMTP handshake successful |
| `very_high` | SMTP 250 response (server confirmed address exists) |

Emails found directly (from website parse, gosom -email flag, or OSINT) inherit `high` unless SMTP-verified, in which case `very_high`.

---

## REST API Endpoints (Phase 3)

| Method | Endpoint | What it does |
|---|---|---|
| `POST` | `/api/projects/{id}/phases/3/run` | Run Phase 3 — normalise + dedup + export |
| `POST` | `/api/projects/{id}/phases/3/resume` | Resume from checkpoint |
| `GET` | `/api/projects/{id}/leads/export` | Download leads.xlsx |
| `GET` | `/api/projects/{id}/pipeline/status` | Check phase3 completion + counts |

---

## File Structure

```
scraper-ui/
├── pipeline/
│   └── phase3_output.py     # normalise_uk_phone(), deduplicate(), export_leads_xlsx()
└── requirements.txt         # includes: phonenumbers openpyxl
```

---

## What's Not Here

**Lead scoring (0–10)** is Phase 5, deferred to v2. See `phases/phase5-lead-scoring.md`.

No score column exists in the v1 export. When Phase 5 is built later, it can extend the schema and export contract explicitly.
