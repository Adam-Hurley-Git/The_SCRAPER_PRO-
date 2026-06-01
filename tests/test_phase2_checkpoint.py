"""D7 — Phase 2 checkpoint engine tests.

Covers:
- run_phase2_all_stages: chains website → CH → SMTP, returns combined summary
- Resume: each stage resets stranded 'running' rows to 'pending' on re-entry
- retry_phase2_stage: re-queues only failed leads for the named stage
- get_phase2_status: per-stage count map
- /api/projects/{id}/pipeline/status endpoint
- /api/projects/{id}/phases/2/run, /resume, /retry endpoints
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from database import (
    create_project,
    get_connection,
    get_phase2_status,
    insert_leads_from_gosom_results,
    retry_failed_leads_for_stage,
    update_lead_website_enrichment,
)
from pipeline.phase2_enrichment import (
    build_enrichment_record,
    retry_phase2_stage,
    run_phase2_all_stages,
    utc_now_iso,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _raw_lead(cid: str | None = None) -> dict[str, Any]:
    return {
        "cid": cid or str(uuid.uuid4()),
        "title": "Test Company",
        "address": "1 High Street, Swansea, SA1 1DP",
        "phone": "01792123456",
        "website": "https://example.co.uk",
        "latitude": 51.6193,
        "longitude": -3.9437,
    }


def _insert_done_website_lead(project_id: str, db_path: Path, raw: dict[str, Any]) -> str:
    insert_leads_from_gosom_results(
        project_id=project_id, cell_id="cell-1", results=[raw], db_path=db_path
    )
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM leads WHERE project_id = ? AND cid = ?",
            (project_id, raw["cid"]),
        ).fetchone()
    lead_id = row["id"]
    record = build_enrichment_record(lead_id=lead_id, raw_data=raw)
    update_lead_website_enrichment(
        lead_id=lead_id,
        enrichment_data=record.model_dump(mode="json"),
        db_path=db_path,
        website_status="done",
        ai_fallback_status="done",
        whois_mx_status="done",
    )
    return lead_id


def _no_op_fetcher(url: str):
    from pipeline.phase2_enrichment import PageFetchResult
    return PageFetchResult(url=url, html="<html></html>", status="live", response_time_ms=1)


# ---------------------------------------------------------------------------
# get_phase2_status
# ---------------------------------------------------------------------------

def test_get_phase2_status_returns_per_stage_counts(temp_db: Path) -> None:
    project = create_project(
        name="Status Test", primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8", db_path=temp_db,
    )
    raw = _raw_lead()
    insert_leads_from_gosom_results(
        project_id=project["id"], cell_id="cell-1", results=[raw], db_path=temp_db
    )
    status = get_phase2_status(project["id"], temp_db)

    assert "website_status" in status
    assert "companies_house_status" in status
    assert "smtp_status" in status
    assert status["total_leads"] == 1
    # All stages should start at pending
    assert status["website_status"].get("pending", 0) == 1
    assert status["companies_house_status"].get("pending", 0) == 1
    assert status["smtp_status"].get("pending", 0) == 1


# ---------------------------------------------------------------------------
# retry_failed_leads_for_stage
# ---------------------------------------------------------------------------

def test_retry_failed_leads_for_stage_requeues_only_failed(temp_db: Path) -> None:
    project = create_project(
        name="Retry Stage Test", primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8", db_path=temp_db,
    )
    raw1 = _raw_lead(cid="cid-fail")
    raw2 = _raw_lead(cid="cid-done")
    insert_leads_from_gosom_results(
        project_id=project["id"], cell_id="cell-1",
        results=[raw1, raw2], db_path=temp_db,
    )
    with get_connection(temp_db) as conn:
        conn.execute(
            "UPDATE leads SET smtp_status = 'failed' WHERE cid = ?", ("cid-fail",)
        )
        conn.execute(
            "UPDATE leads SET smtp_status = 'done' WHERE cid = ?", ("cid-done",)
        )
        conn.commit()

    retried = retry_failed_leads_for_stage(project["id"], "smtp_status", temp_db)
    assert retried == 1

    with get_connection(temp_db) as conn:
        fail_row = conn.execute(
            "SELECT smtp_status FROM leads WHERE cid = ?", ("cid-fail",)
        ).fetchone()
        done_row = conn.execute(
            "SELECT smtp_status FROM leads WHERE cid = ?", ("cid-done",)
        ).fetchone()
    assert fail_row["smtp_status"] == "retry"
    assert done_row["smtp_status"] == "done"  # untouched


def test_retry_failed_leads_invalid_stage_raises(temp_db: Path) -> None:
    project = create_project(
        name="Invalid Stage", primary_term="test",
        bbox="51.5,51.6,-3.9,-3.8", db_path=temp_db,
    )
    with pytest.raises(ValueError, match="Unknown stage column"):
        retry_failed_leads_for_stage(project["id"], "nonexistent_status", temp_db)


# ---------------------------------------------------------------------------
# retry_phase2_stage
# ---------------------------------------------------------------------------

def test_retry_phase2_stage_requeues_failed_and_returns_status(temp_db: Path) -> None:
    project = create_project(
        name="Retry Phase2", primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8", db_path=temp_db,
    )
    raw = _raw_lead()
    insert_leads_from_gosom_results(
        project_id=project["id"], cell_id="cell-1", results=[raw], db_path=temp_db
    )
    with get_connection(temp_db) as conn:
        conn.execute("UPDATE leads SET smtp_status = 'failed'")
        conn.commit()

    result = retry_phase2_stage(project["id"], "smtp", db_path=str(temp_db))
    assert result["retried"] == 1
    assert "status" in result


def test_retry_phase2_stage_unknown_stage_raises(temp_db: Path) -> None:
    project = create_project(
        name="Bad Stage", primary_term="test",
        bbox="51.5,51.6,-3.9,-3.8", db_path=temp_db,
    )
    with pytest.raises(ValueError, match="Unknown stage"):
        retry_phase2_stage(project["id"], "bad_stage", db_path=str(temp_db))


# ---------------------------------------------------------------------------
# run_phase2_all_stages — orchestration
# ---------------------------------------------------------------------------

def test_run_phase2_all_stages_returns_combined_summary(temp_db: Path) -> None:
    project = create_project(
        name="All Stages", primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8", db_path=temp_db,
    )
    raw = _raw_lead()
    insert_leads_from_gosom_results(
        project_id=project["id"], cell_id="cell-1", results=[raw], db_path=temp_db
    )

    result = run_phase2_all_stages(
        project["id"],
        db_path=str(temp_db),
        fetcher=_no_op_fetcher,
        search_lookup=lambda _q: [],  # no CH match → unmatched (done)
        smtp_prober=lambda _addr: "smtp_unverifiable",
    )

    assert "website" in result
    assert "companies_house" in result
    assert "smtp" in result
    assert "status" in result
    assert result["phase"] == "2"


def test_run_phase2_all_stages_resume_resets_stranded_website_running(temp_db: Path) -> None:
    """If website_status is stranded at 'running', a fresh run resets it to pending."""
    project = create_project(
        name="Resume Test", primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8", db_path=temp_db,
    )
    raw = _raw_lead()
    insert_leads_from_gosom_results(
        project_id=project["id"], cell_id="cell-1", results=[raw], db_path=temp_db
    )
    # Artificially strand the lead
    with get_connection(temp_db) as conn:
        conn.execute("UPDATE leads SET website_status = 'running'")
        conn.commit()

    run_phase2_all_stages(
        project["id"],
        db_path=str(temp_db),
        fetcher=_no_op_fetcher,
        search_lookup=lambda _q: [],
        smtp_prober=lambda _addr: "smtp_unverifiable",
    )

    with get_connection(temp_db) as conn:
        row = conn.execute("SELECT website_status FROM leads").fetchone()
    # Should be 'done' — runner reset it to pending, then processed it
    assert row["website_status"] == "done"


def test_run_phase2_all_stages_resume_resets_stranded_ch_running(temp_db: Path) -> None:
    """If companies_house_status is stranded at 'running', a fresh run resets it."""
    project = create_project(
        name="CH Resume Test", primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8", db_path=temp_db,
    )
    raw = _raw_lead()
    lead_id = _insert_done_website_lead(project["id"], temp_db, raw)

    # Artificially strand CH stage
    with get_connection(temp_db) as conn:
        conn.execute("UPDATE leads SET companies_house_status = 'running' WHERE id = ?", (lead_id,))
        conn.commit()

    run_phase2_all_stages(
        project["id"],
        db_path=str(temp_db),
        fetcher=_no_op_fetcher,
        search_lookup=lambda _q: [],
        smtp_prober=lambda _addr: "smtp_unverifiable",
    )

    with get_connection(temp_db) as conn:
        row = conn.execute("SELECT companies_house_status FROM leads WHERE id = ?", (lead_id,)).fetchone()
    assert row["companies_house_status"] == "done"


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

def _build_api_client(db_path: Path):
    from fastapi.testclient import TestClient
    from config import AppSettings
    import main as app_module
    settings = AppSettings(scraper_db_path=db_path)
    test_app = app_module.create_app(settings_override=settings)
    return TestClient(test_app)


def test_api_pipeline_status_returns_coverage_and_phase2(temp_db: Path) -> None:
    project_id = create_project(
        name="API Status", primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8", db_path=temp_db,
    )["id"]
    client = _build_api_client(temp_db)
    response = client.get(f"/api/projects/{project_id}/pipeline/status")
    assert response.status_code == 200
    data = response.json()
    assert "coverage" in data
    assert "phase2" in data
    assert data["project_id"] == project_id


def test_api_phase2_run_starts_background_task(temp_db: Path) -> None:
    project_id = create_project(
        name="API Run", primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8", db_path=temp_db,
    )["id"]
    client = _build_api_client(temp_db)
    response = client.post(f"/api/projects/{project_id}/phases/2/run")
    assert response.status_code == 202
    assert response.json()["status"] == "started"


def test_api_phase2_resume_starts_background_task(temp_db: Path) -> None:
    project_id = create_project(
        name="API Resume", primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8", db_path=temp_db,
    )["id"]
    client = _build_api_client(temp_db)
    response = client.post(f"/api/projects/{project_id}/phases/2/resume")
    assert response.status_code == 202
    assert response.json()["status"] == "resuming"


def test_api_phase2_retry_requeues_failed(temp_db: Path) -> None:
    project_id = create_project(
        name="API Retry", primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8", db_path=temp_db,
    )["id"]
    raw = _raw_lead()
    insert_leads_from_gosom_results(
        project_id=project_id, cell_id="cell-1", results=[raw], db_path=temp_db
    )
    with get_connection(temp_db) as conn:
        conn.execute("UPDATE leads SET smtp_status = 'failed'")
        conn.commit()

    client = _build_api_client(temp_db)
    response = client.post(
        f"/api/projects/{project_id}/phases/2/retry",
        json={"stage": "smtp"},
    )
    assert response.status_code == 200
    assert response.json()["retried"] == 1


def test_api_phase2_retry_rejects_invalid_stage(temp_db: Path) -> None:
    project_id = create_project(
        name="API Bad Stage", primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8", db_path=temp_db,
    )["id"]
    client = _build_api_client(temp_db)
    response = client.post(
        f"/api/projects/{project_id}/phases/2/retry",
        json={"stage": "not_a_real_stage"},
    )
    assert response.status_code == 400


def test_api_endpoints_return_404_for_missing_project(temp_db: Path) -> None:
    client = _build_api_client(temp_db)
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/projects/{missing}/pipeline/status").status_code == 404
    assert client.post(f"/api/projects/{missing}/phases/2/run").status_code == 404
    assert client.post(f"/api/projects/{missing}/phases/2/resume").status_code == 404
    assert client.post(
        f"/api/projects/{missing}/phases/2/retry", json={"stage": "smtp"}
    ).status_code == 404
