# Lead Enrichment — Research Findings
*What we have found. What we are still looking for. No assumed plan or direction.*

---

## What Enrichment Means in This Context

After scraping a raw list of businesses (name, address, phone, website, coordinates from Google Maps), enrichment means layering on additional contact data that wasn't in the original scrape — primarily: verified email addresses, direct phone numbers, owner/decision-maker names, employee counts, and social profiles. The goal is outreach-readiness.

---

## What gosom Already Provides (Pre-Enrichment Baseline)

From the scraper itself, before any enrichment step:

- Business name
- Phone number (the public-facing number listed on Google Maps)
- Website URL
- Address
- GPS coordinates
- Review count and rating
- Category (e.g. "Plumber")
- Status (open/closed/permanently closed)
- Google CID (unique business ID, useful as dedup key)

With the `-email` flag enabled, gosom also visits each business website and extracts any email addresses found via regex. This is the first and cheapest enrichment layer — it happens during the scrape itself.

---

## Data Sources Found

### 1. Companies House API (UK)
**URL:** https://developer.company-information.service.gov.uk/  
**Cost:** Completely free. Official UK government API.  
**What it provides:** Registered company name, company number, registered address, company status (active/dissolved/dormant), filing history. Critically: **director names**, appointment dates, nationality, occupation. Also **PSC data** (People of Significant Control — beneficial owners with 25%+ stake, voting rights, nature of control).  
**How to access:** Register for a free API key at Companies House developer portal. REST API with JSON responses.  
**Limitation:** Only covers registered limited companies. Sole traders, partnerships, and unregistered businesses are not in Companies House. For very small local tradespeople, coverage will be partial.  
**Note:** Wales-specific data is included — this is a UK-wide database.

---

### 2. gosom `-email` Flag (Website Email Extraction)
**Cost:** Free (part of the scraper)  
**What it does:** Visits each business website, fetches the HTML, runs regex to find `mailto:` links and email patterns.  
**Limitation:** Only finds publicly visible emails. Misses email addresses that are in contact forms, images, or behind JavaScript rendering.

---

### 3. theHarvester
**Repo:** https://github.com/laramies/theHarvester  
**Cost:** Free, open source  
**What it does:** OSINT tool that queries multiple public sources (Google, Bing, DuckDuckGo, LinkedIn, GitHub, Shodan, HunterIO, Censys, VirusTotal, and ~30 others) for emails, subdomains, and names associated with a target domain. Given a domain like `smithsplumbing.co.uk`, it searches across all sources simultaneously and returns any publicly indexed emails.  
**How to use:** `theHarvester -d targetdomain.co.uk -b google,linkedin,bing`  
**Limitation:** Results quality varies by domain size and age. Very small businesses with minimal web presence return few results.

---

### 4. EmailFinder (Josue87)
**Repo:** https://github.com/Josue87/EmailFinder  
**Cost:** Free, open source  
**What it does:** Searches for emails associated with a domain specifically through search engines (Google, Bing, DuckDuckGo). More focused than theHarvester — email-only.

---

### 5. EmailFinder (rix4uni)
**Repo:** https://github.com/rix4uni/emailfinder  
**Cost:** Free, open source  
**What it does:** Email OSINT tool querying Google, DuckDuckGo, Bing, Yahoo, Yandex, GitHub. Collects emails across many engines in one run.

---

### 6. Email Permutation + Verification
**Cost:** Free (compute only)  
**What it does:** Given an owner name (e.g. "John Smith") and a domain (e.g. `smithsplumbing.co.uk`), generate the statistically most likely email patterns:
- `john@smithsplumbing.co.uk`
- `jsmith@smithsplumbing.co.uk`
- `john.smith@smithsplumbing.co.uk`
- `j.smith@smithsplumbing.co.uk`
- `johnsmith@smithsplumbing.co.uk`
- `smith@smithsplumbing.co.uk`

Then verify each one using free SMTP verification tools (check MX records and SMTP handshake without sending an email).  
**Free verifier tools found:** verify-email.org, MailTester, Reoon Email Verifier (free tier), NeverBounce (free tier 1,000 verifications).  
**Limitation:** Requires knowing the owner's name first. Verification is not 100% reliable — some mail servers block SMTP probing.

---

### 7. Hunter.io
**URL:** https://hunter.io  
**Cost:** Free tier: 25 domain searches/month, 50 email verification/month  
**What it does:** Given a domain, returns: the email pattern the company uses (e.g. `{first}.{last}@domain.com`), any publicly found email addresses, email confidence scores.  
**Also has:** Email verifier (checks if an email address is deliverable).  
**Limitation:** 25 searches/month on free tier is very low for bulk enrichment. Primarily useful for manual verification or small batches.

---

### 8. Apollo.io
**URL:** https://apollo.io  
**Cost:** Free tier available (as of 2026)  
**Free tier limits:** Unlimited email reveals subject to ~250/day fair use cap. **5 mobile phone credits/month** (each mobile reveal costs 1 credit). 10 export credits/month (max 25 records per export).  
**What it provides:** Contact-level data tied to LinkedIn profiles — work email, job title, LinkedIn URL, sometimes direct phone. Company-level data: employee count, revenue range, industry, HQ location, tech stack.  
**Limitation:** Free tier phone data is nearly unusable (5 credits/month). Export limits make bulk enrichment impractical on free tier. Best suited for manual lookup of specific targets. UK/local SMB coverage is weaker than US enterprise coverage — database skews toward larger companies.

---

### 9. Skrapp.io
**URL:** https://skrapp.io  
**Cost:** Free tier: 150 email finds/month  
**What it does:** LinkedIn-based email finder. Given a person's name and company, finds their work email by pattern matching against known data.  
**Limitation:** 150/month is small. Requires knowing the person's name. LinkedIn-dependent, so coverage for non-LinkedIn-using tradespeople is low.

---

### 10. PhantomBuster
**URL:** https://phantombuster.com  
**Cost:** No permanent free tier. 14-day free trial only. Paid plans start at $69/month.  
**What it does:** LinkedIn automation and scraping — profile scraping, connection export, email extraction via its Professional Email Finder phantom.  
**Note:** PhantomBuster does not have its own email database. It uses external enrichment credits for email finding. LinkedIn ToS violation risk is documented: ~25–35% of heavy scrapers face account restrictions within 60 days.  
**Verdict for free/open-source requirement:** Does not qualify. Included here for awareness only.

---

### 11. OpenClay
**URL:** https://openclay.io  
**Repo:** https://github.com/topics/clay-alternative  
**Cost:** Free, open source (BYOK — bring your own API keys for LLMs)  
**What it does:** Open-source alternative to Clay.com. Spreadsheet-style interface for AI-powered data enrichment. Supports GPT, Claude, Gemini, Grok with your own API keys. No subscription, no data stored externally.  
**What it can do for enrichment:** Feed it a list of business names/domains, write a prompt to extract or infer data, use LLM to fill gaps. More of a workflow/orchestration layer than a data source itself.  
**Limitation:** Requires paid LLM API keys (though cost is low with Gemini Flash/GPT-4o-mini). Not a standalone data source — it wraps other sources or uses AI inference.

---

### 12. ScrapeGraphAI
**Repo:** https://github.com/ScrapeGraphAI/Scrapegraph-ai  
**Stars:** 23.9k  
**Cost:** Open source (free). Requires LLM API key (OpenAI, Groq, Gemini, etc.) or local Ollama (fully free).  
**What it does:** Given a website URL and a natural language prompt, uses an LLM to extract structured data. Example: "Extract the owner name, email, and phone number from this website." Returns clean JSON.  
**Relevant for enrichment:** Visiting each business website and using AI to extract contact details more intelligently than regex — handles contact pages, "About Us" pages, non-standard layouts.  
**Limitation:** Slower and more expensive (API cost) than regex scraping. With local Ollama it is free but requires a capable machine (8GB+ VRAM for useful models). Not suitable for scraping Google Maps itself.

---

### 13. n8n HTTP + Regex (Website Contact Scraping)
**Cost:** Free (self-hosted n8n)  
**What it does:** For each lead with a website URL, an n8n sub-workflow fetches the HTML and runs JavaScript regex to extract emails, phone numbers in common formats, and social media links.  
**Based on:** n8n template 2567 approach.  
**Limitation:** Fragile — breaks for JavaScript-rendered contact pages, embedded contact forms, and non-standard layouts.

---

### 14. Yell.com / 192.com / Thomson Local (UK Directories)
**Cost:** Free to access (public web data)  
**What they provide:** UK business listings with phone, address, sometimes website and email. Often have data that isn't on Google Maps — particularly for older established businesses.  
**How to access:** Web scraping (no official API). n8n HTTP request + parser, or Playwright-based scraping.  
**Research status:** No dedicated open-source scraper identified specifically for Yell/192 yet. This is an **open gap** — tools exist in concept but none have been validated.

---

### 15. Facebook Business Pages
**Cost:** Free to access (public data)  
**What they provide:** Many UK tradespeople use Facebook instead of (or instead of a website) — phone numbers, email, sometimes owner name, business hours. High coverage for the local SMB segment.  
**How to access:** Facebook Graph API has public page data endpoints, though coverage has reduced over time. Alternatively: web scraping public business pages.  
**Research status:** No validated free tool identified specifically for extracting Facebook Business page contact data at scale. This is an **open gap**.

---

### 16. LinkedIn (Public Profile Data)
**Cost:** Free to access manually; scraping is ToS violation  
**What it provides:** Decision-maker names, job titles, company employee counts, direct contact visibility for connections.  
**Research status:** Most open-source LinkedIn scrapers violate ToS and carry account ban risk. PhantomBuster (paid) and similar tools exist but were already noted above. A validated safe/free solution has **not been identified** — this remains an open question.

---

## What We Are Still Looking For

The following are gaps identified in this research that have not yet been resolved:

**Email verification at scale, free:** Hunter.io free tier (25/month) is too small. NeverBounce has a 1,000 free credit one-off. No unlimited free email verifier has been identified.

**Facebook Business Page scraping at scale:** Many UK tradespeople have a Facebook presence but no website. No validated free tool found.

**UK-specific directory scraping (Yell, 192, Thomson):** These contain complementary data not on Google Maps. No validated open-source scraper for these identified.

**LinkedIn enrichment without ToS risk:** No free, safe solution identified. Remains an open question.

**Employee count for micro businesses:** Apollo/ZoomInfo data for sole traders and micro businesses (1–5 employees) is unreliable. No alternative identified.

**Phone number format normalisation:** UK numbers come in many formats (+44, 01792, 07xxx). No tool specifically for cleaning/standardising this has been evaluated yet.

**Waterfall enrichment orchestration:** The concept of a waterfall (try source A, if no result try source B, etc.) is well-suited to this problem. OpenClay is the closest open-source option found, but has not been tested against UK local business data.

---

## Summary Table

| Tool | Cost | Data Provided | UK SMB Coverage | Status |
|---|---|---|---|---|
| gosom `-email` flag | Free | Emails from websites | Good (if website exists) | Validated |
| Companies House API | Free | Director names, company info | Partial (registered companies only) | Validated |
| theHarvester | Free, OSS | Emails from public sources | Variable | Found, untested |
| EmailFinder (Josue87) | Free, OSS | Emails via search engines | Variable | Found, untested |
| Email permutator + verify | Free | Derived emails | Requires name first | Concept validated |
| Hunter.io | Free (25/mo) | Email patterns, verification | Limited | Free tier confirmed |
| Apollo.io | Free (limited) | Emails, some phones, company data | Weak for micro-SMB | Free tier confirmed |
| Skrapp.io | Free (150/mo) | LinkedIn emails | LinkedIn-dependent | Free tier confirmed |
| PhantomBuster | No free tier | LinkedIn scraping | N/A | Not free |
| OpenClay | Free (BYOK LLM) | AI enrichment layer | Untested | Found, untested |
| ScrapeGraphAI | Free (needs LLM) | Website contact extraction | Good (per-site) | Found, untested |
| n8n HTTP + regex | Free | Website emails/phones | Good (basic) | Approach validated |
| Yell / 192.com | Free (scraping) | Phone, address, email | High | Open gap — no tool |
| Facebook Business | Free (scraping) | Phone, email, owner | High for trades | Open gap — no tool |
| LinkedIn | ToS risk | Names, titles, company size | Poor for micro-SMB | Open gap |
