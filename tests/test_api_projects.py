from __future__ import annotations

import json

from fastapi.testclient import TestClient

from config import AppSettings
from main import create_app


def build_client(temp_db):
    settings = AppSettings(scraper_db_path=temp_db)
    return TestClient(create_app(settings))


def test_project_crud_and_archive_hides_default_listing(temp_db) -> None:
    with build_client(temp_db) as client:
        create_response = client.post(
            "/api/projects",
            json={
                "name": "Plumbers Swansea",
                "primary_term": "plumbers",
                "bbox": "51.5900,-4.0300,51.6700,-3.8900",
                "extra_terms": ["drainage engineer", " emergency plumbing "],
                "min_cell_degrees": 0.01,
            },
        )

        assert create_response.status_code == 201
        project = create_response.json()
        assert json.loads(project["extra_terms"]) == ["drainage engineer", "emergency plumbing"]
        assert project["bbox"] == "51.5900,-4.0300,51.6700,-3.8900"

        project_id = project["id"]

        list_response = client.get("/api/projects")
        assert list_response.status_code == 200
        assert [item["id"] for item in list_response.json()["projects"]] == [project_id]

        get_response = client.get(f"/api/projects/{project_id}")
        assert get_response.status_code == 200
        assert get_response.json()["name"] == "Plumbers Swansea"

        delete_response = client.delete(f"/api/projects/{project_id}")
        assert delete_response.status_code == 204

        list_after_delete = client.get("/api/projects")
        assert list_after_delete.status_code == 200
        assert list_after_delete.json()["projects"] == []

        get_after_delete = client.get(f"/api/projects/{project_id}")
        assert get_after_delete.status_code == 404


def test_ui_routes_render_active_project_context(temp_db) -> None:
    with build_client(temp_db) as client:
        created = client.post(
            "/api/projects",
            json={
                "name": "Roofers Swansea",
                "primary_term": "roofers",
                "bbox": "51.60,-4.00,51.66,-3.92",
            },
        ).json()

        response = client.get(f"/ui/pipeline?project_id={created['id']}")

        assert response.status_code == 200
        assert "Pipeline" in response.text
        assert "Tracks B-C" in response.text
