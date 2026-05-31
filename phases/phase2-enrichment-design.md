# Phase 2 — Enrichment
**Scraping Pipeline — Enrichment Layer v3**

---

## Role of Enrichment

The scraper already does heavy lifting — it pulls business name, address, phone(s), website, Google listing data, and more. Enrichment's job is:

1. **Extend** — find data the scraper can't reach (Companies House officers, WHOIS, website contact page parse)
2. **Validate** — confirm what the scraper found is real (email SMTP probe, phone format, website live check)
3. **Organise** — structure everything into a clean, rich record with source metadata on every field

**What enrichment does NOT do:**
- Deep website crawling or auditing — that's the Web & Presence Pipeline (separate stage)
- Tech stack analysis, page speed, SEO checks — separate stage
- Throw away data because two sources give different values — different sources often give genuinely different, both valid, information

---

## Free-Only Source Stack

Core enrichment sources are free to use, but some require keys. In v1 that means Companies House and the Groq fallback.

| Source | What it gives | Method |
|---|---|---|
| **Companies House API** | Company number, registered address, all SIC codes, incorporation date, company status (active/dissolved/dormant/liquidation/administration); officers (names, roles, appointment dates, resignation dates, nationality, occupation); PSC data (People with Significant Control — beneficial owners with 25%+ stake/voting rights, nature of control); full filing history; annual accounts (turnover band, net assets, total assets, liabilities, cash, employee count — from filed micro/small/full accounts); charges/mortgages (secured lending against the company); insolvency flags; name change history; address change history; confirmation statement recency | Free API key required, 600 req/min |
| **Groq API** | Fallback extraction from cleaned page content when deterministic parsing misses email, phone, or person name | API key required, direct JSON extraction |
| **Postcodes.io** | Lat/lng, ward, local authority, LSOA from any UK postcode | REST API, no auth |
| **HTTP check (httpx)** | Live/dead, HTTPS, final URL after redirects, response time | Single GET request |
| **Homepage + contact page parse** | Emails, phones, person names, Schema.org/JSON-LD structured data | httpx + Selectolax (CSS selectors), 2 pages max |
| **WHOIS (python-whois)** | Domain owner/org, registration date, expiry date, registrar | Python lib |
| **dnspython** | MX records — email domain validity | Python lib |
| **dns-smtp-email-validator** | Confirms specific email address exists at mail server (SMTP handshake, no send) | Python lib |
| **libphonenumber** | Phone number format validation, type (mobile/landline), national format | Python lib |
| **Selectolax** | Fast HTML parsing for website/contact page extraction | `pip install selectolax` — CSS selectors, 10–50× faster than BeautifulSoup |
| **httpx[http2]** | HTTP/2 support on all outbound requests | `pip install httpx[http2]`, enable with `http2=True` on the client |

---

## SMTP Rate Limiting

**Hard limit: 1 probe per second.** SMTP verification probes a live mail server — hammering it aggressively risks getting our IP blacklisted by the receiving domain's mail server, which would cause all future probes to that domain to return false negatives.

```python
import time
import smtplib

SMTP_MIN_INTERVAL = 1.0  # seconds between probes

_last_smtp_call = 0.0

def smtp_verify(email: str) -> dict:
    global _last_smtp_call
    elapsed = time.monotonic() - _last_smtp_call
    if elapsed < SMTP_MIN_INTERVAL:
        time.sleep(SMTP_MIN_INTERVAL - elapsed)
    _last_smtp_call = time.monotonic()

    try:
        # dns-smtp-email-validator call here
        result = verify_email(email)  # underlying lib call
        return {"verified": result.is_valid, "smtp_code": result.smtp_code}
    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, ConnectionRefusedError):
        # Server actively refused or dropped — back off before next probe
        time.sleep(5)
        return {"verified": False, "smtp_code": None, "error": "connection_refused"}
    except Exception as e:
        return {"verified": False, "smtp_code": None, "error": str(e)}
```

**Backoff rules:**
- Connection refused or server disconnect → sleep 5s before the next probe (different domain)
- Any error → return `verified: False`, mark `email_confidence: medium` (MX confirmed, SMTP blocked)
- Never retry the same address in the same run — the checkpoint system handles retries on next run

**Why this matters:** Sole trader businesses on shared hosting often have mail servers that are quick to flag IPs hitting multiple addresses in rapid succession. 1 probe/sec is conservative enough to avoid triggering rate-limiting on even the strictest servers while still processing ~3,600 addresses per hour.

---

## Website Checks — Lightweight Only

Enrichment touches the website for **one purpose only: completing the business record**. Two pages, no crawling.

**httpx client setup (HTTP/2 enabled):**

```python
import httpx

# Reuse one client across all enrichment requests — connection pooling + HTTP/2
http_client = httpx.Client(
    http2=True,
    timeout=10.0,
    follow_redirects=True,
    headers={"User-Agent": "Mozilla/5.0 (compatible; enrichment-bot/1.0)"}
)
```

Create once at enrichment startup, share across all stages. Close on shutdown. HTTP/2 is transparently negotiated — falls back to HTTP/1.1 for servers that don't support it.

### What we do
| Check | How | Output |
|---|---|---|
| Live/dead | Single GET | `status: live/dead/redirect/error` |
| HTTPS | Check final URL scheme | `https: true/false` |
| Final URL | Follow redirects | `url_final` (canonical URL for web audit to use later) |
| Response time | Measure GET duration | `response_time_ms` |
| Homepage parse | Extract emails, phones, person names, JSON-LD | Selectolax CSS selectors — added to contacts arrays |
| Contact page parse | Same extraction on `/contact` or `/contact-us` if exists | Selectolax CSS selectors — added to contacts arrays |
| Schema.org / JSON-LD | Parse structured data embedded in HTML | Free, instant, no crawl — many sites have full contact info here |
| AI fallback | Direct Groq call over cleaned content + metadata + deterministic partials | Only if `email`, `phone`, or `person name` is missing |
| WHOIS | Domain owner, expiry | `web.whois_owner`, `web.domain_expires` |
| MX records | Email domain has valid mail server | Used for email validation only |

### What we do NOT do here
- Full site crawl
- Tech stack detection (Wappalyzer)
- Page speed / Core Web Vitals
- SEO analysis
- Mobile friendliness check
- Content quality assessment
- Social media audit
- Backlink data
- Broad OSINT sweeps with theHarvester in v1

All of the above → **Phase 4 — Web & Presence Audit** (separate stage, runs after enrichment)

### AI Fallback Rules

- Deterministic extraction always runs first.
- AI fallback runs only if any of `email`, `phone`, or `person name` is still missing.
- Input to the model = cleaned homepage/contact-page content + selected metadata + deterministic partial results.
- The model may infer roles and labels such as `owner`, `director`, `generic`, or `sales`, but may not invent names, emails, phones, or company facts.
- Any AI-recovered field is accepted only if returned with evidence: a short snippet plus a page source label such as `homepage`, `contact_page`, `json_ld`, `mailto_link`, or `footer`.

### Hand-off to Web Pipeline
Enrichment outputs a clean `web` object that the Web Pipeline picks up directly:
```json
"web": {
  "url_final": "https://swanseaplumbing.co.uk",
  "status": "live",
  "https": true,
  "response_time_ms": 1840,
  "domain_expires": "2026-11-02",
  "whois_owner": "Robert Davies / Swansea Plumbing Ltd"
}
```
The Web Pipeline starts from `url_final` — it doesn't redo the live check.

---

## The Multi-Contact Model

A real business has multiple legitimate contact points. Different sources give genuinely different — and both valid — pieces of information. We never discard; we organise.

### People

```json
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
    "context": "Listed as 'Bob, founder & lead plumber'",
    "flag": "possible_same_person:Robert Davies"
  }
]
```

"Robert Davies" and "Bob Davies" may be the same person — flagged, not auto-merged. Human review decides.

### Phone Numbers

```json
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
  },
  {
    "number": "+447891234567",
    "number_display": "07891 234567",
    "type": "mobile",
    "role_inferred": "owner_mobile",
    "sources": ["companies_house_filing"],
    "source_count": 1,
    "validated": true,
    "primary": false,
    "linked_person": "Robert Davies"
  }
]
```

### Emails

```json
"emails": [
  {
    "address": "info@swanseaplumbing.co.uk",
    "role_inferred": "generic",
    "sources": ["website_footer"],
    "source_count": 1,
    "smtp_verified": true,
    "mx_valid": true,
    "primary": true
  },
  {
    "address": "bob@swanseaplumbing.co.uk",
    "role_inferred": "owner_direct",
    "sources": ["website_about_page"],
    "source_count": 1,
    "smtp_verified": true,
    "mx_valid": true,
    "primary": false,
    "linked_person": "Bob Davies"
  }
]
```

---

## Role Inference Rules

Heuristics only — always stored as `role_inferred`, never treated as confirmed.

### Phone
| Signal | Inferred Role |
|---|---|
| Mobile (07xxx) from Companies House filing | `owner_mobile` |
| Mobile from website "Call [name] directly" | `owner_mobile` |
| Landline matching Google listing main number | `main_line` |
| Appears on 3+ sources | `main_line` |
| Landline on contact page, different from main | `secondary_line` |
| Single directory only, not on website | `unverified` |

### Email
| Signal | Inferred Role |
|---|---|
| `info@`, `hello@`, `contact@`, `admin@` | `generic` |
| `quotes@`, `enquiries@`, `sales@` | `sales` |
| `jobs@`, `careers@` | `hr` |
| First name matches a known director/owner | `owner_direct` |
| Personal name pattern next to a person on About/Team page | `personal` — linked to that person |

### Person
| Signal | Inferred Role |
|---|---|
| Companies House Director | `director` |
| Companies House Secretary | `secretary` |
| Website About page, described as founder/owner | `owner` |
| Website team page with job title | `staff` (title stored as context) |
| Google listing owner response name | `owner` |

---

## Source Weighting (display priority, not conflict resolution)

Used to rank contacts for outreach selection — does not delete lower-ranked data.

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

---

## Potential Match Flags

When two items could be the same thing, flag — don't auto-merge.

- `possible_same_person` — e.g. "Robert Davies" (CH) + "Bob Davies" (website)
- `review_which_is_primary` — two mobiles both inferred as `owner_mobile`
- `domain_mismatch` — email domain doesn't match website domain
- `address_discrepancy` — Companies House registered address ≠ trading address (common and usually legitimate)

Flags go in `review_flags` — visible to human reviewer, don't block the record.

---

## Scraper vs. Enrichment — What Each Provides

| Field | Scraper | Enrichment adds |
|---|---|---|
| Business name | ✅ | Registered name vs. trading name distinction |
| Address | ✅ | Geo: lat/lng, ward, local authority |
| Phone | ✅ One number typically | Additional numbers from website, CH, directories |
| Website URL | ✅ | Live check, final URL, HTTPS, WHOIS |
| Email | ❌ Rarely | Website parse, SMTP validation |
| Owner name | ❌ | Companies House officers, website About page |
| Beneficial owner (PSC) | ❌ | Companies House PSC data — 25%+ stake/voting rights |
| Company number | ❌ | Companies House lookup |
| SIC / sector | ❌ | Companies House (all SIC codes) |
| Incorporation date | ❌ | Companies House |
| Turnover band | ❌ | Companies House annual accounts |
| Net assets / total assets | ❌ | Companies House annual accounts |
| Liabilities | ❌ | Companies House annual accounts |
| Cash at bank | ❌ | Companies House annual accounts |
| Employee count | ❌ | Companies House annual accounts |
| Charges / secured lending | ❌ | Companies House charges register |
| Insolvency / administration | ❌ | Companies House insolvency data |
| Filing status / overdue | ❌ | Companies House filing history |
| Domain expiry | ❌ | WHOIS |
| MX / email validity | ❌ | dnspython |

---

## Full Output Schema

```json
{
  "business_id": "uuid",
  "pipeline_version": "1.0",
  "scraped_at": "2026-05-31T09:00:00Z",
  "enriched_at": "2026-05-31T09:05:00Z",
  "enrichment_sources_used": [
    "companies_house", "postcodes_io", "website_parse",
    "whois", "smtp_probe"
  ],

  "company": {
    "name_scraped": "Swansea Plumbing",
    "name_registered": "Swansea Plumbing Ltd",
    "name_trading": "Bob's Plumbing Services",
    "companies_house_number": "12345678",
    "companies_house_status": "active",
    "sic_codes": [
      { "code": "43220", "description": "Plumbing, heat and air-conditioning installation" }
    ],
    "incorporation_date": "2015-03-12",
    "last_accounts_date": "2024-06-30",
    "accounts_overdue": false,
    "last_confirmation_statement": "2025-03-01",
    "confirmation_statement_overdue": false,
    "previous_names": [],
    "finances": {
      "source": "companies_house_accounts",
      "accounts_year_end": "2024-06-30",
      "accounts_type": "micro-entity",
      "turnover_band": "£100k–£250k",
      "turnover_exact": null,
      "net_assets": 42000,
      "total_assets": 68000,
      "total_liabilities": 26000,
      "cash_at_bank": 18500,
      "employee_count": 3,
      "employee_band": "1-9",
      "note": "Micro-entity accounts — turnover exact figure not filed, band estimated from net assets"
    },
    "charges": [],
    "insolvency": {
      "flag": false,
      "details": null
    },
    "pscs": [
      {
        "name": "Robert Davies",
        "nature_of_control": ["ownership-of-shares-75-to-100-percent"],
        "notified_on": "2016-04-06"
      }
    ]
  },

  "addresses": [
    {
      "type": "trading",
      "source": "google_listing",
      "full": "14 Wind Street, Swansea, SA1 1DP",
      "postcode": "SA1 1DP",
      "lat": 51.6193,
      "lng": -3.9437,
      "local_authority": "City and County of Swansea",
      "ward": "Castle"
    },
    {
      "type": "registered",
      "source": "companies_house",
      "full": "c/o Davies Accountants, 55 High Street, Swansea, SA1 2AB",
      "postcode": "SA1 2AB",
      "lat": 51.6201,
      "lng": -3.9441,
      "local_authority": "City and County of Swansea",
      "ward": "Castle",
      "flag": "address_discrepancy"
    }
  ],

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
      "context": "Listed as 'Bob, founder & lead plumber'",
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
    },
    {
      "number": "+447891234567",
      "number_display": "07891 234567",
      "type": "mobile",
      "role_inferred": "owner_mobile",
      "sources": ["companies_house_filing"],
      "source_count": 1,
      "validated": true,
      "primary": false,
      "linked_person": "Robert Davies"
    }
  ],

  "emails": [
    {
      "address": "info@swanseaplumbing.co.uk",
      "role_inferred": "generic",
      "sources": ["website_footer"],
      "source_count": 1,
      "smtp_verified": true,
      "mx_valid": true,
      "primary": true
    },
    {
      "address": "bob@swanseaplumbing.co.uk",
      "role_inferred": "owner_direct",
      "sources": ["website_about_page"],
      "source_count": 1,
      "smtp_verified": true,
      "mx_valid": true,
      "primary": false,
      "linked_person": "Bob Davies"
    }
  ],

  "web": {
    "url_final": "https://swanseaplumbing.co.uk",
    "status": "live",
    "https": true,
    "response_time_ms": 1840,
    "whois_owner": "Robert Davies / Swansea Plumbing Ltd",
    "domain_registered": "2014-11-02",
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
    "review_flags": [
      "address_discrepancy",
      "possible_same_person:Robert Davies+Bob Davies"
    ],
  }
}
```

---

## Companies House Matching Rules

Companies House enrichment is useful only when the match is conservative. Wrong-company attachment is worse than leaving the company section blank.

### Matching Order

1. Exact normalized name match
2. Normalized match after stripping legal suffixes and decorative locality noise
3. Postcode-aware shortlist match
4. Website/domain-supported shortlist match
5. Conservative fuzzy fallback only if the earlier steps fail

### Normalization Rules

Normalize business names before matching by:

- lowercasing
- stripping punctuation
- collapsing repeated whitespace
- standardizing or removing legal suffixes such as `Ltd`, `Limited`, `LLP`, `Limited Liability Partnership`
- stripping clearly decorative locality suffixes or prefixes when present

### Confidence Rules

Store both:

- `match_method`
- `match_confidence`

Suggested methods:

- `exact_normalized`
- `suffix_stripped_exact`
- `postcode_supported`
- `domain_supported`
- `conservative_fuzzy`
- `unmatched`

Suggested confidence levels:

- `high`
- `medium`
- `low`
- `ambiguous`

If ambiguity remains after shortlist scoring, leave the lead unmatched. Do not attach officers, PSCs, charges, or financials from a low-confidence candidate.

---

## SMTP Verification Rules

SMTP probing is a confidence-raising step, not a binary truth oracle.

Required behavior:

- hard cap of `1 probe/second` globally
- `5s` backoff after connection refusal or server disconnect
- no retry of the same address in the same run
- tri-state result:
  - `smtp_verified_true`
  - `smtp_verified_false`
  - `smtp_unverifiable`

### Confidence Mapping

| Signals | Confidence |
|---|---|
| Syntax valid only | `low` |
| Syntax valid + MX valid | `medium` |
| Syntax valid + MX valid + SMTP handshake succeeded | `high` |
| SMTP `250` mailbox confirmation | `very_high` |

If MX is valid but SMTP is blocked, rate-limited, or otherwise hostile, the email remains usable with reduced confidence. Do not discard it purely because the mail server would not cooperate.

---

## Checkpoint / Resume

Phase 2 runs per lead, per stage, and uses the same checkpoint pattern as the rest of v1.

**Stage statuses:** `pending -> running -> done / failed`

Tracked fields on the lead record:

- `website_status`
- `ai_fallback_status`
- `whois_mx_status`
- `companies_house_status`
- `smtp_status`

On startup or resume, any lead left in `running` for a Phase 2 stage is reset to `pending` before processing continues.

Rules:

- deterministic website extraction runs first
- AI fallback runs only if `email`, `phone`, or `person name` is still missing
- failed-only retry re-queues only leads with `failed` for the selected stage
- indexed scalar outputs are written after enrichment so export/filter paths do not have to parse JSON

---

## REST API Endpoints (Phase 2)

| Method | Endpoint | What it does |
|---|---|---|
| `POST` | `/api/projects/{id}/phases/2/run` | Run Phase 2 enrichment |
| `POST` | `/api/projects/{id}/phases/2/resume` | Resume Phase 2 from checkpoint |
| `POST` | `/api/projects/{id}/phases/2/retry` | Retry failed leads only |
| `GET` | `/api/projects/{id}/pipeline/status` | Return per-stage Phase 2 progress and counts |

---

## File Structure

```
scraper-ui/
├── pipeline/
│   └── phase2_enrichment.py  # deterministic parse, AI fallback, WHOIS/MX, CH, SMTP
├── database.py               # stage status updates + enrichment JSON persistence
└── requirements.txt          # httpx[http2], selectolax, whois, dns, smtp, groq deps
```

---

## Output

Phase 2 writes the rich enrichment record into `leads.enrichment_data`, updates the indexed scalar fields used by the UI and export path, and leaves each lead ready for Phase 3.

Indexed scalar outputs written after enrichment:

- `primary_email`
- `primary_phone`
- `primary_person`
- `outreach_ready`

The canonical JSON blob remains the full source of truth. The scalar columns exist only for fast filtering and export.

---

## What Comes Next

Phase 3 picks up every lead where `output_status = pending` and performs:

- postcode bulk lookup via Postcodes.io
- phone normalization to E.164
- final CID dedup confirmation
- export to `leads.xlsx`
