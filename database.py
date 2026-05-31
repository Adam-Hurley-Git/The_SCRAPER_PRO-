from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DEFAULT_DB_PATH = DATA_DIR / "scraper.db"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT,
    primary_term TEXT,
    extra_terms TEXT,
    bbox TEXT,
    colour TEXT,
    min_cell_degrees REAL DEFAULT 0.005,
    created_at TEXT,
    archived INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cells (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    bbox TEXT,
    depth INTEGER DEFAULT 0,
    status TEXT,
    result_count INTEGER,
    cap_hit INTEGER DEFAULT 0,
    gosom_job_id TEXT,
    created_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS leads (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    cid TEXT,
    raw_data TEXT,
    enrichment_data TEXT,
    enrichment_version TEXT,
    source TEXT DEFAULT 'gosom',
    website_status TEXT DEFAULT 'pending',
    ai_fallback_status TEXT DEFAULT 'pending',
    whois_mx_status TEXT DEFAULT 'pending',
    companies_house_status TEXT DEFAULT 'pending',
    smtp_status TEXT DEFAULT 'pending',
    output_status TEXT DEFAULT 'pending',
    primary_email TEXT,
    primary_phone TEXT,
    primary_person TEXT,
    outreach_ready INTEGER DEFAULT 0,
    first_seen_cell TEXT,
    last_updated TEXT,
    UNIQUE(project_id, cid)
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    phase INTEGER,
    stage INTEGER,
    status TEXT,
    records_total INTEGER,
    records_done INTEGER,
    records_failed INTEGER,
    started_at TEXT,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_cells_project_id ON cells(project_id);
CREATE INDEX IF NOT EXISTS idx_cells_status ON cells(status);
CREATE INDEX IF NOT EXISTS idx_leads_project_id ON leads(project_id);
CREATE INDEX IF NOT EXISTS idx_leads_cid ON leads(cid);
CREATE INDEX IF NOT EXISTS idx_leads_website_status ON leads(website_status);
CREATE INDEX IF NOT EXISTS idx_leads_ai_fallback_status ON leads(ai_fallback_status);
CREATE INDEX IF NOT EXISTS idx_leads_whois_mx_status ON leads(whois_mx_status);
CREATE INDEX IF NOT EXISTS idx_leads_companies_house_status ON leads(companies_house_status);
CREATE INDEX IF NOT EXISTS idx_leads_smtp_status ON leads(smtp_status);
CREATE INDEX IF NOT EXISTS idx_leads_output_status ON leads(output_status);
CREATE INDEX IF NOT EXISTS idx_leads_primary_email ON leads(primary_email);
CREATE INDEX IF NOT EXISTS idx_leads_primary_phone ON leads(primary_phone);
CREATE INDEX IF NOT EXISTS idx_leads_primary_person ON leads(primary_person);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_project_id ON pipeline_runs(project_id);
"""


def get_db_path() -> Path:
    return Path(os.getenv("SCRAPER_DB_PATH", DEFAULT_DB_PATH))


def ensure_data_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "jobs").mkdir(parents=True, exist_ok=True)


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    resolved = Path(db_path) if db_path else get_db_path()
    conn = sqlite3.connect(resolved)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | Path | None = None) -> Path:
    ensure_data_dirs()
    resolved = Path(db_path) if db_path else get_db_path()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with get_connection(resolved) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    return resolved


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def _project_summary_select() -> str:
    return """
    SELECT
        p.*,
        COALESCE(lead_stats.lead_count, 0) AS lead_count,
        COALESCE(cell_stats.cell_count, 0) AS cell_count
    FROM projects p
    LEFT JOIN (
        SELECT project_id, COUNT(*) AS lead_count
        FROM leads
        GROUP BY project_id
    ) AS lead_stats ON lead_stats.project_id = p.id
    LEFT JOIN (
        SELECT project_id, COUNT(*) AS cell_count
        FROM cells
        GROUP BY project_id
    ) AS cell_stats ON cell_stats.project_id = p.id
    """


def list_projects(
    db_path: str | Path | None = None,
    *,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    query = _project_summary_select()
    if not include_archived:
        query += " WHERE p.archived = 0"
    query += " ORDER BY p.created_at DESC, p.name COLLATE NOCASE ASC"

    with get_connection(db_path) as conn:
        rows = conn.execute(query).fetchall()
    return [dict(row) for row in rows]


def get_project(
    project_id: str,
    db_path: str | Path | None = None,
    *,
    include_archived: bool = False,
) -> dict[str, Any] | None:
    query = _project_summary_select() + " WHERE p.id = ?"
    params: list[Any] = [project_id]
    if not include_archived:
        query += " AND p.archived = 0"

    with get_connection(db_path) as conn:
        row = conn.execute(query, params).fetchone()
    return row_to_dict(row)


def create_project(
    *,
    name: str,
    primary_term: str,
    bbox: str,
    extra_terms: list[str] | None = None,
    colour: str | None = None,
    min_cell_degrees: float = 0.005,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    project_id = str(uuid.uuid4())
    created_at = utc_now_iso()
    serialized_extra_terms = json.dumps(extra_terms or [])

    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO projects (
                id, name, primary_term, extra_terms, bbox, colour,
                min_cell_degrees, created_at, archived
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                project_id,
                name,
                primary_term,
                serialized_extra_terms,
                bbox,
                colour,
                min_cell_degrees,
                created_at,
            ),
        )
        conn.commit()

    project = get_project(project_id, db_path, include_archived=True)
    if project is None:
        raise RuntimeError("Created project could not be loaded")
    return project


def archive_project(project_id: str, db_path: str | Path | None = None) -> bool:
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "UPDATE projects SET archived = 1 WHERE id = ? AND archived = 0",
            (project_id,),
        )
        conn.commit()
    return cursor.rowcount > 0
