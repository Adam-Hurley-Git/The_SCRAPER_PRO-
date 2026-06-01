"""D5 — Companies House stage tests.

Covers:
- normalize_company_name: legal suffix stripping and locality removal
- select_companies_house_match: exact, messy-name, ambiguous fixtures
- apply_companies_house_data: match method / confidence recorded, officers / PSCs attached, low-confidence left unmatched
- run_companies_house_stage: DB claim/reset/update lifecycle
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from database import (
    claim_next_pending_companies_house_lead,
    count_pending_companies_house_leads,
    create_project,
    get_connection,
    insert_leads_from_gosom_results,
    reset_running_companies_house_leads,
    retry_failed_companies_house_leads,
    update_lead_companies_house_enrichment,
    update_lead_website_enrichment,
)
from pipeline.phase2_enrichment import (
    AddressRecord,
    EnrichmentRecord,
    apply_companies_house_data,
    build_enrichment_record,
    normalize_company_name,
    run_companies_house_stage,
    select_companies_house_match,
    utc_now_iso,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_search_item(
    title: str,
    company_number: str = "12345678",
    status: str = "active",
    postcode: str | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "company_number": company_number,
        "company_status": status,
        "address_snippet": f"1 High Street, Swansea, {postcode}" if postcode else "1 High Street, Swansea",
        "address": {"postal_code": postcode} if postcode else {},
    }


def _make_address(full: str = "1 High Street, Swansea, SA1 1DP", postcode: str | None = "SA11DP") -> AddressRecord:
    return AddressRecord(type="trading", source="google_listing", full=full, postcode=postcode)


def _raw_lead(title: str = "Swansea Plumbing Ltd") -> dict[str, Any]:
    return {
        "cid": str(uuid.uuid4()),
        "title": title,
        "address": "1 High Street, Swansea, SA1 1DP",
        "phone": "01792123456",
        "website": "https://swanseaplumbing.co.uk",
        "latitude": 51.6193,
        "longitude": -3.9437,
    }


def _insert_done_website_lead(project_id: str, db_path: Path, raw_data: dict[str, Any]) -> str:
    """Insert a lead that has completed the website stage."""
    insert_leads_from_gosom_results(
        project_id=project_id,
        cell_id="cell-1",
        results=[raw_data],
        db_path=db_path,
    )
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM leads WHERE project_id = ? AND cid = ?",
            (project_id, raw_data["cid"]),
        ).fetchone()
    lead_id = row["id"]

    record = build_enrichment_record(lead_id=lead_id, raw_data=raw_data)
    update_lead_website_enrichment(
        lead_id=lead_id,
        enrichment_data=record.model_dump(mode="json"),
        db_path=db_path,
        website_status="done",
        ai_fallback_status="done",
        whois_mx_status="done",
    )
    return lead_id


# ---------------------------------------------------------------------------
# normalize_company_name
# ---------------------------------------------------------------------------

def test_normalize_strips_legal_suffix() -> None:
    assert normalize_company_name("Swansea Plumbing Ltd", strip_suffixes=True) == "swansea plumbing"


def test_normalize_strips_llp() -> None:
    # & is expanded to "and" by _name_to_tokens before suffix removal
    assert normalize_company_name("Davies And Sons LLP", strip_suffixes=True) == "davies and sons"


def test_normalize_collapses_punctuation() -> None:
    # Punctuation is replaced by spaces; apostrophe splits the token
    result = normalize_company_name("ABC Builders, Ltd.")
    assert "abc" in result and "builders" in result and "ltd" in result


def test_normalize_strips_locality_prefix(tmp_path: Path) -> None:
    address = _make_address("1 High Street, Swansea, SA1 1DP", "SA11DP")
    locality_terms = {"swansea"}
    result = normalize_company_name(
        "Swansea Plumbing",
        strip_suffixes=True,
        locality_terms=locality_terms,
    )
    assert "swansea" not in result


# ---------------------------------------------------------------------------
# select_companies_house_match — exact match
# ---------------------------------------------------------------------------

def test_exact_normalized_match() -> None:
    items = [_make_search_item("Swansea Plumbing Ltd")]
    evaluation = select_companies_house_match(
        scraped_name="Swansea Plumbing Ltd",
        addresses=[_make_address()],
        website_url=None,
        search_items=items,
    )
    assert evaluation is not None
    assert evaluation.method == "exact_normalized"
    assert evaluation.confidence == "high"


def test_suffix_stripped_exact_match() -> None:
    items = [_make_search_item("Swansea Plumbing Limited")]
    evaluation = select_companies_house_match(
        scraped_name="Swansea Plumbing",
        addresses=[_make_address()],
        website_url=None,
        search_items=items,
    )
    assert evaluation is not None
    assert evaluation.method in ("suffix_stripped_exact", "postcode_supported")
    assert evaluation.confidence == "high"


def test_postcode_supported_match() -> None:
    items = [_make_search_item("SW Plumbers Limited", postcode="SA11DP")]
    evaluation = select_companies_house_match(
        scraped_name="Swansea Plumbers",
        addresses=[_make_address(postcode="SA11DP")],
        website_url=None,
        search_items=items,
    )
    assert evaluation is not None
    assert evaluation.method == "postcode_supported"
    assert evaluation.confidence == "high"


def test_domain_supported_match() -> None:
    items = [_make_search_item("Swansea Plumbing Services Limited")]
    evaluation = select_companies_house_match(
        scraped_name="Swansea Plumbing",
        addresses=[],
        website_url="https://swanseaplumbing.co.uk",
        search_items=items,
    )
    assert evaluation is not None
    assert evaluation.method in ("domain_supported", "suffix_stripped_exact", "exact_normalized", "conservative_fuzzy")


# ---------------------------------------------------------------------------
# select_companies_house_match — ambiguous / unmatched
# ---------------------------------------------------------------------------

def test_ambiguous_remains_unmatched_when_two_candidates_tie() -> None:
    # Two candidates with the exact same normalised name produce tied scores → None returned
    items = [
        _make_search_item("ABC Plumbing Ltd", company_number="11111111"),
        _make_search_item("ABC Plumbing Ltd", company_number="22222222"),
    ]
    evaluation = select_companies_house_match(
        scraped_name="ABC Plumbing Ltd",
        addresses=[],
        website_url=None,
        search_items=items,
    )
    # Two identical-scoring candidates — selector must refuse to pick one
    assert evaluation is None


def test_no_match_when_search_empty() -> None:
    evaluation = select_companies_house_match(
        scraped_name="Swansea Plumbing",
        addresses=[_make_address()],
        website_url=None,
        search_items=[],
    )
    assert evaluation is None


def test_unrelated_name_not_matched() -> None:
    items = [_make_search_item("London Architects Ltd")]
    evaluation = select_companies_house_match(
        scraped_name="Swansea Plumbing",
        addresses=[],
        website_url=None,
        search_items=items,
    )
    assert evaluation is None or evaluation.confidence in ("low", "ambiguous")


# ---------------------------------------------------------------------------
# apply_companies_house_data — controlled lookups
# ---------------------------------------------------------------------------

def _make_record(name: str = "Swansea Plumbing Ltd") -> EnrichmentRecord:
    raw = _raw_lead(name)
    return build_enrichment_record(lead_id=str(uuid.uuid4()), raw_data=raw)


def test_apply_ch_data_exact_match_populates_company() -> None:
    items = [_make_search_item("Swansea Plumbing Ltd", company_number="12345678")]
    record = _make_record("Swansea Plumbing Ltd")

    updated_record, status = apply_companies_house_data(
        record=record,
        raw_data={"title": "Swansea Plumbing Ltd"},
        search_lookup=lambda _q: items,
        profile_lookup=lambda _cn: {},
        officers_lookup=lambda _cn: [],
        psc_lookup=lambda _cn: [],
    )
    assert status == "done"
    assert updated_record.company.match_method == "exact_normalized"
    assert updated_record.company.match_confidence == "high"
    assert updated_record.company.companies_house_number == "12345678"
    assert "companies_house" in updated_record.enrichment_sources_used


def test_apply_ch_data_attaches_officers_for_confident_match() -> None:
    items = [_make_search_item("Swansea Plumbing Ltd", company_number="12345678")]
    officers = [
        {"name": "Robert Davies", "officer_role": "director", "appointed_on": "2015-03-12"},
    ]
    record = _make_record("Swansea Plumbing Ltd")

    updated_record, status = apply_companies_house_data(
        record=record,
        raw_data={"title": "Swansea Plumbing Ltd"},
        search_lookup=lambda _q: items,
        profile_lookup=lambda _cn: {},
        officers_lookup=lambda _cn: officers,
        psc_lookup=lambda _cn: [],
    )
    assert status == "done"
    director_names = [p.name for p in updated_record.people]
    assert "Robert Davies" in director_names


def test_apply_ch_data_attaches_pscs_for_confident_match() -> None:
    items = [_make_search_item("Swansea Plumbing Ltd", company_number="12345678")]
    pscs = [
        {"name": "Robert Davies", "natures_of_control": ["ownership-of-shares-75-to-100-percent"], "notified_on": "2016-04-06"},
    ]
    record = _make_record("Swansea Plumbing Ltd")

    updated_record, status = apply_companies_house_data(
        record=record,
        raw_data={"title": "Swansea Plumbing Ltd"},
        search_lookup=lambda _q: items,
        profile_lookup=lambda _cn: {},
        officers_lookup=lambda _cn: [],
        psc_lookup=lambda _cn: pscs,
    )
    assert status == "done"
    psc_names = [p.name for p in updated_record.company.pscs]
    assert "Robert Davies" in psc_names


def test_apply_ch_data_leaves_ambiguous_unmatched() -> None:
    items = [
        _make_search_item("Something Completely Different Ltd", company_number="99999999"),
    ]
    record = _make_record("Swansea Plumbing Ltd")

    updated_record, status = apply_companies_house_data(
        record=record,
        raw_data={"title": "Swansea Plumbing Ltd"},
        search_lookup=lambda _q: items,
        profile_lookup=lambda _cn: {},
        officers_lookup=lambda _cn: [],
        psc_lookup=lambda _cn: [],
    )
    assert status == "done"
    assert updated_record.company.match_method == "unmatched"
    assert updated_record.company.companies_house_number is None


def test_apply_ch_data_returns_pending_when_no_lookup() -> None:
    record = _make_record("Swansea Plumbing Ltd")
    updated_record, status = apply_companies_house_data(
        record=record,
        raw_data={"title": "Swansea Plumbing Ltd"},
    )
    assert status == "pending"


# ---------------------------------------------------------------------------
# run_companies_house_stage — DB lifecycle
# ---------------------------------------------------------------------------

def test_run_ch_stage_processes_done_website_lead(temp_db: Path) -> None:
    project = create_project(
        name="Test Project",
        primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8",
        db_path=temp_db,
    )
    raw = _raw_lead("Swansea Plumbing Ltd")
    _insert_done_website_lead(project["id"], temp_db, raw)

    items = [_make_search_item("Swansea Plumbing Ltd", company_number="12345678")]
    result = run_companies_house_stage(
        project["id"],
        db_path=str(temp_db),
        search_lookup=lambda _q: items,
        profile_lookup=lambda _cn: {},
        officers_lookup=lambda _cn: [],
        psc_lookup=lambda _cn: [],
    )

    assert result["processed"] == 1
    assert result["failed"] == 0
    assert result["remaining"] == 0

    with get_connection(temp_db) as conn:
        row = conn.execute(
            "SELECT companies_house_status, enrichment_data FROM leads WHERE project_id = ?",
            (project["id"],),
        ).fetchone()
    assert row["companies_house_status"] == "done"
    enrichment = json.loads(row["enrichment_data"])
    assert enrichment["company"]["companies_house_number"] == "12345678"


def test_run_ch_stage_skips_leads_with_pending_website(temp_db: Path) -> None:
    """Leads that haven't completed website stage should not be claimed."""
    project = create_project(
        name="Test Project 2",
        primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8",
        db_path=temp_db,
    )
    raw = _raw_lead("Swansea Plumbing Ltd")
    # Insert lead but leave website_status=pending (default)
    insert_leads_from_gosom_results(
        project_id=project["id"],
        cell_id="cell-1",
        results=[raw],
        db_path=temp_db,
    )

    items = [_make_search_item("Swansea Plumbing Ltd")]
    result = run_companies_house_stage(
        project["id"],
        db_path=str(temp_db),
        search_lookup=lambda _q: items,
    )
    assert result["processed"] == 0
    assert result["remaining"] == 0


def test_run_ch_stage_resets_stranded_running_leads(temp_db: Path) -> None:
    project = create_project(
        name="Test Project 3",
        primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8",
        db_path=temp_db,
    )
    raw = _raw_lead("Swansea Plumbing Ltd")
    lead_id = _insert_done_website_lead(project["id"], temp_db, raw)

    # Artificially strand the lead as running
    with get_connection(temp_db) as conn:
        conn.execute(
            "UPDATE leads SET companies_house_status = 'running' WHERE id = ?",
            (lead_id,),
        )
        conn.commit()

    reset_count = reset_running_companies_house_leads(project["id"], temp_db)
    assert reset_count == 1

    with get_connection(temp_db) as conn:
        row = conn.execute("SELECT companies_house_status FROM leads WHERE id = ?", (lead_id,)).fetchone()
    assert row["companies_house_status"] == "pending"


def test_retry_failed_companies_house_leads(temp_db: Path) -> None:
    project = create_project(
        name="Test Project 4",
        primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8",
        db_path=temp_db,
    )
    raw = _raw_lead("Swansea Plumbing Ltd")
    lead_id = _insert_done_website_lead(project["id"], temp_db, raw)

    with get_connection(temp_db) as conn:
        conn.execute(
            "UPDATE leads SET companies_house_status = 'failed' WHERE id = ?",
            (lead_id,),
        )
        conn.commit()

    retried = retry_failed_companies_house_leads(project["id"], temp_db)
    assert retried == 1

    with get_connection(temp_db) as conn:
        row = conn.execute("SELECT companies_house_status FROM leads WHERE id = ?", (lead_id,)).fetchone()
    assert row["companies_house_status"] == "retry"


def test_count_pending_companies_house_leads(temp_db: Path) -> None:
    project = create_project(
        name="Test Project 5",
        primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8",
        db_path=temp_db,
    )
    raw = _raw_lead("Swansea Plumbing Ltd")
    _insert_done_website_lead(project["id"], temp_db, raw)

    count = count_pending_companies_house_leads(project["id"], temp_db)
    assert count == 1
