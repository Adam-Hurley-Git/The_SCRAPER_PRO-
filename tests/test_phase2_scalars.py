"""D8 — Indexed scalar extraction tests.

Verifies that primary_email, primary_phone, primary_person, and outreach_ready
are written to scalar columns after enrichment so leads can be filtered and
exported without parsing enrichment_data JSON.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from database import (
    create_project,
    get_connection,
    insert_leads_from_gosom_results,
    update_lead_website_enrichment,
    update_lead_companies_house_enrichment,
    update_lead_smtp_enrichment,
)
from pipeline.phase2_enrichment import build_enrichment_record


def _raw_lead() -> dict:
    return {
        "cid": str(uuid.uuid4()),
        "title": "Scalar Test Co",
        "address": "1 High Street, Swansea, SA1 1DP",
        "phone": "01792123456",
        "website": "https://example.co.uk",
        "latitude": 51.6193,
        "longitude": -3.9437,
    }


def _insert_lead(project_id: str, db_path: Path) -> tuple[str, dict]:
    raw = _raw_lead()
    insert_leads_from_gosom_results(
        project_id=project_id, cell_id="cell-1", results=[raw], db_path=db_path
    )
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM leads WHERE project_id = ? AND cid = ?",
            (project_id, raw["cid"]),
        ).fetchone()
    return row["id"], raw


def test_website_enrichment_writes_scalar_columns(temp_db: Path) -> None:
    project = create_project(
        name="Scalar Test", primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8", db_path=temp_db,
    )
    lead_id, raw = _insert_lead(project["id"], temp_db)
    record = build_enrichment_record(lead_id=lead_id, raw_data=raw)
    enrichment = record.model_dump(mode="json")
    enrichment["outreach"]["primary_email"] = "test@example.co.uk"
    enrichment["outreach"]["primary_phone"] = "01792123456"
    enrichment["outreach"]["ready"] = True

    update_lead_website_enrichment(
        lead_id=lead_id,
        enrichment_data=enrichment,
        db_path=temp_db,
        website_status="done",
    )

    # Query the scalar columns directly — no JSON parsing needed
    with get_connection(temp_db) as conn:
        row = conn.execute(
            "SELECT primary_email, primary_phone, outreach_ready FROM leads WHERE id = ?",
            (lead_id,),
        ).fetchone()

    assert row["primary_email"] == "test@example.co.uk"
    assert row["primary_phone"] == "01792123456"
    assert row["outreach_ready"] == 1


def test_companies_house_enrichment_writes_scalar_columns(temp_db: Path) -> None:
    project = create_project(
        name="CH Scalar Test", primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8", db_path=temp_db,
    )
    lead_id, raw = _insert_lead(project["id"], temp_db)
    record = build_enrichment_record(lead_id=lead_id, raw_data=raw)
    enrichment = record.model_dump(mode="json")
    enrichment["outreach"]["primary_person"] = "Robert Davies"
    enrichment["outreach"]["ready"] = True

    # Simulate website stage first
    update_lead_website_enrichment(
        lead_id=lead_id, enrichment_data=enrichment, db_path=temp_db, website_status="done",
    )
    # CH stage overwrites/extends scalars
    enrichment["outreach"]["primary_person"] = "Robert Davies"
    update_lead_companies_house_enrichment(
        lead_id=lead_id,
        enrichment_data=enrichment,
        companies_house_status="done",
        db_path=temp_db,
    )

    with get_connection(temp_db) as conn:
        row = conn.execute(
            "SELECT primary_person, outreach_ready FROM leads WHERE id = ?", (lead_id,)
        ).fetchone()

    assert row["primary_person"] == "Robert Davies"
    assert row["outreach_ready"] == 1


def test_smtp_enrichment_writes_scalar_columns(temp_db: Path) -> None:
    project = create_project(
        name="SMTP Scalar Test", primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8", db_path=temp_db,
    )
    lead_id, raw = _insert_lead(project["id"], temp_db)
    record = build_enrichment_record(lead_id=lead_id, raw_data=raw)
    enrichment = record.model_dump(mode="json")
    enrichment["outreach"]["primary_email"] = "smtp@example.co.uk"
    enrichment["outreach"]["ready"] = True

    update_lead_website_enrichment(
        lead_id=lead_id, enrichment_data=enrichment, db_path=temp_db, website_status="done",
    )
    update_lead_smtp_enrichment(
        lead_id=lead_id,
        enrichment_data=enrichment,
        smtp_status="done",
        db_path=temp_db,
    )

    with get_connection(temp_db) as conn:
        row = conn.execute(
            "SELECT primary_email, outreach_ready, smtp_status FROM leads WHERE id = ?",
            (lead_id,),
        ).fetchone()

    assert row["primary_email"] == "smtp@example.co.uk"
    assert row["outreach_ready"] == 1
    assert row["smtp_status"] == "done"


def test_scalar_columns_can_filter_outreach_ready_leads_without_json(temp_db: Path) -> None:
    """The key D8 assertion: outreach-ready leads are queryable via scalar column only."""
    project = create_project(
        name="Filter Test", primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8", db_path=temp_db,
    )
    lead_id, raw = _insert_lead(project["id"], temp_db)
    record = build_enrichment_record(lead_id=lead_id, raw_data=raw)
    enrichment = record.model_dump(mode="json")
    enrichment["outreach"]["primary_email"] = "ready@example.co.uk"
    enrichment["outreach"]["ready"] = True

    update_lead_website_enrichment(
        lead_id=lead_id, enrichment_data=enrichment, db_path=temp_db, website_status="done",
    )

    with get_connection(temp_db) as conn:
        ready_rows = conn.execute(
            "SELECT id, primary_email FROM leads WHERE project_id = ? AND outreach_ready = 1",
            (project["id"],),
        ).fetchall()

    assert len(ready_rows) == 1
    assert ready_rows[0]["primary_email"] == "ready@example.co.uk"
