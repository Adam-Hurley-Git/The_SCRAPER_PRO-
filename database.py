from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from coverage import BBox, format_bbox, parse_bbox


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


def ensure_initial_cell(
    project_id: str,
    bbox: str,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM cells
            WHERE project_id = ?
            ORDER BY depth ASC, created_at ASC
            LIMIT 1
            """,
            (project_id,),
        ).fetchone()
        if row is None:
            cell_id = str(uuid.uuid4())
            created_at = utc_now_iso()
            conn.execute(
                """
                INSERT INTO cells (
                    id, project_id, bbox, depth, status, result_count, cap_hit, gosom_job_id,
                    created_at, completed_at
                )
                VALUES (?, ?, ?, 0, 'pending', NULL, 0, NULL, ?, NULL)
                """,
                (cell_id, project_id, bbox, created_at),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM cells WHERE id = ?", (cell_id,)).fetchone()
    result = row_to_dict(row)
    if result is None:
        raise RuntimeError("Initial cell could not be created")
    return result


def reset_running_cells(project_id: str, db_path: str | Path | None = None) -> int:
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE cells
            SET status = 'pending'
            WHERE project_id = ? AND status = 'running'
            """,
            (project_id,),
        )
        conn.commit()
    return cursor.rowcount


def claim_next_pending_cell(project_id: str, db_path: str | Path | None = None) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT *
            FROM cells
            WHERE project_id = ? AND status = 'pending'
            ORDER BY depth ASC, created_at ASC, id ASC
            LIMIT 1
            """,
            (project_id,),
        ).fetchone()
        if row is None:
            conn.commit()
            return None

        conn.execute(
            "UPDATE cells SET status = 'running' WHERE id = ?",
            (row["id"],),
        )
        conn.commit()
        claimed = conn.execute("SELECT * FROM cells WHERE id = ?", (row["id"],)).fetchone()
    return row_to_dict(claimed)


def complete_cell(
    *,
    cell_id: str,
    result_count: int,
    cap_hit: bool,
    gosom_job_id: str | None,
    db_path: str | Path | None = None,
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE cells
            SET status = 'completed',
                result_count = ?,
                cap_hit = ?,
                gosom_job_id = ?,
                completed_at = ?
            WHERE id = ?
            """,
            (result_count, int(cap_hit), gosom_job_id, utc_now_iso(), cell_id),
        )
        conn.commit()


def fail_cell(
    *,
    cell_id: str,
    gosom_job_id: str | None,
    db_path: str | Path | None = None,
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE cells
            SET status = 'failed',
                gosom_job_id = ?,
                completed_at = ?
            WHERE id = ?
            """,
            (gosom_job_id, utc_now_iso(), cell_id),
        )
        conn.commit()


def insert_child_cells(
    project_id: str,
    parent_bbox: BBox,
    depth: int,
    child_bboxes: list[BBox],
    db_path: str | Path | None = None,
) -> int:
    created_at = utc_now_iso()
    inserted = 0

    with get_connection(db_path) as conn:
        for child_bbox in child_bboxes:
            serialized_bbox = format_bbox(child_bbox)
            exists = conn.execute(
                """
                SELECT 1
                FROM cells
                WHERE project_id = ? AND depth = ? AND bbox = ?
                """,
                (project_id, depth, serialized_bbox),
            ).fetchone()
            if exists:
                continue

            conn.execute(
                """
                INSERT INTO cells (
                    id, project_id, bbox, depth, status, result_count, cap_hit, gosom_job_id,
                    created_at, completed_at
                )
                VALUES (?, ?, ?, ?, 'pending', NULL, 0, NULL, ?, NULL)
                """,
                (str(uuid.uuid4()), project_id, serialized_bbox, depth, created_at),
            )
            inserted += 1
        conn.commit()

    return inserted


def insert_leads_from_gosom_results(
    *,
    project_id: str,
    cell_id: str,
    results: list[dict[str, Any]],
    db_path: str | Path | None = None,
) -> dict[str, int]:
    inserted = 0
    duplicates = 0

    with get_connection(db_path) as conn:
        for item in results:
            cid = str(item.get("cid") or "").strip()
            if not cid:
                continue

            cursor = conn.execute(
                """
                INSERT INTO leads (
                    id, project_id, cid, raw_data, source, website_status, ai_fallback_status,
                    whois_mx_status, companies_house_status, smtp_status, output_status,
                    primary_email, primary_phone, primary_person, outreach_ready,
                    first_seen_cell, last_updated
                )
                VALUES (?, ?, ?, ?, 'gosom', 'pending', 'pending', 'pending', 'pending',
                        'pending', 'pending', NULL, NULL, NULL, 0, ?, ?)
                ON CONFLICT(project_id, cid) DO NOTHING
                """,
                (
                    str(uuid.uuid4()),
                    project_id,
                    cid,
                    json.dumps(item),
                    cell_id,
                    utc_now_iso(),
                ),
            )
            if cursor.rowcount:
                inserted += 1
            else:
                duplicates += 1
        conn.commit()

    return {"inserted": inserted, "duplicates": duplicates}


def get_phase2_status(project_id: str, db_path: str | Path | None = None) -> dict[str, Any]:
    """Return per-stage lead counts for the Phase 2 pipeline dashboard."""
    stages = ("website_status", "ai_fallback_status", "whois_mx_status", "companies_house_status", "smtp_status")
    status: dict[str, Any] = {}
    with get_connection(db_path) as conn:
        for stage_col in stages:
            rows = conn.execute(
                f"""
                SELECT {stage_col} AS stage_status, COUNT(*) AS lead_count
                FROM leads
                WHERE project_id = ?
                GROUP BY {stage_col}
                """,
                (project_id,),
            ).fetchall()
            status[stage_col] = {row["stage_status"]: row["lead_count"] for row in rows}
        total_row = conn.execute(
            "SELECT COUNT(*) AS total FROM leads WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    status["total_leads"] = int(total_row["total"]) if total_row else 0
    return status


def retry_failed_leads_for_stage(
    project_id: str,
    stage_column: str,
    db_path: str | Path | None = None,
) -> int:
    """Re-queue all failed leads for one Phase 2 stage column into 'retry'."""
    allowed = {
        "website_status",
        "ai_fallback_status",
        "whois_mx_status",
        "companies_house_status",
        "smtp_status",
    }
    if stage_column not in allowed:
        raise ValueError(f"Unknown stage column: {stage_column!r}")
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            f"""
            UPDATE leads
            SET {stage_column} = 'retry',
                last_updated = ?
            WHERE project_id = ? AND {stage_column} = 'failed'
            """,
            (utc_now_iso(), project_id),
        )
        conn.commit()
    return cursor.rowcount


def list_output_pending_leads(
    project_id: str,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return all leads ready for Phase 3 output (output_status pending or retry)."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM leads
            WHERE project_id = ?
              AND output_status IN ('pending', 'retry')
            ORDER BY last_updated ASC, id ASC
            """,
            (project_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def reset_running_output_leads(project_id: str, db_path: str | Path | None = None) -> int:
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE leads
            SET output_status = 'pending',
                last_updated = ?
            WHERE project_id = ? AND output_status = 'running'
            """,
            (utc_now_iso(), project_id),
        )
        conn.commit()
    return cursor.rowcount


def mark_leads_output_done(
    lead_ids: list[str],
    db_path: str | Path | None = None,
) -> int:
    if not lead_ids:
        return 0
    placeholders = ",".join("?" for _ in lead_ids)
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            f"""
            UPDATE leads
            SET output_status = 'done',
                last_updated = ?
            WHERE id IN ({placeholders})
            """,
            [utc_now_iso(), *lead_ids],
        )
        conn.commit()
    return cursor.rowcount


def mark_leads_output_failed(
    lead_ids: list[str],
    db_path: str | Path | None = None,
) -> int:
    if not lead_ids:
        return 0
    placeholders = ",".join("?" for _ in lead_ids)
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            f"""
            UPDATE leads
            SET output_status = 'failed',
                last_updated = ?
            WHERE id IN ({placeholders})
            """,
            [utc_now_iso(), *lead_ids],
        )
        conn.commit()
    return cursor.rowcount


def get_output_status(project_id: str, db_path: str | Path | None = None) -> dict[str, Any]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT output_status AS status, COUNT(*) AS count
            FROM leads
            WHERE project_id = ?
            GROUP BY output_status
            """,
            (project_id,),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) AS total FROM leads WHERE project_id = ?", (project_id,)
        ).fetchone()
    return {
        "counts": {row["status"]: row["count"] for row in rows},
        "total": int(total["total"]) if total else 0,
    }


def retry_failed_output_leads(project_id: str, db_path: str | Path | None = None) -> int:
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE leads
            SET output_status = 'retry',
                last_updated = ?
            WHERE project_id = ? AND output_status = 'failed'
            """,
            (utc_now_iso(), project_id),
        )
        conn.commit()
    return cursor.rowcount


def check_duplicate_cids(project_id: str, db_path: str | Path | None = None) -> list[str]:
    """Return a list of CIDs that appear more than once in the project (should be empty)."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT cid, COUNT(*) AS count
            FROM leads
            WHERE project_id = ?
            GROUP BY cid
            HAVING COUNT(*) > 1
            """,
            (project_id,),
        ).fetchall()
    return [row["cid"] for row in rows]


def list_leads_for_website_enrichment(
    project_id: str,
    db_path: str | Path | None = None,
    *,
    limit: int = 25,
) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM leads
            WHERE project_id = ?
              AND website_status IN ('pending', 'retry')
            ORDER BY last_updated ASC, id ASC
            LIMIT ?
            """,
            (project_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def count_pending_website_leads(project_id: str, db_path: str | Path | None = None) -> int:
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS lead_count
            FROM leads
            WHERE project_id = ?
              AND website_status IN ('pending', 'retry')
            """,
            (project_id,),
        ).fetchone()
    return int(row["lead_count"]) if row is not None else 0


def reset_running_website_leads(project_id: str, db_path: str | Path | None = None) -> int:
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE leads
            SET website_status = 'pending',
                last_updated = ?
            WHERE project_id = ? AND website_status = 'running'
            """,
            (utc_now_iso(), project_id),
        )
        conn.commit()
    return cursor.rowcount


def claim_next_pending_website_lead(
    project_id: str,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT *
            FROM leads
            WHERE project_id = ?
              AND website_status IN ('pending', 'retry')
            ORDER BY last_updated ASC, id ASC
            LIMIT 1
            """,
            (project_id,),
        ).fetchone()
        if row is None:
            conn.commit()
            return None

        conn.execute(
            """
            UPDATE leads
            SET website_status = 'running',
                last_updated = ?
            WHERE id = ?
            """,
            (utc_now_iso(), row["id"]),
        )
        conn.commit()
        claimed = conn.execute("SELECT * FROM leads WHERE id = ?", (row["id"],)).fetchone()
    return row_to_dict(claimed)


def retry_failed_website_leads(project_id: str, db_path: str | Path | None = None) -> int:
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE leads
            SET website_status = 'retry',
                last_updated = ?
            WHERE project_id = ? AND website_status = 'failed'
            """,
            (utc_now_iso(), project_id),
        )
        conn.commit()
    return cursor.rowcount


def update_lead_website_enrichment(
    *,
    lead_id: str,
    enrichment_data: dict[str, Any],
    db_path: str | Path | None = None,
    website_status: str = "done",
    ai_fallback_status: str | None = None,
    whois_mx_status: str | None = None,
) -> None:
    outreach = enrichment_data.get("outreach") or {}
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE leads
            SET enrichment_data = ?,
                enrichment_version = ?,
                website_status = ?,
                ai_fallback_status = COALESCE(?, ai_fallback_status),
                whois_mx_status = COALESCE(?, whois_mx_status),
                primary_email = ?,
                primary_phone = ?,
                primary_person = ?,
                outreach_ready = ?,
                last_updated = ?
            WHERE id = ?
            """,
            (
                json.dumps(enrichment_data),
                enrichment_data.get("pipeline_version"),
                website_status,
                ai_fallback_status,
                whois_mx_status,
                outreach.get("primary_email"),
                outreach.get("primary_phone"),
                outreach.get("primary_person"),
                1 if outreach.get("ready") else 0,
                utc_now_iso(),
                lead_id,
            ),
        )
        conn.commit()


def reset_running_companies_house_leads(project_id: str, db_path: str | Path | None = None) -> int:
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE leads
            SET companies_house_status = 'pending',
                last_updated = ?
            WHERE project_id = ? AND companies_house_status = 'running'
            """,
            (utc_now_iso(), project_id),
        )
        conn.commit()
    return cursor.rowcount


def claim_next_pending_companies_house_lead(
    project_id: str,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT *
            FROM leads
            WHERE project_id = ?
              AND website_status = 'done'
              AND companies_house_status IN ('pending', 'retry')
            ORDER BY last_updated ASC, id ASC
            LIMIT 1
            """,
            (project_id,),
        ).fetchone()
        if row is None:
            conn.commit()
            return None
        conn.execute(
            """
            UPDATE leads
            SET companies_house_status = 'running',
                last_updated = ?
            WHERE id = ?
            """,
            (utc_now_iso(), row["id"]),
        )
        conn.commit()
        claimed = conn.execute("SELECT * FROM leads WHERE id = ?", (row["id"],)).fetchone()
    return row_to_dict(claimed)


def count_pending_companies_house_leads(project_id: str, db_path: str | Path | None = None) -> int:
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS lead_count
            FROM leads
            WHERE project_id = ?
              AND website_status = 'done'
              AND companies_house_status IN ('pending', 'retry')
            """,
            (project_id,),
        ).fetchone()
    return int(row["lead_count"]) if row is not None else 0


def update_lead_companies_house_enrichment(
    *,
    lead_id: str,
    enrichment_data: dict[str, Any],
    companies_house_status: str,
    db_path: str | Path | None = None,
) -> None:
    outreach = enrichment_data.get("outreach") or {}
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE leads
            SET enrichment_data = ?,
                companies_house_status = ?,
                primary_email = COALESCE(?, primary_email),
                primary_phone = COALESCE(?, primary_phone),
                primary_person = COALESCE(?, primary_person),
                outreach_ready = ?,
                last_updated = ?
            WHERE id = ?
            """,
            (
                json.dumps(enrichment_data),
                companies_house_status,
                outreach.get("primary_email"),
                outreach.get("primary_phone"),
                outreach.get("primary_person"),
                1 if outreach.get("ready") else 0,
                utc_now_iso(),
                lead_id,
            ),
        )
        conn.commit()


def retry_failed_companies_house_leads(project_id: str, db_path: str | Path | None = None) -> int:
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE leads
            SET companies_house_status = 'retry',
                last_updated = ?
            WHERE project_id = ? AND companies_house_status = 'failed'
            """,
            (utc_now_iso(), project_id),
        )
        conn.commit()
    return cursor.rowcount


def reset_running_smtp_leads(project_id: str, db_path: str | Path | None = None) -> int:
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE leads
            SET smtp_status = 'pending',
                last_updated = ?
            WHERE project_id = ? AND smtp_status = 'running'
            """,
            (utc_now_iso(), project_id),
        )
        conn.commit()
    return cursor.rowcount


def claim_next_pending_smtp_lead(
    project_id: str,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT *
            FROM leads
            WHERE project_id = ?
              AND website_status = 'done'
              AND smtp_status IN ('pending', 'retry')
            ORDER BY last_updated ASC, id ASC
            LIMIT 1
            """,
            (project_id,),
        ).fetchone()
        if row is None:
            conn.commit()
            return None
        conn.execute(
            """
            UPDATE leads
            SET smtp_status = 'running',
                last_updated = ?
            WHERE id = ?
            """,
            (utc_now_iso(), row["id"]),
        )
        conn.commit()
        claimed = conn.execute("SELECT * FROM leads WHERE id = ?", (row["id"],)).fetchone()
    return row_to_dict(claimed)


def count_pending_smtp_leads(project_id: str, db_path: str | Path | None = None) -> int:
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS lead_count
            FROM leads
            WHERE project_id = ?
              AND website_status = 'done'
              AND smtp_status IN ('pending', 'retry')
            """,
            (project_id,),
        ).fetchone()
    return int(row["lead_count"]) if row is not None else 0


def update_lead_smtp_enrichment(
    *,
    lead_id: str,
    enrichment_data: dict[str, Any],
    smtp_status: str,
    db_path: str | Path | None = None,
) -> None:
    outreach = enrichment_data.get("outreach") or {}
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE leads
            SET enrichment_data = ?,
                smtp_status = ?,
                primary_email = COALESCE(?, primary_email),
                primary_phone = COALESCE(?, primary_phone),
                primary_person = COALESCE(?, primary_person),
                outreach_ready = ?,
                last_updated = ?
            WHERE id = ?
            """,
            (
                json.dumps(enrichment_data),
                smtp_status,
                outreach.get("primary_email"),
                outreach.get("primary_phone"),
                outreach.get("primary_person"),
                1 if outreach.get("ready") else 0,
                utc_now_iso(),
                lead_id,
            ),
        )
        conn.commit()


def retry_failed_smtp_leads(project_id: str, db_path: str | Path | None = None) -> int:
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE leads
            SET smtp_status = 'retry',
                last_updated = ?
            WHERE project_id = ? AND smtp_status = 'failed'
            """,
            (utc_now_iso(), project_id),
        )
        conn.commit()
    return cursor.rowcount


def mark_lead_website_failed(lead_id: str, db_path: str | Path | None = None) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE leads
            SET website_status = 'failed',
                last_updated = ?
            WHERE id = ?
            """,
            (utc_now_iso(), lead_id),
        )
        conn.commit()


def list_cells(project_id: str, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM cells
            WHERE project_id = ?
            ORDER BY depth ASC, created_at ASC, id ASC
            """,
            (project_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_coverage_status(project_id: str, db_path: str | Path | None = None) -> dict[str, Any]:
    with get_connection(db_path) as conn:
        cells = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END), 0) AS cells_completed,
                COALESCE(SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END), 0) AS cells_running,
                COALESCE(SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END), 0) AS cells_pending,
                COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0) AS cells_failed,
                COALESCE(SUM(CASE WHEN cap_hit = 1 THEN 1 ELSE 0 END), 0) AS cap_hits,
                COUNT(*) AS total_cells
            FROM cells
            WHERE project_id = ?
            """,
            (project_id,),
        ).fetchone()
        leads = conn.execute(
            "SELECT COUNT(*) AS lead_count FROM leads WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        depth_rows = conn.execute(
            """
            SELECT depth, COUNT(*) AS cell_count
            FROM cells
            WHERE project_id = ?
            GROUP BY depth
            ORDER BY depth ASC
            """,
            (project_id,),
        ).fetchall()

    status = dict(cells) if cells is not None else {}
    status["leads_found"] = int(leads["lead_count"]) if leads is not None else 0
    status["coverage_complete"] = (
        status.get("total_cells", 0) > 0
        and status.get("cells_running", 0) == 0
        and status.get("cells_pending", 0) == 0
    )
    total_cells = status.get("total_cells", 0) or 0
    completed_cells = status.get("cells_completed", 0) or 0
    status["completion_percent"] = int((completed_cells / total_cells) * 100) if total_cells else 0
    status["depth_stats"] = [dict(row) for row in depth_rows]
    return status


def cells_to_geojson(project_id: str, db_path: str | Path | None = None) -> dict[str, Any]:
    features = []
    for cell in list_cells(project_id, db_path):
        min_lat, min_lon, max_lat, max_lon = parse_bbox(cell["bbox"])
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [min_lon, min_lat],
                        [max_lon, min_lat],
                        [max_lon, max_lat],
                        [min_lon, max_lat],
                        [min_lon, min_lat],
                    ]],
                },
                "properties": {
                    "id": cell["id"],
                    "bbox": cell["bbox"],
                    "depth": cell["depth"],
                    "status": cell["status"],
                    "result_count": cell["result_count"],
                    "cap_hit": bool(cell["cap_hit"]),
                    "gosom_job_id": cell["gosom_job_id"],
                    "created_at": cell["created_at"],
                    "completed_at": cell["completed_at"],
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}
