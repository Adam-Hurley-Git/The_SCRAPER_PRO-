from __future__ import annotations

import json
import re
import smtplib
import time as _time_module
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from time import monotonic
from typing import Any, Literal
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import BaseModel, Field, HttpUrl

try:
    from selectolax.parser import HTMLParser
except ImportError:  # pragma: no cover - optional dependency in local env
    HTMLParser = None

from database import (
    claim_next_pending_companies_house_lead,
    claim_next_pending_smtp_lead,
    claim_next_pending_website_lead,
    count_pending_companies_house_leads,
    count_pending_smtp_leads,
    count_pending_website_leads,
    mark_lead_website_failed,
    reset_running_companies_house_leads,
    reset_running_smtp_leads,
    reset_running_website_leads,
    update_lead_companies_house_enrichment,
    update_lead_smtp_enrichment,
    update_lead_website_enrichment,
)
from config import get_settings


EnrichmentSource = Literal[
    "companies_house",
    "postcodes_io",
    "website_parse",
    "whois",
    "smtp_probe",
    "google_listing",
    "contact_page",
    "homepage",
    "json_ld",
    "mailto_link",
    "footer",
]
ContactRole = Literal[
    "director",
    "owner",
    "staff",
    "secretary",
    "generic",
    "sales",
    "hr",
    "personal",
    "owner_direct",
    "main_line",
    "secondary_line",
    "owner_mobile",
    "unverified",
]
EmailConfidence = Literal["low", "medium", "high", "very_high"]
WebStatus = Literal["live", "dead", "redirect", "error", "unknown"]
CompaniesHouseMatchMethod = Literal[
    "exact_normalized",
    "suffix_stripped_exact",
    "postcode_supported",
    "domain_supported",
    "conservative_fuzzy",
    "unmatched",
]
MatchConfidence = Literal["high", "medium", "low", "ambiguous"]
EvidencePageSource = Literal["homepage", "contact_page", "json_ld", "mailto_link", "footer"]

EMAIL_PATTERN = re.compile(r"(?i)\b[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}\b")
PHONE_PATTERN = re.compile(r"(?:(?:\+44\s?7\d{3}|\+44\s?\(0\)\s?\d{2,4}|\+44\s?\d{2,4}|0\d{2,4})[\d\s().-]{5,}\d)")
PERSON_PATTERN = re.compile(
    r"(?:(?:Mr|Mrs|Ms|Miss|Dr)\.?\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})"
)
CONTACT_PATH_HINTS = ("contact", "about", "team", "staff", "get-in-touch")
NON_PERSON_TOKENS = {
    "about",
    "all",
    "book",
    "contact",
    "delicious",
    "discover",
    "evening",
    "find",
    "flavours",
    "flavors",
    "follow",
    "great",
    "greek",
    "home",
    "keep",
    "landscape",
    "lunch",
    "menu",
    "mobile",
    "monday",
    "ok",
    "open",
    "our",
    "play",
    "policy",
    "portrait",
    "privacy",
    "rights",
    "story",
    "table",
    "tablet",
    "thankyou",
    "traditional",
    "us",
    "verified",
    "video",
    "where",
    "with",
    "your",
}
UK_POSTCODE_PATTERN = re.compile(
    r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b",
    flags=re.IGNORECASE,
)
LEGAL_SUFFIX_PATTERNS = (
    r"limited liability partnership",
    r"limited",
    r"ltd",
    r"llp",
)
GENERIC_LOCALITY_TOKENS = {
    "branch",
    "central",
    "centre",
    "center",
    "city",
    "downtown",
    "east",
    "north",
    "south",
    "west",
}
ADDRESS_NOISE_TOKENS = {
    "avenue",
    "close",
    "court",
    "crescent",
    "drive",
    "lane",
    "park",
    "place",
    "road",
    "square",
    "street",
    "way",
}


@dataclass(slots=True)
class PageFetchResult:
    url: str
    html: str
    status: WebStatus
    response_time_ms: int


@dataclass(slots=True)
class ContactExtractionResult:
    emails: list[str]
    phones: list[str]
    people: list[str]
    contact_links: list[str]
    email_sources: dict[str, list[str]]
    phone_sources: dict[str, list[str]]
    person_sources: dict[str, list[str]]


@dataclass(slots=True)
class CompaniesHouseCandidate:
    title: str
    company_number: str | None
    company_status: str | None
    address_snippet: str | None
    address: dict[str, Any]
    raw: dict[str, Any]


@dataclass(slots=True)
class CandidateEvaluation:
    candidate: CompaniesHouseCandidate
    method: CompaniesHouseMatchMethod
    confidence: MatchConfidence
    score: int
    normalized_name: str
    normalized_name_stripped: str


def _append_source(mapping: dict[str, list[str]], key: str, source: str) -> None:
    mapping.setdefault(key, [])
    if source not in mapping[key]:
        mapping[key].append(source)


def _select_primary_person(person_records: list["PersonRecord"]) -> str | None:
    for person in person_records:
        if "json_ld" in person.sources:
            return person.name
    return None


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _html_to_text(html: str) -> str:
    if HTMLParser is not None:
        return HTMLParser(html).text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def extract_emails(text: str) -> list[str]:
    return _unique_preserve_order([match.lower() for match in EMAIL_PATTERN.findall(text)])


def _normalize_phone(candidate: str) -> str | None:
    normalized = re.sub(r"[^\d+]+", "", candidate)
    if normalized.startswith("44") and not normalized.startswith("+44"):
        normalized = f"+{normalized}"
    digits_only = re.sub(r"\D", "", normalized)
    if normalized.startswith("+44"):
        if len(digits_only) != 12:
            return None
    elif normalized.startswith("0"):
        if len(digits_only) not in {10, 11}:
            return None
    elif len(digits_only) < 10 or len(digits_only) > 15:
        return None
    return normalized


def extract_phones(text: str) -> list[str]:
    phones: list[str] = []
    for match in PHONE_PATTERN.findall(text):
        normalized = _normalize_phone(match)
        if normalized:
            phones.append(normalized)
    return _unique_preserve_order(phones)


def _looks_like_person_name(candidate: str) -> bool:
    parts = [part for part in candidate.split() if part]
    if len(parts) < 2 or len(parts) > 3:
        return False
    lowered = {part.lower() for part in parts}
    if lowered & NON_PERSON_TOKENS:
        return False
    return True


def extract_person_names(text: str) -> list[str]:
    candidates = [match.strip() for match in PERSON_PATTERN.findall(text)]
    filtered = [
        candidate
        for candidate in candidates
        if candidate.lower() not in {"contact us", "about us", "privacy policy"}
        and _looks_like_person_name(candidate)
    ]
    return _unique_preserve_order(filtered)


def _extract_script_blocks(html: str) -> list[str]:
    if HTMLParser is not None:
        parser = HTMLParser(html)
        return [
            node.text(strip=True)
            for node in parser.css("script[type='application/ld+json']")
            if node.text(strip=True)
        ]
    return re.findall(
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )


def extract_json_ld(html: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for block in _extract_script_blocks(html):
        try:
            decoded = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict):
            payloads.append(decoded)
        elif isinstance(decoded, list):
            payloads.extend(item for item in decoded if isinstance(item, dict))
    return payloads


def _extract_anchor_hrefs(html: str) -> list[str]:
    if HTMLParser is not None:
        parser = HTMLParser(html)
        return [node.attributes.get("href", "") for node in parser.css("a[href]")]
    return re.findall(r"<a[^>]+href=[\"']([^\"']+)[\"']", html, flags=re.IGNORECASE)


def extract_contact_links(html: str, base_url: str) -> list[str]:
    links: list[str] = []
    base_host = urlparse(base_url).netloc
    for href in _extract_anchor_hrefs(html):
        absolute = urljoin(base_url, href.strip())
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        if parsed.netloc and parsed.netloc != base_host:
            continue
        lowered = parsed.path.lower()
        if any(hint in lowered for hint in CONTACT_PATH_HINTS):
            links.append(absolute)
    return _unique_preserve_order(links)


def extract_contact_data(
    *,
    homepage_html: str | None,
    contact_page_html: str | None = None,
    homepage_url: str | None = None,
    contact_page_url: str | None = None,
) -> ContactExtractionResult:
    emails: list[str] = []
    phones: list[str] = []
    people: list[str] = []
    contact_links: list[str] = []
    email_sources: dict[str, list[str]] = {}
    phone_sources: dict[str, list[str]] = {}
    person_sources: dict[str, list[str]] = {}

    pages: list[tuple[str, str]] = []
    if homepage_html:
        pages.append(("homepage", homepage_html))
    if contact_page_html:
        pages.append(("contact_page", contact_page_html))

    for source_name, html in pages:
        text = _html_to_text(html)
        text_emails = extract_emails(text)
        text_phones = extract_phones(text)
        text_people = extract_person_names(text)
        emails.extend(text_emails)
        phones.extend(text_phones)
        people.extend(text_people)
        for email in text_emails:
            _append_source(email_sources, email, source_name)
        for phone in text_phones:
            _append_source(phone_sources, phone, source_name)
        for person in text_people:
            _append_source(person_sources, person, source_name)

        for payload in extract_json_ld(html):
            email = payload.get("email")
            if isinstance(email, str):
                parsed_emails = extract_emails(email)
                emails.extend(parsed_emails)
                for item in parsed_emails:
                    _append_source(email_sources, item, "json_ld")
            telephone = payload.get("telephone")
            if isinstance(telephone, str):
                parsed_phones = extract_phones(telephone)
                phones.extend(parsed_phones)
                for item in parsed_phones:
                    _append_source(phone_sources, item, "json_ld")
            founder = payload.get("founder")
            if isinstance(founder, dict) and isinstance(founder.get("name"), str):
                person = founder["name"].strip()
                people.append(person)
                _append_source(person_sources, person, "json_ld")
            employee = payload.get("employee")
            if isinstance(employee, dict) and isinstance(employee.get("name"), str):
                person = employee["name"].strip()
                people.append(person)
                _append_source(person_sources, person, "json_ld")

        if source_name == "homepage" and homepage_url:
            contact_links.extend(extract_contact_links(html, homepage_url))
        if source_name == "contact_page" and contact_page_url:
            contact_links.extend(extract_contact_links(html, contact_page_url))

    unique_emails = _unique_preserve_order(emails)
    unique_phones = _unique_preserve_order(phones)
    unique_people = _unique_preserve_order(people)

    return ContactExtractionResult(
        emails=unique_emails,
        phones=unique_phones,
        people=unique_people,
        contact_links=_unique_preserve_order(contact_links),
        email_sources={email: email_sources.get(email, []) for email in unique_emails},
        phone_sources={phone: phone_sources.get(phone, []) for phone in unique_phones},
        person_sources={person: person_sources.get(person, []) for person in unique_people},
    )


def create_http_client(timeout: float = 20.0) -> httpx.Client:
    client_kwargs = {
        "timeout": timeout,
        "follow_redirects": True,
        "headers": {"User-Agent": "ScraperPro/0.1"},
    }
    try:
        return httpx.Client(http2=True, **client_kwargs)
    except ImportError:
        return httpx.Client(http2=False, **client_kwargs)


def fetch_page(url: str, client: httpx.Client | None = None) -> PageFetchResult:
    owns_client = client is None
    active_client = client or create_http_client()
    try:
        started = monotonic()
        response = active_client.get(url)
        elapsed_ms = int((monotonic() - started) * 1000)
        if 200 <= response.status_code < 300:
            status: WebStatus = "redirect" if str(response.url) != url else "live"
        elif response.status_code == 404:
            status = "dead"
        else:
            status = "error"
        return PageFetchResult(
            url=str(response.url),
            html=response.text,
            status=status,
            response_time_ms=elapsed_ms,
        )
    finally:
        if owns_client:
            active_client.close()


class Evidence(BaseModel):
    snippet: str
    page_source: str


class SicCode(BaseModel):
    code: str
    description: str


class PscRecord(BaseModel):
    name: str
    nature_of_control: list[str] = Field(default_factory=list)
    notified_on: str | None = None


class InsolvencyRecord(BaseModel):
    flag: bool = False
    details: str | None = None


class CompanyFinances(BaseModel):
    source: str | None = None
    accounts_year_end: str | None = None
    accounts_type: str | None = None
    turnover_band: str | None = None
    turnover_exact: float | None = None
    net_assets: float | None = None
    total_assets: float | None = None
    total_liabilities: float | None = None
    cash_at_bank: float | None = None
    employee_count: int | None = None
    employee_band: str | None = None
    note: str | None = None


class CompanyRecord(BaseModel):
    name_scraped: str
    name_registered: str | None = None
    name_trading: str | None = None
    companies_house_number: str | None = None
    companies_house_status: str | None = None
    sic_codes: list[SicCode] = Field(default_factory=list)
    incorporation_date: str | None = None
    last_accounts_date: str | None = None
    accounts_overdue: bool = False
    last_confirmation_statement: str | None = None
    confirmation_statement_overdue: bool = False
    previous_names: list[str] = Field(default_factory=list)
    finances: CompanyFinances = Field(default_factory=CompanyFinances)
    charges: list[dict[str, Any]] = Field(default_factory=list)
    insolvency: InsolvencyRecord = Field(default_factory=InsolvencyRecord)
    pscs: list[PscRecord] = Field(default_factory=list)
    match_method: CompaniesHouseMatchMethod = "unmatched"
    match_confidence: MatchConfidence = "ambiguous"


class AddressRecord(BaseModel):
    type: str
    source: str
    full: str
    postcode: str | None = None
    lat: float | None = None
    lng: float | None = None
    local_authority: str | None = None
    ward: str | None = None
    flag: str | None = None


class PersonRecord(BaseModel):
    name: str
    role_inferred: ContactRole
    sources: list[str] = Field(default_factory=list)
    companies_house_role: str | None = None
    appointment_date: str | None = None
    resigned: bool | None = None
    nationality: str | None = None
    occupation: str | None = None
    context: str | None = None
    linked_person: str | None = None
    flag: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class PhoneRecord(BaseModel):
    number: str
    number_display: str
    type: str | None = None
    role_inferred: ContactRole
    sources: list[str] = Field(default_factory=list)
    source_count: int = 0
    validated: bool = False
    primary: bool = False
    linked_person: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class EmailRecord(BaseModel):
    address: str
    role_inferred: ContactRole
    sources: list[str] = Field(default_factory=list)
    source_count: int = 0
    smtp_verified: bool | None = None
    mx_valid: bool | None = None
    syntax_valid: bool | None = None
    smtp_result: Literal["smtp_verified_true", "smtp_verified_false", "smtp_unverifiable"] | None = None
    confidence: EmailConfidence = "low"
    primary: bool = False
    linked_person: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class WebRecord(BaseModel):
    url_final: str | None = None
    status: WebStatus = "unknown"
    https: bool | None = None
    response_time_ms: int | None = None
    whois_owner: str | None = None
    domain_registered: str | None = None
    domain_expires: str | None = None


class SocialRecord(BaseModel):
    google_place_id: str | None = None
    google_rating: float | None = None
    google_review_count: int | None = None


class OutreachRecord(BaseModel):
    primary_email: str | None = None
    primary_phone: str | None = None
    primary_person: str | None = None
    ready: bool = False
    review_flags: list[str] = Field(default_factory=list)


class EnrichmentRecord(BaseModel):
    business_id: str
    pipeline_version: str = "1.0"
    scraped_at: str
    enriched_at: str
    enrichment_sources_used: list[EnrichmentSource] = Field(default_factory=list)
    company: CompanyRecord
    addresses: list[AddressRecord] = Field(default_factory=list)
    people: list[PersonRecord] = Field(default_factory=list)
    phones: list[PhoneRecord] = Field(default_factory=list)
    emails: list[EmailRecord] = Field(default_factory=list)
    web: WebRecord = Field(default_factory=WebRecord)
    social: SocialRecord = Field(default_factory=SocialRecord)
    outreach: OutreachRecord = Field(default_factory=OutreachRecord)


class AIFallbackField(BaseModel):
    value: str
    role_inferred: ContactRole | None = None
    evidence: Evidence


class AIFallbackResult(BaseModel):
    email: AIFallbackField | None = None
    phone: AIFallbackField | None = None
    person: AIFallbackField | None = None


def _extract_postcode(address: str | None) -> str | None:
    if not address:
        return None
    parts = [part.strip() for part in address.split(",") if part.strip()]
    if not parts:
        return None
    candidate = parts[-1]
    return candidate if any(char.isdigit() for char in candidate) else None


def needs_ai_fallback(record: EnrichmentRecord) -> bool:
    outreach = record.outreach
    return not (outreach.primary_email and outreach.primary_phone and outreach.primary_person)


def build_ai_fallback_input(
    *,
    raw_data: dict[str, Any],
    record: EnrichmentRecord,
    homepage_html: str | None,
    contact_page_html: str | None,
    homepage_url: str | None,
    contact_page_url: str | None,
) -> dict[str, Any]:
    return {
        "business_name": raw_data.get("title") or "",
        "website": raw_data.get("website"),
        "homepage_url": homepage_url,
        "contact_page_url": contact_page_url,
        "homepage_text": _html_to_text(homepage_html) if homepage_html else "",
        "contact_page_text": _html_to_text(contact_page_html) if contact_page_html else "",
        "deterministic_partial": record.model_dump(mode="json"),
    }


def _valid_ai_evidence(field: AIFallbackField) -> bool:
    page_source = field.evidence.page_source
    return bool(field.evidence.snippet.strip()) and page_source in {
        "homepage",
        "contact_page",
        "json_ld",
        "mailto_link",
        "footer",
    }


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Groq response did not contain a JSON object")
    return json.loads(stripped[start : end + 1])


def extract_domain(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    host = parsed.netloc.strip().lower()
    if not host:
        return None
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _normalize_date_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        for item in value:
            normalized = _normalize_date_value(item)
            if normalized:
                return normalized
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = str(value).strip()
    return text or None


def _normalize_postcode(postcode: str | None) -> str | None:
    if not postcode:
        return None
    normalized = re.sub(r"\s+", "", postcode).upper()
    return normalized or None


def _extract_postcode_from_text(text: str | None) -> str | None:
    if not text:
        return None
    match = UK_POSTCODE_PATTERN.search(text)
    return _normalize_postcode(match.group(1)) if match else None


def _name_to_tokens(name: str) -> list[str]:
    lowered = name.lower().replace("&", " and ")
    cleaned = re.sub(r"[^a-z0-9\s]+", " ", lowered)
    return [token for token in cleaned.split() if token]


def _remove_legal_suffixes(text: str) -> str:
    normalized = text
    changed = True
    while changed:
        changed = False
        for pattern in LEGAL_SUFFIX_PATTERNS:
            updated = re.sub(rf"\b{pattern}\b\s*$", "", normalized).strip()
            if updated != normalized:
                normalized = updated
                changed = True
    return normalized


def _derive_locality_terms(addresses: list[AddressRecord]) -> set[str]:
    locality_terms = set(GENERIC_LOCALITY_TOKENS)
    for address in addresses:
        parts = [part.strip() for part in address.full.split(",") if part.strip()]
        for part in parts[1:]:
            if _extract_postcode_from_text(part):
                continue
            for token in _name_to_tokens(part):
                if len(token) <= 2 or token.isdigit() or token in ADDRESS_NOISE_TOKENS:
                    continue
                locality_terms.add(token)
    return locality_terms


def normalize_company_name(
    name: str,
    *,
    strip_suffixes: bool = False,
    locality_terms: set[str] | None = None,
) -> str:
    normalized = " ".join(_name_to_tokens(name))
    if strip_suffixes:
        normalized = _remove_legal_suffixes(normalized)
        tokens = normalized.split()
        localities = locality_terms or set()
        while tokens and tokens[0] in localities:
            tokens = tokens[1:]
        while tokens and tokens[-1] in localities:
            tokens = tokens[:-1]
        normalized = " ".join(tokens)
    return " ".join(normalized.split())


def _normalize_domain_hint(url: str | None) -> str | None:
    domain = extract_domain(url)
    if not domain:
        return None
    host = domain.split(":")[0]
    first_label = host.split(".", 1)[0]
    tokens = _name_to_tokens(first_label)
    return "".join(tokens) or None


def _candidate_from_search_item(item: dict[str, Any]) -> CompaniesHouseCandidate:
    address = item.get("address") if isinstance(item.get("address"), dict) else {}
    return CompaniesHouseCandidate(
        title=str(item.get("title") or "").strip(),
        company_number=str(item.get("company_number") or "").strip() or None,
        company_status=str(item.get("company_status") or "").strip() or None,
        address_snippet=str(item.get("address_snippet") or "").strip() or None,
        address=address,
        raw=item,
    )


def _candidate_postcode(candidate: CompaniesHouseCandidate) -> str | None:
    postal_code = candidate.address.get("postal_code") if isinstance(candidate.address, dict) else None
    return _normalize_postcode(postal_code) or _extract_postcode_from_text(candidate.address_snippet)


def _score_candidate(
    *,
    scraped_name: str,
    locality_terms: set[str],
    trading_postcode: str | None,
    domain_hint: str | None,
    candidate: CompaniesHouseCandidate,
) -> CandidateEvaluation:
    normalized_scraped = normalize_company_name(scraped_name)
    normalized_scraped_stripped = normalize_company_name(
        scraped_name,
        strip_suffixes=True,
        locality_terms=locality_terms,
    )
    normalized_candidate = normalize_company_name(candidate.title)
    normalized_candidate_stripped = normalize_company_name(
        candidate.title,
        strip_suffixes=True,
        locality_terms=locality_terms,
    )
    candidate_postcode = _candidate_postcode(candidate)
    condensed_candidate = normalized_candidate_stripped.replace(" ", "")
    similarity = SequenceMatcher(None, normalized_scraped_stripped, normalized_candidate_stripped).ratio()

    if normalized_scraped and normalized_scraped == normalized_candidate:
        return CandidateEvaluation(
            candidate=candidate,
            method="exact_normalized",
            confidence="high",
            score=100,
            normalized_name=normalized_candidate,
            normalized_name_stripped=normalized_candidate_stripped,
        )
    if (
        normalized_scraped_stripped
        and normalized_scraped_stripped == normalized_candidate_stripped
    ):
        method: CompaniesHouseMatchMethod = "suffix_stripped_exact"
        confidence: MatchConfidence = "high"
        score = 90
        if trading_postcode and candidate_postcode and trading_postcode == candidate_postcode:
            method = "postcode_supported"
            score = 96
        return CandidateEvaluation(
            candidate=candidate,
            method=method,
            confidence=confidence,
            score=score,
            normalized_name=normalized_candidate,
            normalized_name_stripped=normalized_candidate_stripped,
        )
    if (
        trading_postcode
        and candidate_postcode
        and trading_postcode == candidate_postcode
        and similarity >= 0.72
    ):
        return CandidateEvaluation(
            candidate=candidate,
            method="postcode_supported",
            confidence="high",
            score=84,
            normalized_name=normalized_candidate,
            normalized_name_stripped=normalized_candidate_stripped,
        )
    if domain_hint and condensed_candidate and (condensed_candidate in domain_hint or domain_hint in condensed_candidate):
        return CandidateEvaluation(
            candidate=candidate,
            method="domain_supported",
            confidence="medium",
            score=76,
            normalized_name=normalized_candidate,
            normalized_name_stripped=normalized_candidate_stripped,
        )
    if similarity >= 0.93:
        return CandidateEvaluation(
            candidate=candidate,
            method="conservative_fuzzy",
            confidence="low",
            score=61,
            normalized_name=normalized_candidate,
            normalized_name_stripped=normalized_candidate_stripped,
        )
    return CandidateEvaluation(
        candidate=candidate,
        method="unmatched",
        confidence="ambiguous",
        score=0,
        normalized_name=normalized_candidate,
        normalized_name_stripped=normalized_candidate_stripped,
    )


def select_companies_house_match(
    *,
    scraped_name: str,
    addresses: list[AddressRecord],
    website_url: str | None,
    search_items: list[dict[str, Any]],
) -> CandidateEvaluation | None:
    locality_terms = _derive_locality_terms(addresses)
    trading_postcode = _normalize_postcode(addresses[0].postcode) if addresses else None
    domain_hint = _normalize_domain_hint(website_url)
    evaluations = [
        _score_candidate(
            scraped_name=scraped_name,
            locality_terms=locality_terms,
            trading_postcode=trading_postcode,
            domain_hint=domain_hint,
            candidate=_candidate_from_search_item(item),
        )
        for item in search_items
    ]
    evaluations = [evaluation for evaluation in evaluations if evaluation.score > 0]
    if not evaluations:
        return None
    evaluations.sort(key=lambda item: (item.score, item.confidence == "high"), reverse=True)
    top = evaluations[0]
    second = evaluations[1] if len(evaluations) > 1 else None
    if second and second.score >= top.score - 3:
        return None
    return top


def companies_house_search(query: str, *, api_key: str, items_per_page: int = 10) -> list[dict[str, Any]]:
    with httpx.Client(
        base_url="https://api.company-information.service.gov.uk",
        timeout=20.0,
        auth=(api_key, ""),
    ) as client:
        response = client.get(
            "/search/companies",
            params={"q": query, "items_per_page": items_per_page},
        )
        response.raise_for_status()
        payload = response.json()
    return payload.get("items") or []


def companies_house_company_profile(company_number: str, *, api_key: str) -> dict[str, Any]:
    with httpx.Client(
        base_url="https://api.company-information.service.gov.uk",
        timeout=20.0,
        auth=(api_key, ""),
    ) as client:
        response = client.get(f"/company/{company_number}")
        response.raise_for_status()
        return response.json()


def companies_house_officers(company_number: str, *, api_key: str) -> list[dict[str, Any]]:
    with httpx.Client(
        base_url="https://api.company-information.service.gov.uk",
        timeout=20.0,
        auth=(api_key, ""),
    ) as client:
        response = client.get(f"/company/{company_number}/officers")
        response.raise_for_status()
        payload = response.json()
    return payload.get("items") or []


def companies_house_pscs(company_number: str, *, api_key: str) -> list[dict[str, Any]]:
    with httpx.Client(
        base_url="https://api.company-information.service.gov.uk",
        timeout=20.0,
        auth=(api_key, ""),
    ) as client:
        response = client.get(f"/company/{company_number}/persons-with-significant-control")
        response.raise_for_status()
        payload = response.json()
    return payload.get("items") or []


def _build_registered_address(profile: dict[str, Any]) -> tuple[str | None, str | None]:
    registered = profile.get("registered_office_address")
    if not isinstance(registered, dict):
        return None, None
    ordered_keys = (
        "care_of",
        "premises",
        "address_line_1",
        "address_line_2",
        "locality",
        "region",
        "postal_code",
        "country",
    )
    parts = [str(registered.get(key)).strip() for key in ordered_keys if registered.get(key)]
    full = ", ".join(part for part in parts if part)
    return full or None, _normalize_postcode(registered.get("postal_code"))


def _append_review_flag(record: EnrichmentRecord, flag: str) -> None:
    if flag not in record.outreach.review_flags:
        record.outreach.review_flags.append(flag)


def apply_companies_house_data(
    *,
    record: EnrichmentRecord,
    raw_data: dict[str, Any],
    search_lookup: Any | None = None,
    profile_lookup: Any | None = None,
    officers_lookup: Any | None = None,
    psc_lookup: Any | None = None,
    api_key: str = "",
) -> tuple[EnrichmentRecord, str]:
    active_search_lookup = search_lookup
    active_profile_lookup = profile_lookup
    active_officers_lookup = officers_lookup
    active_psc_lookup = psc_lookup
    if active_search_lookup is None and api_key:
        active_search_lookup = lambda query: companies_house_search(query, api_key=api_key)
    if active_profile_lookup is None and api_key:
        active_profile_lookup = lambda company_number: companies_house_company_profile(company_number, api_key=api_key)
    if active_officers_lookup is None and api_key:
        active_officers_lookup = lambda company_number: companies_house_officers(company_number, api_key=api_key)
    if active_psc_lookup is None and api_key:
        active_psc_lookup = lambda company_number: companies_house_pscs(company_number, api_key=api_key)
    if active_search_lookup is None:
        return record, "pending"

    search_items = active_search_lookup(record.company.name_scraped)
    selected = select_companies_house_match(
        scraped_name=record.company.name_scraped,
        addresses=record.addresses,
        website_url=record.web.url_final,
        search_items=search_items,
    )
    if selected is None:
        record.company.match_method = "unmatched"
        record.company.match_confidence = "ambiguous"
        if search_items:
            _append_review_flag(record, "companies_house_ambiguous")
        return record, "done"

    if selected.confidence not in {"high", "medium"}:
        record.company.match_method = "unmatched"
        record.company.match_confidence = "ambiguous"
        _append_review_flag(record, "companies_house_low_confidence")
        return record, "done"

    candidate = selected.candidate
    record.company.match_method = selected.method
    record.company.match_confidence = selected.confidence
    record.company.name_registered = candidate.title or None
    record.company.companies_house_number = candidate.company_number
    record.company.companies_house_status = candidate.company_status
    if "companies_house" not in record.enrichment_sources_used:
        record.enrichment_sources_used.append("companies_house")

    trading_postcode = _normalize_postcode(record.addresses[0].postcode) if record.addresses else None
    if candidate.company_number and active_profile_lookup is not None:
        profile = active_profile_lookup(candidate.company_number)
        record.company.companies_house_status = (
            str(profile.get("company_status")).strip() or record.company.companies_house_status
        )
        record.company.incorporation_date = _normalize_date_value(profile.get("date_of_creation"))
        record.company.last_accounts_date = _normalize_date_value(
            ((profile.get("accounts") or {}).get("last_accounts") or {}).get("made_up_to")
        )
        record.company.accounts_overdue = bool((profile.get("accounts") or {}).get("overdue"))
        record.company.last_confirmation_statement = _normalize_date_value(
            ((profile.get("confirmation_statement") or {}).get("last_made_up_to"))
        )
        record.company.confirmation_statement_overdue = bool(
            (profile.get("confirmation_statement") or {}).get("overdue")
        )
        previous_names = profile.get("previous_company_names") or []
        record.company.previous_names = [
            str(item.get("name")).strip()
            for item in previous_names
            if isinstance(item, dict) and item.get("name")
        ]
        record.company.insolvency.flag = bool(profile.get("has_insolvency_history"))

        full_registered_address, registered_postcode = _build_registered_address(profile)
        if full_registered_address:
            flag = None
            if trading_postcode and registered_postcode and trading_postcode != registered_postcode:
                flag = "address_discrepancy"
                _append_review_flag(record, flag)
            record.addresses.append(
                AddressRecord(
                    type="registered",
                    source="companies_house",
                    full=full_registered_address,
                    postcode=registered_postcode,
                    flag=flag,
                )
            )

        if candidate.company_number and active_officers_lookup is not None:
            for officer in active_officers_lookup(candidate.company_number):
                if not isinstance(officer, dict) or not officer.get("name"):
                    continue
                role_name = str(officer.get("officer_role") or "").lower()
                inferred_role: ContactRole = "secretary" if "secretary" in role_name else "director"
                record.people.append(
                    PersonRecord(
                        name=str(officer["name"]).strip(),
                        role_inferred=inferred_role,
                        sources=["companies_house"],
                        companies_house_role=str(officer.get("officer_role") or "").strip() or None,
                        appointment_date=_normalize_date_value(officer.get("appointed_on")),
                        resigned=bool(officer.get("resigned_on")),
                        nationality=str(officer.get("nationality") or "").strip() or None,
                        occupation=str(officer.get("occupation") or "").strip() or None,
                    )
                )
        if candidate.company_number and active_psc_lookup is not None:
            for psc in active_psc_lookup(candidate.company_number):
                if not isinstance(psc, dict) or not psc.get("name"):
                    continue
                record.company.pscs.append(
                    PscRecord(
                        name=str(psc["name"]).strip(),
                        nature_of_control=[
                            str(value)
                            for value in (psc.get("natures_of_control") or [])
                            if str(value).strip()
                        ],
                        notified_on=_normalize_date_value(psc.get("notified_on")),
                    )
                )

    return record, "done"


def lookup_whois(domain: str) -> dict[str, str | None]:
    try:
        import whois  # type: ignore
    except ImportError:
        return {"whois_owner": None, "domain_registered": None, "domain_expires": None}

    try:
        result = whois.whois(domain)
    except Exception:
        return {"whois_owner": None, "domain_registered": None, "domain_expires": None}

    owner = (
        getattr(result, "org", None)
        or getattr(result, "registrant_name", None)
        or getattr(result, "name", None)
    )
    created = (
        getattr(result, "creation_date", None)
        or getattr(result, "creationdate", None)
    )
    expires = (
        getattr(result, "expiration_date", None)
        or getattr(result, "expiry_date", None)
        or getattr(result, "expires", None)
    )
    return {
        "whois_owner": str(owner).strip() if owner else None,
        "domain_registered": _normalize_date_value(created),
        "domain_expires": _normalize_date_value(expires),
    }


def lookup_mx(domain: str) -> bool | None:
    try:
        import dns.resolver  # type: ignore
    except ImportError:
        return None

    try:
        answers = dns.resolver.resolve(domain, "MX")
    except Exception:
        return False
    return bool(list(answers))


def apply_whois_and_mx(
    *,
    record: EnrichmentRecord,
    whois_lookup: Any | None = None,
    mx_lookup: Any | None = None,
) -> tuple[EnrichmentRecord, str]:
    domain = extract_domain(record.web.url_final)
    if not domain:
        return record, "failed"

    active_whois_lookup = whois_lookup or lookup_whois
    active_mx_lookup = mx_lookup or lookup_mx

    whois_data = active_whois_lookup(domain)
    record.web.whois_owner = whois_data.get("whois_owner")
    record.web.domain_registered = whois_data.get("domain_registered")
    record.web.domain_expires = whois_data.get("domain_expires")
    if any(value is not None for value in whois_data.values()):
        if "whois" not in record.enrichment_sources_used:
            record.enrichment_sources_used.append("whois")

    any_mx = False
    for email in record.emails:
        email_domain = email.address.split("@", 1)[1].lower() if "@" in email.address else domain
        mx_valid = active_mx_lookup(email_domain)
        email.mx_valid = mx_valid
        if email.syntax_valid and mx_valid is True:
            email.confidence = "medium"
        any_mx = any_mx or mx_valid is True

    return record, "done" if (any(value is not None for value in whois_data.values()) or any_mx or record.emails) else "failed"


def call_groq_ai_fallback(
    fallback_input: dict[str, Any],
    *,
    api_key: str,
    model: str,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    owns_client = client is None
    active_client = client or httpx.Client(
        base_url="https://api.groq.com",
        timeout=30.0,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        response = active_client.post(
            "/openai/v1/chat/completions",
            json={
                "model": model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You extract only missing business contact fields from supplied website text. "
                            "Never invent facts. Return JSON with optional keys email, phone, person. "
                            "Each returned field must contain value, optional role_inferred, and evidence "
                            "with snippet and page_source. Omit fields you cannot evidence."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(fallback_input),
                    },
                ],
            },
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        return _extract_json_object(content)
    finally:
        if owns_client:
            active_client.close()


def build_groq_ai_extractor(api_key: str, model: str) -> Any:
    def _extractor(fallback_input: dict[str, Any]) -> dict[str, Any]:
        return call_groq_ai_fallback(fallback_input, api_key=api_key, model=model)

    return _extractor


def _merge_ai_fallback(
    *,
    record: EnrichmentRecord,
    fallback_payload: dict[str, Any],
) -> tuple[EnrichmentRecord, bool]:
    parsed = AIFallbackResult.model_validate(fallback_payload)
    accepted = False

    if parsed.email and not record.outreach.primary_email and _valid_ai_evidence(parsed.email):
        record.emails.append(
            EmailRecord(
                address=parsed.email.value.lower(),
                role_inferred=parsed.email.role_inferred or "generic",
                sources=[parsed.email.evidence.page_source],
                source_count=1,
                syntax_valid=True,
                confidence="medium",
                primary=not any(item.primary for item in record.emails),
                evidence=[parsed.email.evidence],
            )
        )
        record.outreach.primary_email = parsed.email.value.lower()
        accepted = True

    if parsed.phone and not record.outreach.primary_phone and _valid_ai_evidence(parsed.phone):
        normalized_phone = _normalize_phone(parsed.phone.value)
        if normalized_phone:
            record.phones.append(
                PhoneRecord(
                    number=normalized_phone,
                    number_display=normalized_phone,
                    type="unknown",
                    role_inferred=parsed.phone.role_inferred or "secondary_line",
                    sources=[parsed.phone.evidence.page_source],
                    source_count=1,
                    validated=False,
                    primary=not any(item.primary for item in record.phones),
                    evidence=[parsed.phone.evidence],
                )
            )
            record.outreach.primary_phone = normalized_phone
            accepted = True

    if parsed.person and not record.outreach.primary_person and _valid_ai_evidence(parsed.person):
        record.people.append(
            PersonRecord(
                name=parsed.person.value,
                role_inferred=parsed.person.role_inferred or "unverified",
                sources=[parsed.person.evidence.page_source],
                context="ai fallback",
                evidence=[parsed.person.evidence],
            )
        )
        record.outreach.primary_person = parsed.person.value
        accepted = True

    record.outreach.ready = bool(
        record.outreach.primary_email or record.outreach.primary_phone or record.outreach.primary_person
    )
    return record, accepted


def build_enrichment_record(
    *,
    lead_id: str,
    raw_data: dict[str, Any],
    scraped_at: str | None = None,
    enriched_at: str | None = None,
    homepage_html: str | None = None,
    contact_page_html: str | None = None,
    homepage_url: str | None = None,
    contact_page_url: str | None = None,
    web_status: WebStatus = "unknown",
    response_time_ms: int | None = None,
) -> EnrichmentRecord:
    address = raw_data.get("address") or ""
    phone = raw_data.get("phone")
    website = raw_data.get("website")
    extracted = extract_contact_data(
        homepage_html=homepage_html,
        contact_page_html=contact_page_html,
        homepage_url=homepage_url or website,
        contact_page_url=contact_page_url,
    )

    normalized_phone = str(phone) if phone else None
    all_phones = _unique_preserve_order(([normalized_phone] if normalized_phone else []) + extracted.phones)
    all_emails = extracted.emails
    all_people = extracted.people

    phone_records: list[PhoneRecord] = []
    if normalized_phone:
        phone_records.append(
            PhoneRecord(
                number=normalized_phone,
                number_display=normalized_phone,
                type="unknown",
                role_inferred="main_line",
                sources=["google_listing"],
                source_count=1,
                validated=False,
                primary=True,
            )
        )
    for extracted_phone in all_phones:
        if normalized_phone and extracted_phone == normalized_phone:
            continue
        phone_records.append(
            PhoneRecord(
                number=extracted_phone,
                number_display=extracted_phone,
                type="unknown",
                role_inferred="secondary_line",
                sources=extracted.phone_sources.get(extracted_phone, ["homepage"]),
                source_count=len(extracted.phone_sources.get(extracted_phone, ["homepage"])),
                validated=False,
                primary=not phone_records,
            )
        )

    email_records = [
        EmailRecord(
            address=email,
            role_inferred="generic",
            sources=extracted.email_sources.get(email, ["homepage"]),
            source_count=len(extracted.email_sources.get(email, ["homepage"])),
            syntax_valid=True,
            confidence="low",
            primary=index == 0,
        )
        for index, email in enumerate(all_emails)
    ]

    person_records = [
        PersonRecord(
            name=person,
            role_inferred="unverified",
            sources=extracted.person_sources.get(person, ["homepage"]),
            context="deterministic website extraction",
        )
        for person in all_people
    ]

    enrichment_sources = ["google_listing"]
    if homepage_html:
        enrichment_sources.append("homepage")
    if contact_page_html:
        enrichment_sources.append("contact_page")
    if homepage_html or contact_page_html:
        enrichment_sources.append("website_parse")
    if homepage_html and extract_json_ld(homepage_html):
        enrichment_sources.append("json_ld")
    if contact_page_html and extract_json_ld(contact_page_html):
        enrichment_sources.append("json_ld")
    enrichment_sources = _unique_preserve_order(enrichment_sources)

    return EnrichmentRecord(
        business_id=lead_id,
        scraped_at=scraped_at or utc_now_iso(),
        enriched_at=enriched_at or utc_now_iso(),
        enrichment_sources_used=enrichment_sources,
        company=CompanyRecord(name_scraped=raw_data.get("title") or ""),
        addresses=[
            AddressRecord(
                type="trading",
                source="google_listing",
                full=address,
                postcode=_extract_postcode(address),
                lat=raw_data.get("latitude"),
                lng=raw_data.get("longitude"),
            )
        ]
        if address
        else [],
        people=person_records,
        phones=phone_records,
        emails=email_records,
        web=WebRecord(
            url_final=homepage_url or website,
            status=web_status,
            https=bool(str(homepage_url or website).startswith("https://"))
            if (homepage_url or website)
            else None,
            response_time_ms=response_time_ms,
        ),
        social=SocialRecord(
            google_rating=raw_data.get("rating"),
            google_review_count=raw_data.get("reviews_count"),
        ),
        outreach=OutreachRecord(
            primary_email=all_emails[0] if all_emails else None,
            primary_phone=all_phones[0] if all_phones else None,
            primary_person=_select_primary_person(person_records),
            ready=bool(all_emails or all_phones or _select_primary_person(person_records)),
        ),
    )


def run_phase2(
    project_id: str,
    *,
    db_path: str,
    fetcher: Any | None = None,
    ai_extractor: Any | None = None,
    whois_lookup: Any | None = None,
    mx_lookup: Any | None = None,
    batch_limit: int = 25,
) -> dict[str, Any]:
    reset_running_website_leads(project_id, db_path)
    processed = 0
    failed = 0
    claimed = 0
    settings = get_settings()

    def resolve_fetcher() -> Any:
        if fetcher is not None:
            return fetcher
        client = create_http_client()

        def _fetch(url: str) -> tuple[str, str]:
            return fetch_page(url, client)

        _fetch._shared_client = client  # type: ignore[attr-defined]
        return _fetch

    active_fetcher = resolve_fetcher()

    try:
        while claimed < batch_limit:
            lead = claim_next_pending_website_lead(project_id, db_path)
            if lead is None:
                break
            claimed += 1
            raw_data = json.loads(lead["raw_data"])
            website = raw_data.get("website")
            if not website:
                mark_lead_website_failed(lead["id"], db_path)
                failed += 1
                continue

            try:
                homepage_result = active_fetcher(str(website))
                contact_page_url = None
                contact_page_html = None
                if homepage_result.status in {"live", "redirect"}:
                    contact_links = extract_contact_links(homepage_result.html, homepage_result.url)
                    if contact_links:
                        contact_result = active_fetcher(contact_links[0])
                        if contact_result.status in {"live", "redirect"}:
                            contact_page_url = contact_result.url
                            contact_page_html = contact_result.html

                record = build_enrichment_record(
                    lead_id=lead["id"],
                    raw_data=raw_data,
                    scraped_at=lead.get("last_updated"),
                    homepage_html=homepage_result.html,
                    contact_page_html=contact_page_html,
                    homepage_url=homepage_result.url,
                    contact_page_url=contact_page_url,
                    web_status=homepage_result.status,
                    response_time_ms=homepage_result.response_time_ms,
                )
                ai_status = "done"
                if needs_ai_fallback(record):
                    active_ai_extractor = ai_extractor
                    if active_ai_extractor is None and settings.groq_api_key:
                        active_ai_extractor = build_groq_ai_extractor(
                            settings.groq_api_key,
                            settings.groq_model,
                        )
                    if active_ai_extractor is not None:
                        fallback_input = build_ai_fallback_input(
                            raw_data=raw_data,
                            record=record,
                            homepage_html=homepage_result.html,
                            contact_page_html=contact_page_html,
                            homepage_url=homepage_result.url,
                            contact_page_url=contact_page_url,
                        )
                        try:
                            merged_record, accepted = _merge_ai_fallback(
                                record=record,
                                fallback_payload=active_ai_extractor(fallback_input),
                            )
                            record = merged_record
                            ai_status = "done" if accepted else "failed"
                        except Exception:
                            ai_status = "failed"
                    else:
                        ai_status = "pending"
                record, whois_mx_status = apply_whois_and_mx(
                    record=record,
                    whois_lookup=whois_lookup,
                    mx_lookup=mx_lookup,
                )
                update_lead_website_enrichment(
                    lead_id=lead["id"],
                    enrichment_data=record.model_dump(mode="json"),
                    db_path=db_path,
                    website_status="done",
                    ai_fallback_status=ai_status,
                    whois_mx_status=whois_mx_status,
                )
                if homepage_result.status in {"live", "redirect", "dead", "error"}:
                    processed += 1
                else:
                    failed += 1
            except Exception:
                fallback_record = build_enrichment_record(
                    lead_id=lead["id"],
                    raw_data=raw_data,
                    scraped_at=lead.get("last_updated"),
                    homepage_url=str(website),
                    web_status="error",
                )
                update_lead_website_enrichment(
                    lead_id=lead["id"],
                    enrichment_data=fallback_record.model_dump(mode="json"),
                    db_path=db_path,
                    website_status="failed",
                    ai_fallback_status="pending",
                    whois_mx_status="pending",
                )
                failed += 1
    finally:
        shared_client = getattr(active_fetcher, "_shared_client", None)
        if shared_client is not None:
            shared_client.close()

    return {
        "project_id": project_id,
        "phase": "2",
        "stage": "website_extraction",
        "processed": processed,
        "failed": failed,
        "remaining": count_pending_website_leads(project_id, db_path),
    }


def run_companies_house_stage(
    project_id: str,
    *,
    db_path: str,
    search_lookup: Any | None = None,
    profile_lookup: Any | None = None,
    officers_lookup: Any | None = None,
    psc_lookup: Any | None = None,
    batch_limit: int = 25,
) -> dict[str, Any]:
    reset_running_companies_house_leads(project_id, db_path)
    settings = get_settings()
    api_key = settings.companies_house_api_key or ""

    active_search_lookup = search_lookup
    active_profile_lookup = profile_lookup
    active_officers_lookup = officers_lookup
    active_psc_lookup = psc_lookup

    if api_key:
        if active_search_lookup is None:
            active_search_lookup = lambda q: companies_house_search(q, api_key=api_key)
        if active_profile_lookup is None:
            active_profile_lookup = lambda cn: companies_house_company_profile(cn, api_key=api_key)
        if active_officers_lookup is None:
            active_officers_lookup = lambda cn: companies_house_officers(cn, api_key=api_key)
        if active_psc_lookup is None:
            active_psc_lookup = lambda cn: companies_house_pscs(cn, api_key=api_key)

    processed = 0
    failed = 0
    claimed = 0

    while claimed < batch_limit:
        lead = claim_next_pending_companies_house_lead(project_id, db_path)
        if lead is None:
            break
        claimed += 1

        raw_enrichment = lead.get("enrichment_data")
        if not raw_enrichment:
            update_lead_companies_house_enrichment(
                lead_id=lead["id"],
                enrichment_data={},
                companies_house_status="failed",
                db_path=db_path,
            )
            failed += 1
            continue

        try:
            enrichment_data = json.loads(raw_enrichment) if isinstance(raw_enrichment, str) else raw_enrichment
            record = EnrichmentRecord.model_validate(enrichment_data)
            raw_data = json.loads(lead["raw_data"]) if isinstance(lead["raw_data"], str) else (lead.get("raw_data") or {})

            record, ch_status = apply_companies_house_data(
                record=record,
                raw_data=raw_data,
                search_lookup=active_search_lookup,
                profile_lookup=active_profile_lookup,
                officers_lookup=active_officers_lookup,
                psc_lookup=active_psc_lookup,
            )
            update_lead_companies_house_enrichment(
                lead_id=lead["id"],
                enrichment_data=record.model_dump(mode="json"),
                companies_house_status=ch_status,
                db_path=db_path,
            )
            processed += 1
        except Exception:
            update_lead_companies_house_enrichment(
                lead_id=lead["id"],
                enrichment_data=json.loads(raw_enrichment) if isinstance(raw_enrichment, str) else {},
                companies_house_status="failed",
                db_path=db_path,
            )
            failed += 1

    return {
        "project_id": project_id,
        "phase": "2",
        "stage": "companies_house",
        "processed": processed,
        "failed": failed,
        "remaining": count_pending_companies_house_leads(project_id, db_path),
    }


# ---------------------------------------------------------------------------
# SMTP verification stage
# ---------------------------------------------------------------------------

_SMTP_MIN_INTERVAL: float = 1.0  # seconds between probes globally
_last_smtp_probe: float = 0.0    # module-level monotonic clock tracking


def _smtp_rate_limit() -> None:
    """Block until at least _SMTP_MIN_INTERVAL seconds have passed since the last probe."""
    global _last_smtp_probe
    elapsed = _time_module.monotonic() - _last_smtp_probe
    if elapsed < _SMTP_MIN_INTERVAL:
        _time_module.sleep(_SMTP_MIN_INTERVAL - elapsed)
    _last_smtp_probe = _time_module.monotonic()


def _resolve_mx_host(domain: str) -> str | None:
    """Return the highest-priority MX hostname for domain, or None if unavailable."""
    try:
        import dns.resolver  # type: ignore
        answers = sorted(dns.resolver.resolve(domain, "MX"), key=lambda r: r.preference)
        if not answers:
            return None
        return str(answers[0].exchange).rstrip(".")
    except Exception:
        return None


SmtpResult = Literal["smtp_verified_true", "smtp_verified_false", "smtp_unverifiable"]


def smtp_probe_email(
    email: str,
    *,
    timeout: float = 10.0,
    helo_domain: str = "scraper-probe.local",
) -> SmtpResult:
    """Probe a single email address via SMTP RCPT TO handshake.

    Rate-limited to _SMTP_MIN_INTERVAL seconds globally.
    Returns one of smtp_verified_true / smtp_verified_false / smtp_unverifiable.
    Never raises — all exceptions are absorbed into smtp_unverifiable.
    """
    _smtp_rate_limit()

    if "@" not in email:
        return "smtp_unverifiable"

    domain = email.split("@", 1)[1].lower()
    mx_host = _resolve_mx_host(domain)
    if not mx_host:
        return "smtp_unverifiable"

    try:
        with smtplib.SMTP(timeout=timeout) as smtp:
            smtp.connect(mx_host, 25)
            smtp.ehlo(helo_domain)
            # Some servers support VRFY; most honour RCPT TO in a dummy transaction
            smtp.mail("")
            code, _ = smtp.rcpt(email)
            smtp.rset()
            if code == 250:
                return "smtp_verified_true"
            elif code in {550, 551, 553}:
                return "smtp_verified_false"
            else:
                return "smtp_unverifiable"
    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, ConnectionRefusedError, OSError):
        # Connection-level failure → backoff then unverifiable (not a verdict on the address)
        _time_module.sleep(5.0)
        return "smtp_unverifiable"
    except Exception:
        return "smtp_unverifiable"


def apply_smtp_verification(
    *,
    record: EnrichmentRecord,
    probed_addresses: set[str],
    smtp_prober: Any | None = None,
) -> tuple[EnrichmentRecord, str, set[str]]:
    """Run SMTP probes for all unverified emails on a lead.

    Returns (updated_record, smtp_status, updated_probed_addresses).
    smtp_status is 'done' when all addresses were processed (even if unverifiable),
    'failed' only if an unexpected exception aborts the whole lead.

    Rules:
    - Never probe an address already in probed_addresses (no same-run retry).
    - smtp_verified_true  → confidence 'high',  smtp_verified = True
    - smtp_verified_false → confidence 'low',   smtp_verified = False
    - smtp_unverifiable   → keep existing confidence (MX-based medium preserved)
    """
    active_prober = smtp_prober if smtp_prober is not None else smtp_probe_email

    for email in record.emails:
        if email.address in probed_addresses:
            continue
        probed_addresses.add(email.address)

        result: SmtpResult = active_prober(email.address)
        email.smtp_result = result

        if result == "smtp_verified_true":
            email.smtp_verified = True
            email.confidence = "high"
        elif result == "smtp_verified_false":
            email.smtp_verified = False
            # Downgrade but don't wipe — the address might still be a role inbox
            if email.confidence in {"high", "very_high"}:
                email.confidence = "medium"
            else:
                email.confidence = "low"
        else:
            # smtp_unverifiable — preserve existing MX-based confidence
            email.smtp_verified = None

    return record, "done", probed_addresses


def run_smtp_stage(
    project_id: str,
    *,
    db_path: str,
    smtp_prober: Any | None = None,
    batch_limit: int = 25,
) -> dict[str, Any]:
    """Run the SMTP verification stage for a project.

    Resets stranded running leads, then claims and processes up to batch_limit leads.
    A module-level set tracks probed addresses so the same address is never probed
    twice within one call to this function.
    """
    reset_running_smtp_leads(project_id, db_path)

    probed_addresses: set[str] = set()
    processed = 0
    failed = 0
    claimed = 0

    while claimed < batch_limit:
        lead = claim_next_pending_smtp_lead(project_id, db_path)
        if lead is None:
            break
        claimed += 1

        raw_enrichment = lead.get("enrichment_data")
        if not raw_enrichment:
            update_lead_smtp_enrichment(
                lead_id=lead["id"],
                enrichment_data={},
                smtp_status="failed",
                db_path=db_path,
            )
            failed += 1
            continue

        try:
            enrichment_data = json.loads(raw_enrichment) if isinstance(raw_enrichment, str) else raw_enrichment
            record = EnrichmentRecord.model_validate(enrichment_data)

            record, smtp_status, probed_addresses = apply_smtp_verification(
                record=record,
                probed_addresses=probed_addresses,
                smtp_prober=smtp_prober,
            )
            update_lead_smtp_enrichment(
                lead_id=lead["id"],
                enrichment_data=record.model_dump(mode="json"),
                smtp_status=smtp_status,
                db_path=db_path,
            )
            processed += 1
        except Exception:
            update_lead_smtp_enrichment(
                lead_id=lead["id"],
                enrichment_data=json.loads(raw_enrichment) if isinstance(raw_enrichment, str) else {},
                smtp_status="failed",
                db_path=db_path,
            )
            failed += 1

    return {
        "project_id": project_id,
        "phase": "2",
        "stage": "smtp_verification",
        "processed": processed,
        "failed": failed,
        "remaining": count_pending_smtp_leads(project_id, db_path),
    }
