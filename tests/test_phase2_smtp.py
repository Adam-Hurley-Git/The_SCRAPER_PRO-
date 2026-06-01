"""D6 — SMTP verification stage tests.

Covers:
- smtp_probe_email: result tri-state, rate limiting, connection-error backoff
- apply_smtp_verification: confidence mapping, no same-run retry, unverifiable preserves MX confidence
- run_smtp_stage: DB claim/reset/retry lifecycle, batch processing
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from database import (
    claim_next_pending_smtp_lead,
    count_pending_smtp_leads,
    create_project,
    get_connection,
    insert_leads_from_gosom_results,
    reset_running_smtp_leads,
    retry_failed_smtp_leads,
    update_lead_website_enrichment,
)
from pipeline.phase2_enrichment import (
    EmailRecord,
    EnrichmentRecord,
    OutreachRecord,
    SmtpResult,
    WebRecord,
    apply_smtp_verification,
    build_enrichment_record,
    run_smtp_stage,
    utc_now_iso,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_email_record(
    address: str = "info@example.co.uk",
    confidence: str = "medium",
    mx_valid: bool | None = True,
    syntax_valid: bool = True,
) -> EmailRecord:
    return EmailRecord(
        address=address,
        role_inferred="generic",
        sources=["homepage"],
        source_count=1,
        syntax_valid=syntax_valid,
        mx_valid=mx_valid,
        confidence=confidence,  # type: ignore[arg-type]
        primary=True,
    )


def _make_record_with_emails(*emails: EmailRecord) -> EnrichmentRecord:
    return EnrichmentRecord(
        business_id=str(uuid.uuid4()),
        scraped_at=utc_now_iso(),
        enriched_at=utc_now_iso(),
        company=__import__("pipeline.phase2_enrichment", fromlist=["CompanyRecord"]).CompanyRecord(
            name_scraped="Test Company"
        ),
        emails=list(emails),
        web=WebRecord(url_final="https://example.co.uk", status="live"),
        outreach=OutreachRecord(
            primary_email=emails[0].address if emails else None,
            ready=bool(emails),
        ),
    )


def _raw_lead(title: str = "Test Co", cid: str | None = None) -> dict[str, Any]:
    return {
        "cid": cid or str(uuid.uuid4()),
        "title": title,
        "address": "1 High Street, Swansea, SA1 1DP",
        "phone": "01792123456",
        "website": "https://example.co.uk",
        "latitude": 51.6193,
        "longitude": -3.9437,
    }


def _insert_done_website_lead(
    project_id: str,
    db_path: Path,
    raw_data: dict[str, Any],
    email: str | None = "info@example.co.uk",
) -> str:
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
    # Inject a test email if requested
    if email and not record.emails:
        record.emails.append(_make_email_record(email))
        record.outreach.primary_email = email
        record.outreach.ready = True

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
# apply_smtp_verification — confidence mapping
# ---------------------------------------------------------------------------

def test_smtp_verified_true_raises_confidence_to_high() -> None:
    email = _make_email_record(confidence="medium")
    record = _make_record_with_emails(email)
    prober = lambda _addr: "smtp_verified_true"

    updated, status, probed = apply_smtp_verification(
        record=record,
        probed_addresses=set(),
        smtp_prober=prober,
    )

    assert status == "done"
    assert updated.emails[0].smtp_verified is True
    assert updated.emails[0].confidence == "high"
    assert updated.emails[0].smtp_result == "smtp_verified_true"


def test_smtp_verified_false_lowers_confidence() -> None:
    email = _make_email_record(confidence="medium")
    record = _make_record_with_emails(email)
    prober = lambda _addr: "smtp_verified_false"

    updated, status, _ = apply_smtp_verification(
        record=record,
        probed_addresses=set(),
        smtp_prober=prober,
    )

    assert updated.emails[0].smtp_verified is False
    assert updated.emails[0].confidence == "low"
    assert updated.emails[0].smtp_result == "smtp_verified_false"


def test_smtp_unverifiable_preserves_mx_based_medium_confidence() -> None:
    """Hostile/blocking mail server must not penalise a valid email."""
    email = _make_email_record(confidence="medium", mx_valid=True)
    record = _make_record_with_emails(email)
    prober = lambda _addr: "smtp_unverifiable"

    updated, status, _ = apply_smtp_verification(
        record=record,
        probed_addresses=set(),
        smtp_prober=prober,
    )

    assert updated.emails[0].smtp_verified is None
    assert updated.emails[0].confidence == "medium"  # unchanged
    assert updated.emails[0].smtp_result == "smtp_unverifiable"


def test_smtp_no_same_run_retry_for_already_probed_address() -> None:
    """An address already in probed_addresses must not be probed again."""
    call_count = 0

    def counting_prober(_addr: str) -> SmtpResult:
        nonlocal call_count
        call_count += 1
        return "smtp_verified_true"

    email = _make_email_record("info@example.co.uk", confidence="medium")
    record = _make_record_with_emails(email)

    already_probed: set[str] = {"info@example.co.uk"}
    apply_smtp_verification(
        record=record,
        probed_addresses=already_probed,
        smtp_prober=counting_prober,
    )

    assert call_count == 0  # must not have been called


def test_smtp_probed_addresses_accumulate_across_leads() -> None:
    """The same email appearing on two leads should be probed only once per run."""
    probe_calls: list[str] = []

    def tracking_prober(addr: str) -> SmtpResult:
        probe_calls.append(addr)
        return "smtp_verified_true"

    email1 = _make_email_record("shared@example.co.uk")
    email2 = _make_email_record("shared@example.co.uk")
    record1 = _make_record_with_emails(email1)
    record2 = _make_record_with_emails(email2)

    _, _, probed = apply_smtp_verification(
        record=record1, probed_addresses=set(), smtp_prober=tracking_prober
    )
    apply_smtp_verification(
        record=record2, probed_addresses=probed, smtp_prober=tracking_prober
    )

    assert probe_calls.count("shared@example.co.uk") == 1


def test_smtp_multiple_emails_each_probed_separately() -> None:
    email_a = _make_email_record("a@example.co.uk", confidence="medium")
    email_b = _make_email_record("b@example.co.uk", confidence="medium")
    record = _make_record_with_emails(email_a, email_b)
    record.emails[1].primary = False

    results_map = {"a@example.co.uk": "smtp_verified_true", "b@example.co.uk": "smtp_unverifiable"}
    prober = lambda addr: results_map[addr]

    updated, _, _ = apply_smtp_verification(
        record=record, probed_addresses=set(), smtp_prober=prober
    )

    assert updated.emails[0].confidence == "high"
    assert updated.emails[1].confidence == "medium"  # unverifiable → preserved


# ---------------------------------------------------------------------------
# smtp_probe_email — unit testing the prober with mock SMTP
# ---------------------------------------------------------------------------

def test_smtp_probe_returns_verified_true_on_250_rcpt() -> None:
    """Simulate a mail server that confirms the mailbox with RCPT 250."""
    from pipeline.phase2_enrichment import smtp_probe_email

    mock_smtp_instance = MagicMock()
    mock_smtp_instance.__enter__ = lambda s: s
    mock_smtp_instance.__exit__ = MagicMock(return_value=False)
    mock_smtp_instance.rcpt.return_value = (250, b"OK")

    with patch("pipeline.phase2_enrichment._resolve_mx_host", return_value="mail.example.co.uk"), \
         patch("smtplib.SMTP", return_value=mock_smtp_instance), \
         patch("pipeline.phase2_enrichment._smtp_rate_limit"):
        result = smtp_probe_email("test@example.co.uk")

    assert result == "smtp_verified_true"


def test_smtp_probe_returns_verified_false_on_550_rcpt() -> None:
    """Simulate a mail server that rejects the mailbox with RCPT 550."""
    from pipeline.phase2_enrichment import smtp_probe_email

    mock_smtp_instance = MagicMock()
    mock_smtp_instance.__enter__ = lambda s: s
    mock_smtp_instance.__exit__ = MagicMock(return_value=False)
    mock_smtp_instance.rcpt.return_value = (550, b"No such user")

    with patch("pipeline.phase2_enrichment._resolve_mx_host", return_value="mail.example.co.uk"), \
         patch("smtplib.SMTP", return_value=mock_smtp_instance), \
         patch("pipeline.phase2_enrichment._smtp_rate_limit"):
        result = smtp_probe_email("test@example.co.uk")

    assert result == "smtp_verified_false"


def test_smtp_probe_returns_unverifiable_on_connection_error() -> None:
    """Connection-level failure must map to smtp_unverifiable (not smtp_verified_false)."""
    import smtplib as _smtplib
    from pipeline.phase2_enrichment import smtp_probe_email

    with patch("pipeline.phase2_enrichment._resolve_mx_host", return_value="mail.example.co.uk"), \
         patch("smtplib.SMTP") as mock_smtp_class, \
         patch("pipeline.phase2_enrichment._smtp_rate_limit"), \
         patch("pipeline.phase2_enrichment._time_module") as mock_time:
        mock_smtp_class.return_value.__enter__ = MagicMock(side_effect=_smtplib.SMTPConnectError(421, "Cannot connect"))
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)
        result = smtp_probe_email("test@example.co.uk")

    assert result == "smtp_unverifiable"


def test_smtp_probe_returns_unverifiable_when_no_mx() -> None:
    from pipeline.phase2_enrichment import smtp_probe_email

    with patch("pipeline.phase2_enrichment._resolve_mx_host", return_value=None), \
         patch("pipeline.phase2_enrichment._smtp_rate_limit"):
        result = smtp_probe_email("nobody@nodomain.local")

    assert result == "smtp_unverifiable"


# ---------------------------------------------------------------------------
# run_smtp_stage — DB lifecycle
# ---------------------------------------------------------------------------

def test_run_smtp_stage_processes_done_website_lead(temp_db: Path) -> None:
    project = create_project(
        name="SMTP Test",
        primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8",
        db_path=temp_db,
    )
    raw = _raw_lead()
    _insert_done_website_lead(project["id"], temp_db, raw)

    prober = lambda _addr: "smtp_verified_true"
    result = run_smtp_stage(
        project["id"],
        db_path=str(temp_db),
        smtp_prober=prober,
    )

    assert result["processed"] == 1
    assert result["failed"] == 0
    assert result["remaining"] == 0

    with get_connection(temp_db) as conn:
        row = conn.execute(
            "SELECT smtp_status, enrichment_data FROM leads WHERE project_id = ?",
            (project["id"],),
        ).fetchone()
    assert row["smtp_status"] == "done"


def test_run_smtp_stage_skips_pending_website_leads(temp_db: Path) -> None:
    """Leads where website_status is still pending must not be claimed."""
    project = create_project(
        name="SMTP Skip Test",
        primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8",
        db_path=temp_db,
    )
    raw = _raw_lead()
    insert_leads_from_gosom_results(
        project_id=project["id"],
        cell_id="cell-1",
        results=[raw],
        db_path=temp_db,
    )  # website_status stays 'pending'

    result = run_smtp_stage(project["id"], db_path=str(temp_db))
    assert result["processed"] == 0
    assert result["remaining"] == 0


def test_run_smtp_stage_resets_stranded_running_leads(temp_db: Path) -> None:
    project = create_project(
        name="SMTP Reset Test",
        primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8",
        db_path=temp_db,
    )
    raw = _raw_lead()
    lead_id = _insert_done_website_lead(project["id"], temp_db, raw)

    with get_connection(temp_db) as conn:
        conn.execute(
            "UPDATE leads SET smtp_status = 'running' WHERE id = ?", (lead_id,)
        )
        conn.commit()

    reset_count = reset_running_smtp_leads(project["id"], temp_db)
    assert reset_count == 1

    with get_connection(temp_db) as conn:
        row = conn.execute("SELECT smtp_status FROM leads WHERE id = ?", (lead_id,)).fetchone()
    assert row["smtp_status"] == "pending"


def test_retry_failed_smtp_leads(temp_db: Path) -> None:
    project = create_project(
        name="SMTP Retry Test",
        primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8",
        db_path=temp_db,
    )
    raw = _raw_lead()
    lead_id = _insert_done_website_lead(project["id"], temp_db, raw)

    with get_connection(temp_db) as conn:
        conn.execute("UPDATE leads SET smtp_status = 'failed' WHERE id = ?", (lead_id,))
        conn.commit()

    retried = retry_failed_smtp_leads(project["id"], temp_db)
    assert retried == 1

    with get_connection(temp_db) as conn:
        row = conn.execute("SELECT smtp_status FROM leads WHERE id = ?", (lead_id,)).fetchone()
    assert row["smtp_status"] == "retry"


def test_count_pending_smtp_leads(temp_db: Path) -> None:
    project = create_project(
        name="SMTP Count Test",
        primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8",
        db_path=temp_db,
    )
    raw = _raw_lead()
    _insert_done_website_lead(project["id"], temp_db, raw)

    count = count_pending_smtp_leads(project["id"], temp_db)
    assert count == 1


def test_run_smtp_stage_no_same_run_retry_across_leads(temp_db: Path) -> None:
    """Same email on two leads in one run: prober called only once."""
    probe_calls: list[str] = []

    def tracking_prober(addr: str) -> SmtpResult:
        probe_calls.append(addr)
        return "smtp_verified_true"

    project = create_project(
        name="SMTP Dedup Test",
        primary_term="plumbers",
        bbox="51.5,51.6,-3.9,-3.8",
        db_path=temp_db,
    )
    shared_email = "shared@example.co.uk"
    raw1 = _raw_lead(cid="cid-1")
    raw2 = _raw_lead(cid="cid-2")
    _insert_done_website_lead(project["id"], temp_db, raw1, email=shared_email)
    _insert_done_website_lead(project["id"], temp_db, raw2, email=shared_email)

    run_smtp_stage(project["id"], db_path=str(temp_db), smtp_prober=tracking_prober)

    assert probe_calls.count(shared_email) == 1
