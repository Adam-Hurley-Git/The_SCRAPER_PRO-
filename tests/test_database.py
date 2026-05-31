import sqlite3

from database import get_connection


def test_schema_initializes_core_tables(temp_db) -> None:
    with get_connection(temp_db) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    assert {"projects", "cells", "leads", "pipeline_runs"} <= tables


def test_duplicate_project_cid_insert_is_blocked(temp_db) -> None:
    with get_connection(temp_db) as conn:
        conn.execute(
            "INSERT INTO leads (id, project_id, cid, raw_data, last_updated) VALUES (?, ?, ?, ?, ?)",
            ("lead-1", "project-1", "cid-123", "{}", "2026-06-01T00:00:00Z"),
        )

        try:
            conn.execute(
                "INSERT INTO leads (id, project_id, cid, raw_data, last_updated) VALUES (?, ?, ?, ?, ?)",
                ("lead-2", "project-1", "cid-123", "{}", "2026-06-01T00:00:01Z"),
            )
        except sqlite3.IntegrityError:
            duplicate_blocked = True
        else:
            duplicate_blocked = False

    assert duplicate_blocked is True
