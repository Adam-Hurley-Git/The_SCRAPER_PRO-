"""F1+F2 — Full pipeline orchestration and pipeline_runs logging tests."""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from database import (
    complete_pipeline_run,
    create_project,
    get_connection,
    list_pipeline_runs,
    start_pipeline_run,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_api_client(db_path: Path):
    from fastapi.testclient import TestClient
    from config import AppSettings
    import main as app_module
    settings = AppSettings(scraper_db_path=db_path)
    return TestClient(app_module.create_app(settings_override=settings))


# ---------------------------------------------------------------------------
# F2 — pipeline_runs table
# ---------------------------------------------------------------------------

def test_start_and_complete_pipeline_run(temp_db: Path) -> None:
    project = create_project(
        name="Run Log Test", primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8", db_path=temp_db,
    )
    run_id = start_pipeline_run(project["id"], phase=1, db_path=temp_db)
    assert run_id

    with get_connection(temp_db) as conn:
        row = conn.execute("SELECT * FROM pipeline_runs WHERE id = ?", (run_id,)).fetchone()
    assert row["status"] == "running"
    assert row["phase"] == 1

    complete_pipeline_run(
        run_id,
        status="done",
        records_total=10,
        records_done=8,
        records_failed=2,
        db_path=temp_db,
    )

    with get_connection(temp_db) as conn:
        row = conn.execute("SELECT * FROM pipeline_runs WHERE id = ?", (run_id,)).fetchone()
    assert row["status"] == "done"
    assert row["records_total"] == 10
    assert row["records_done"] == 8
    assert row["records_failed"] == 2
    assert row["completed_at"] is not None


def test_list_pipeline_runs_returns_all_runs(temp_db: Path) -> None:
    project = create_project(
        name="Run List Test", primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8", db_path=temp_db,
    )
    run1 = start_pipeline_run(project["id"], phase=1, db_path=temp_db)
    run2 = start_pipeline_run(project["id"], phase=2, db_path=temp_db)
    runs = list_pipeline_runs(project["id"], temp_db)
    assert len(runs) == 2
    run_ids = {r["id"] for r in runs}
    assert run1 in run_ids
    assert run2 in run_ids


def test_pipeline_runs_isolated_by_project(temp_db: Path) -> None:
    p1 = create_project(
        name="P1", primary_term="test", bbox="51.5,51.6,-3.9,-3.8", db_path=temp_db
    )
    p2 = create_project(
        name="P2", primary_term="test", bbox="51.5,51.6,-3.9,-3.8", db_path=temp_db
    )
    start_pipeline_run(p1["id"], phase=1, db_path=temp_db)
    start_pipeline_run(p2["id"], phase=1, db_path=temp_db)

    runs_p1 = list_pipeline_runs(p1["id"], temp_db)
    runs_p2 = list_pipeline_runs(p2["id"], temp_db)
    assert len(runs_p1) == 1
    assert len(runs_p2) == 1


# ---------------------------------------------------------------------------
# F1 — API endpoints
# ---------------------------------------------------------------------------

def test_api_run_all_returns_202(temp_db: Path) -> None:
    from unittest.mock import patch
    project_id = create_project(
        name="Run All", primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8", db_path=temp_db,
    )["id"]
    client = _build_api_client(temp_db)
    # Patch the module-level pipeline runner so the background task completes immediately
    with patch("main.run_full_pipeline", return_value=None):
        response = client.post(f"/api/projects/{project_id}/run")
    assert response.status_code == 202
    assert response.json()["status"] == "started"


def test_api_stop_returns_202(temp_db: Path) -> None:
    project_id = create_project(
        name="Stop Test", primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8", db_path=temp_db,
    )["id"]
    client = _build_api_client(temp_db)
    response = client.post(f"/api/projects/{project_id}/stop")
    assert response.status_code == 202
    assert response.json()["status"] == "stop_requested"


def test_api_list_runs_returns_empty_for_new_project(temp_db: Path) -> None:
    project_id = create_project(
        name="Empty Runs", primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8", db_path=temp_db,
    )["id"]
    client = _build_api_client(temp_db)
    response = client.get(f"/api/projects/{project_id}/runs")
    assert response.status_code == 200
    assert response.json()["runs"] == []


def test_api_list_runs_returns_logged_runs(temp_db: Path) -> None:
    project_id = create_project(
        name="Has Runs", primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8", db_path=temp_db,
    )["id"]
    run_id = start_pipeline_run(project_id, phase=1, db_path=temp_db)
    complete_pipeline_run(run_id, status="done", db_path=temp_db)

    client = _build_api_client(temp_db)
    response = client.get(f"/api/projects/{project_id}/runs")
    assert response.status_code == 200
    runs = response.json()["runs"]
    assert len(runs) == 1
    assert runs[0]["status"] == "done"
    assert runs[0]["phase"] == 1


def test_api_run_all_404_for_missing_project(temp_db: Path) -> None:
    client = _build_api_client(temp_db)
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.post(f"/api/projects/{missing}/run").status_code == 404
    assert client.post(f"/api/projects/{missing}/stop").status_code == 404
    assert client.get(f"/api/projects/{missing}/runs").status_code == 404
