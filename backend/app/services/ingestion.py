"""Multi-source ingestion pipeline: Downloaded Reports (L2), System Emails (L3), Controlled Input (L4).

Implements:
- Re-ranked evidence hierarchy (Downloaded Report L2 > System Email L3 > Controlled Input L4)
- Salted HMAC-SHA256 PII scrubbing/hashing at ingestion (PDPA/GDPR compliant)
- SHA-256 payload idempotency via raw_ingested_events
- Effective-dated CreditRules evaluation (historical entries never retroactively mutated)
- Campaign-to-Project mapping & retroactive 1-click attribution
- Pending -> Superseded + Confirmed upgrade path (zero double counting, append-only ledger)
"""
from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from typing import Any

from fastapi import HTTPException

from ..config import EVIDENCE_HIERARCHY, VALID_LIFECYCLE_STATUSES
from ..schemas import CampaignMappingCreateRequest, ControlledInputRequest, SystemEmailIngestRequest
from ..security import (
    Actor,
    anonymize_candidate,
    compute_payload_hash,
    require_roles,
    scrub_pii_from_text,
)
from .audit import log_audit, utc_now_iso
from .ledger import next_exception_code, next_tx_code

STATUS_ORDER = {
    "Created": 1,
    "Sent": 2,
    "Started": 3,
    "Completed": 4,
    "Cancelled": 4,
    "Failed": 4,
    "Expired": 4,
}


def resolve_credit_rule(
    conn: sqlite3.Connection,
    assessment_type: str,
    event_date: str,
) -> dict[str, Any] | None:
    """Resolve the active effective-dated credit rule for an assessment type on a given date."""
    row = conn.execute(
        """
        SELECT * FROM credit_rules
        WHERE LOWER(assessment_type) = LOWER(?)
          AND effective_from <= ?
          AND (effective_to IS NULL OR effective_to >= ?)
        ORDER BY effective_from DESC, id DESC
        LIMIT 1
        """,
        (assessment_type.strip(), event_date, event_date),
    ).fetchone()
    return dict(row) if row else None


def should_deduct_credits(rule: dict[str, Any] | None, status: str) -> tuple[bool, int]:
    """Determine if an assessment status triggers credit deduction under the active rule."""
    if not rule:
        return False, 0
    if status in ("Cancelled", "Failed", "Expired", "Created"):
        return False, 0
    trigger = rule["trigger_event"]
    if trigger == "Sent" and status in ("Sent", "Started", "Completed"):
        return True, int(rule["credit_units"])
    if trigger == "Started" and status in ("Started", "Completed"):
        return True, int(rule["credit_units"])
    if trigger == "Completed" and status == "Completed":
        return True, int(rule["credit_units"])
    return False, 0


def resolve_campaign_mapping(
    conn: sqlite3.Connection,
    campaign_key: str | None,
) -> dict[str, Any] | None:
    """Resolve a Pulsifi Campaign/Role key to an internal Project (Client/Partner pool)."""
    if not campaign_key or not campaign_key.strip():
        return None
    cleaned = campaign_key.strip()

    # 1. Exact mapping table match
    row = conn.execute(
        """
        SELECT p.id AS project_id, p.code AS project_code, p.name AS project_name,
               p.client_id, p.partner_id, p.pool_owner_type,
               c.name AS client_name, pa.name AS partner_name
        FROM campaign_mappings cm
        JOIN projects p ON p.id = cm.project_id
        JOIN clients c ON c.id = p.client_id
        LEFT JOIN partners pa ON pa.id = p.partner_id
        WHERE LOWER(cm.pulsifi_campaign_key) = LOWER(?) AND cm.active = 1
        LIMIT 1
        """,
        (cleaned,),
    ).fetchone()
    if row:
        return dict(row)

    # 2. Convention-based prefix match: e.g. "[ABC-GRAD] Graduate Cohort" or "ABC-GRAD-2026"
    projects = conn.execute(
        """
        SELECT p.id AS project_id, p.code AS project_code, p.name AS project_name,
               p.client_id, p.partner_id, p.pool_owner_type,
               c.name AS client_name, pa.name AS partner_name
        FROM projects p
        JOIN clients c ON c.id = p.client_id
        LEFT JOIN partners pa ON pa.id = p.partner_id
        WHERE p.status = 'Active'
        """
    ).fetchall()
    upper_key = cleaned.upper()
    for p in projects:
        code = p["project_code"].upper()
        if upper_key == code or upper_key.startswith(f"{code}-") or f"[{code}]" in upper_key:
            return dict(p)

    return None


def _status_timestamp_column(status: str) -> str:
    return {
        "Created": "created_at",
        "Sent": "sent_at",
        "Started": "started_at",
        "Completed": "completed_at",
        "Cancelled": "cancelled_at",
        "Failed": "failed_at",
        "Expired": "expired_at",
    }[status]


def _create_exception_if_needed(
    conn: sqlite3.Connection,
    category: str,
    severity: str,
    reference_code: str,
    owner_role: str,
    suggested_action: str,
    client_id: int | None = None,
    partner_id: int | None = None,
    campaign_key: str | None = None,
    linked_event_id: int | None = None,
    linked_assessment_id: int | None = None,
    linked_tx_id: int | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    existing = conn.execute(
        """
        SELECT * FROM exceptions
        WHERE category = ? AND reference_code = ? AND status IN ('Open', 'In Review')
        LIMIT 1
        """,
        (category, reference_code),
    ).fetchone()
    if existing:
        return dict(existing)

    exc_code = next_exception_code(conn)
    now = created_at or utc_now_iso()
    cur = conn.execute(
        """
        INSERT INTO exceptions (
            exception_code, category, severity, reference_code, owner_role,
            client_id, partner_id, campaign_key, linked_event_id,
            linked_assessment_id, linked_tx_id, suggested_action, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Open', ?)
        """,
        (
            exc_code,
            category,
            severity,
            reference_code,
            owner_role,
            client_id,
            partner_id,
            campaign_key,
            linked_event_id,
            linked_assessment_id,
            linked_tx_id,
            suggested_action,
            now,
        ),
    )
    return dict(conn.execute("SELECT * FROM exceptions WHERE id = ?", (cur.lastrowid,)).fetchone())


def _record_raw_event(
    conn: sqlite3.Connection,
    source_type: str,
    raw_content: str,
    actor: Actor,
    filename: str | None = None,
    reference_for_dup: str | None = None,
    ingested_at: str | None = None,
) -> tuple[int, bool, int]:
    """Store PII-scrubbed raw event with SHA-256 idempotency.

    Returns (raw_event_id, is_duplicate, pii_redactions_count).
    """
    payload_hash = compute_payload_hash(source_type, raw_content)
    existing = conn.execute(
        "SELECT id FROM raw_ingested_events WHERE payload_hash = ?", (payload_hash,)
    ).fetchone()
    if existing:
        _create_exception_if_needed(
            conn,
            category="Duplicate",
            severity="Medium",
            reference_code=reference_for_dup or f"HASH-{payload_hash[:8].upper()}",
            owner_role="OPERATIONS",
            suggested_action=(
                f"Duplicate {source_type} payload blocked by SHA-256 idempotency guard "
                f"(original event #{existing['id']}). Verify no manual re-entry occurred."
            ),
            linked_event_id=int(existing["id"]),
            created_at=ingested_at,
        )
        return int(existing["id"]), True, 0

    scrubbed, redactions = scrub_pii_from_text(raw_content)
    evidence_level = int(EVIDENCE_HIERARCHY[source_type]["level"])
    now = ingested_at or utc_now_iso()
    cur = conn.execute(
        """
        INSERT INTO raw_ingested_events (
            payload_hash, source_type, evidence_level, filename,
            scrubbed_payload, pii_redactions_count, processing_status,
            ingested_by, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'Processed', ?, ?)
        """,
        (
            payload_hash,
            source_type,
            evidence_level,
            filename,
            scrubbed,
            redactions,
            actor.name,
            now,
        ),
    )
    return int(cur.lastrowid), False, redactions


def _upsert_assessment_and_post_ledger(
    conn: sqlite3.Connection,
    *,
    pulsifi_assessment_id: str,
    candidate_identifier: str,
    assessment_type: str,
    event_status: str,
    event_date: str,
    source_type: str,
    actor: Actor,
    raw_event_id: int,
    project_info: dict[str, Any] | None,
    campaign_key: str | None = None,
    notes: str | None = None,
    timestamp_iso: str | None = None,
) -> dict[str, Any]:
    """Core event-driven lifecycle & append-only ledger processor."""
    if event_status not in VALID_LIFECYCLE_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid assessment status '{event_status}'.")

    now = timestamp_iso or f"{event_date}T09:00:00Z"
    candidate_hash = anonymize_candidate(candidate_identifier)
    evidence_meta = EVIDENCE_HIERARCHY[source_type]
    evidence_level = int(evidence_meta["level"])
    auto_confirm = bool(evidence_meta["auto_confirm"])

    rule = resolve_credit_rule(conn, assessment_type, event_date)
    should_deduct, rule_units = should_deduct_credits(rule, event_status)

    # For Controlled Input on 'Sent' when billing trigger is 'Completed', reserve Pending estimated units
    # so Estimated Balance reflects committed work-in-progress without affecting Confirmed Balance.
    pending_reserve = False
    if (
        not should_deduct
        and source_type == "CONTROLLED_INPUT"
        and event_status in ("Sent", "Started")
        and rule is not None
        and int(rule["credit_units"]) > 0
    ):
        pending_reserve = True
        rule_units = int(rule["credit_units"])

    existing = conn.execute(
        "SELECT * FROM assessments WHERE pulsifi_assessment_id = ?",
        (pulsifi_assessment_id,),
    ).fetchone()

    ts_col = _status_timestamp_column(event_status)
    client_id = project_info["client_id"] if project_info else None
    partner_id = project_info["partner_id"] if project_info else None
    project_id = project_info["project_id"] if project_info else None
    pool_owner_type = project_info["pool_owner_type"] if project_info else "UNASSIGNED"

    if existing:
        assessment_id = int(existing["id"])
        # Preserve attribution if existing already mapped and incoming has none
        final_client_id = client_id or existing["client_id"]
        final_partner_id = partner_id or existing["partner_id"]
        final_project_id = project_id or existing["project_id"]
        if final_project_id and not project_info:
            p_row = conn.execute(
                "SELECT pool_owner_type FROM projects WHERE id = ?", (final_project_id,)
            ).fetchone()
            pool_owner_type = p_row["pool_owner_type"] if p_row else "UNASSIGNED"

        # Upgrade evidence level if new source is higher authority (lower level number)
        final_ev_level = min(int(existing["evidence_level"]), evidence_level)
        final_source = source_type if evidence_level <= int(existing["evidence_level"]) else existing["source_type"]

        # Advance lifecycle status if forward progression or terminal event
        old_rank = STATUS_ORDER.get(existing["current_status"], 0)
        new_rank = STATUS_ORDER.get(event_status, 0)
        final_status = event_status if new_rank >= old_rank else existing["current_status"]

        conn.execute(
            f"""
            UPDATE assessments
            SET current_status = ?,
                {ts_col} = COALESCE({ts_col}, ?),
                client_id = ?,
                partner_id = ?,
                project_id = ?,
                pulsifi_campaign_key = COALESCE(?, pulsifi_campaign_key),
                evidence_level = ?,
                source_type = ?,
                credit_rule_id = COALESCE(?, credit_rule_id),
                raw_event_id = ?
            WHERE id = ?
            """,
            (
                final_status,
                now,
                final_client_id,
                final_partner_id,
                final_project_id,
                campaign_key,
                final_ev_level,
                final_source,
                rule["id"] if rule else None,
                raw_event_id,
                assessment_id,
            ),
        )
        client_id, partner_id, project_id = final_client_id, final_partner_id, final_project_id
    else:
        cur = conn.execute(
            f"""
            INSERT INTO assessments (
                pulsifi_assessment_id, pulsifi_campaign_key, candidate_ref_hash,
                client_id, partner_id, project_id, assessment_type, current_status,
                created_at, {ts_col}, credit_units_applied, credit_rule_id,
                evidence_level, source_type, raw_event_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pulsifi_assessment_id,
                campaign_key,
                candidate_hash,
                client_id,
                partner_id,
                project_id,
                assessment_type,
                event_status,
                now,
                now,
                rule_units if (should_deduct or pending_reserve) else 0,
                rule["id"] if rule else None,
                evidence_level,
                source_type,
                raw_event_id,
            ),
        )
        assessment_id = int(cur.lastrowid)

    # Track ledger action & exceptions
    created_exception = None
    if project_id is None:
        created_exception = _create_exception_if_needed(
            conn,
            category="Unknown Mapping",
            severity="Medium",
            reference_code=pulsifi_assessment_id,
            owner_role="OPERATIONS",
            campaign_key=campaign_key or "MISSING_CAMPAIGN",
            linked_event_id=raw_event_id,
            linked_assessment_id=assessment_id,
            suggested_action=(
                f"Map Pulsifi campaign '{campaign_key or 'N/A'}' to an internal Project/Client pool "
                f"so usage can be confirmed and attributed."
            ),
            created_at=now,
        )

    if rule is None:
        created_exception = _create_exception_if_needed(
            conn,
            category="Rule Mismatch",
            severity="High",
            reference_code=pulsifi_assessment_id,
            owner_role="ADMIN",
            client_id=client_id,
            partner_id=partner_id,
            linked_event_id=raw_event_id,
            linked_assessment_id=assessment_id,
            suggested_action=(
                f"No active effective-dated CreditRule found for '{assessment_type}' on {event_date}. "
                f"Configure a credit rule and reprocess."
            ),
            created_at=now,
        )

    # Evaluate existing active ledger rows for this assessment to prevent double counting
    active_confirmed = conn.execute(
        """
        SELECT * FROM credit_transactions
        WHERE assessment_id = ? AND tx_type = 'Usage' AND status = 'Confirmed'
        LIMIT 1
        """,
        (assessment_id,),
    ).fetchone()

    active_pending = conn.execute(
        """
        SELECT * FROM credit_transactions
        WHERE assessment_id = ? AND tx_type = 'Usage' AND status = 'Pending'
        LIMIT 1
        """,
        (assessment_id,),
    ).fetchone()

    posted_tx = None
    ledger_action = "NO_LEDGER_CHANGE"

    # Case 1: Cancelled / Failed / Expired assessment
    if event_status in ("Cancelled", "Failed", "Expired"):
        if active_pending:
            conn.execute(
                "UPDATE credit_transactions SET status = 'Cancelled' WHERE id = ?",
                (active_pending["id"],),
            )
            ledger_action = "PENDING_CANCELLED"
        elif active_confirmed and rule and int(rule["refund_on_cancel"]) == 1:
            # Append a Refund row instead of mutating Confirmed row
            existing_refund = conn.execute(
                "SELECT id FROM credit_transactions WHERE assessment_id = ? AND tx_type = 'Refund'",
                (assessment_id,),
            ).fetchone()
            if not existing_refund:
                tx_code = next_tx_code(conn)
                cur_tx = conn.execute(
                    """
                    INSERT INTO credit_transactions (
                        tx_code, tx_date, period_month, tx_type, client_id, partner_id, project_id,
                        pool_owner_type, assessment_id, reference_code, units, status,
                        evidence_level, source_type, parent_transaction_id, credit_rule_id,
                        raw_event_id, notes, created_by, created_at
                    ) VALUES (?, ?, ?, 'Refund', ?, ?, ?, ?, ?, ?, ?, 'Confirmed', ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tx_code,
                        event_date,
                        event_date[:7],
                        client_id,
                        partner_id,
                        project_id,
                        pool_owner_type,
                        assessment_id,
                        pulsifi_assessment_id,
                        abs(int(active_confirmed["units"])),
                        evidence_level,
                        source_type,
                        active_confirmed["id"],
                        rule["id"] if rule else None,
                        raw_event_id,
                        f"Auto-refund on {event_status} per active credit rule",
                        actor.name,
                        now,
                    ),
                )
                posted_tx = dict(
                    conn.execute("SELECT * FROM credit_transactions WHERE id = ?", (cur_tx.lastrowid,)).fetchone()
                )
                ledger_action = "REFUND_APPENDED"
        conn.execute("UPDATE assessments SET credit_units_applied = 0 WHERE id = ?", (assessment_id,))

    # Case 2: Usage deduction triggered or pending reservation
    elif should_deduct or pending_reserve:
        desired_status = "Confirmed" if (auto_confirm and should_deduct and project_id is not None) else "Pending"

        if active_confirmed:
            # Already confirmed — prevent double counting! Check for unit discrepancy
            if abs(int(active_confirmed["units"])) != rule_units:
                created_exception = _create_exception_if_needed(
                    conn,
                    category="Rule Mismatch",
                    severity="Medium",
                    reference_code=pulsifi_assessment_id,
                    owner_role="FINANCE",
                    client_id=client_id,
                    partner_id=partner_id,
                    linked_event_id=raw_event_id,
                    linked_assessment_id=assessment_id,
                    linked_tx_id=active_confirmed["id"],
                    suggested_action=(
                        f"New {source_type} indicates {rule_units} units vs already-confirmed "
                        f"{abs(int(active_confirmed['units']))} units on {active_confirmed['tx_code']}."
                    ),
                    created_at=now,
                )
            ledger_action = "ALREADY_CONFIRMED_NO_DOUBLE_COUNT"
        elif active_pending:
            if desired_status == "Confirmed":
                # Upgrade Pending -> Superseded and append immutable Confirmed row
                conn.execute(
                    "UPDATE credit_transactions SET status = 'Superseded' WHERE id = ?",
                    (active_pending["id"],),
                )
                tx_code = next_tx_code(conn)
                cur_tx = conn.execute(
                    """
                    INSERT INTO credit_transactions (
                        tx_code, tx_date, period_month, tx_type, client_id, partner_id, project_id,
                        pool_owner_type, assessment_id, reference_code, units, status,
                        evidence_level, source_type, parent_transaction_id, credit_rule_id,
                        raw_event_id, notes, created_by, created_at
                    ) VALUES (?, ?, ?, 'Usage', ?, ?, ?, ?, ?, ?, ?, 'Confirmed', ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tx_code,
                        event_date,
                        event_date[:7],
                        client_id,
                        partner_id,
                        project_id,
                        pool_owner_type,
                        assessment_id,
                        pulsifi_assessment_id,
                        -rule_units,
                        evidence_level,
                        source_type,
                        active_pending["id"],
                        rule["id"] if rule else None,
                        raw_event_id,
                        notes or f"Evidence upgraded from {active_pending['tx_code']} via {source_type}",
                        actor.name,
                        now,
                    ),
                )
                posted_tx = dict(
                    conn.execute("SELECT * FROM credit_transactions WHERE id = ?", (cur_tx.lastrowid,)).fetchone()
                )
                conn.execute(
                    "UPDATE assessments SET credit_units_applied = ? WHERE id = ?",
                    (rule_units, assessment_id),
                )
                ledger_action = "UPGRADED_PENDING_TO_CONFIRMED"
            else:
                ledger_action = "ALREADY_PENDING"
        else:
            tx_code = next_tx_code(conn)
            cur_tx = conn.execute(
                """
                INSERT INTO credit_transactions (
                    tx_code, tx_date, period_month, tx_type, client_id, partner_id, project_id,
                    pool_owner_type, assessment_id, reference_code, units, status,
                    evidence_level, source_type, credit_rule_id, raw_event_id,
                    notes, created_by, created_at
                ) VALUES (?, ?, ?, 'Usage', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tx_code,
                    event_date,
                    event_date[:7],
                    client_id,
                    partner_id,
                    project_id,
                    pool_owner_type,
                    assessment_id,
                    pulsifi_assessment_id,
                    -rule_units,
                    desired_status,
                    evidence_level,
                    source_type,
                    rule["id"] if rule else None,
                    raw_event_id,
                    notes
                    or (
                        f"Pending unmapped campaign '{campaign_key}'"
                        if project_id is None
                        else f"{assessment_type} ({event_status}) via {source_type}"
                    ),
                    actor.name,
                    now,
                ),
            )
            posted_tx = dict(
                conn.execute("SELECT * FROM credit_transactions WHERE id = ?", (cur_tx.lastrowid,)).fetchone()
            )
            conn.execute(
                "UPDATE assessments SET credit_units_applied = ? WHERE id = ?",
                (rule_units, assessment_id),
            )
            ledger_action = f"POSTED_{desired_status.upper()}"

    return {
        "assessment": dict(conn.execute("SELECT * FROM assessments WHERE id = ?", (assessment_id,)).fetchone()),
        "transaction": posted_tx,
        "ledger_action": ledger_action,
        "exception": created_exception,
        "candidate_ref_hash": candidate_hash,
    }


def ingest_controlled_input(
    conn: sqlite3.Connection,
    req: ControlledInputRequest,
    actor: Actor,
) -> dict[str, Any]:
    """Level 4 Controlled Internal Input: <30s frictionless consultant issuance form."""
    require_roles(actor, {"OPERATIONS", "FINANCE", "ADMIN"}, "Capture Controlled Internal Input")
    proj = conn.execute(
        """
        SELECT p.id AS project_id, p.code AS project_code, p.name AS project_name,
               p.client_id, p.partner_id, p.pool_owner_type,
               c.name AS client_name, pa.name AS partner_name
        FROM projects p
        JOIN clients c ON c.id = p.client_id
        LEFT JOIN partners pa ON pa.id = p.partner_id
        WHERE p.id = ?
        """,
        (req.project_id,),
    ).fetchone()
    if not proj:
        raise HTTPException(status_code=404, detail=f"Project {req.project_id} not found.")

    event_date = req.event_date or utc_now_iso()[:10]
    raw_payload = json.dumps(
        {
            "assessment_id": req.pulsifi_assessment_id.strip(),
            "candidate": req.candidate_identifier.strip(),
            "project_id": req.project_id,
            "assessment_type": req.assessment_type.strip(),
            "status": req.event_status,
            "event_date": event_date,
        },
        sort_keys=True,
    )
    raw_id, is_dup, redactions = _record_raw_event(
        conn,
        source_type="CONTROLLED_INPUT",
        raw_content=raw_payload,
        actor=actor,
        reference_for_dup=req.pulsifi_assessment_id.strip(),
    )
    if is_dup:
        raise HTTPException(
            status_code=409,
            detail=f"Duplicate event blocked by SHA-256 idempotency guard ({req.pulsifi_assessment_id}).",
        )

    result = _upsert_assessment_and_post_ledger(
        conn,
        pulsifi_assessment_id=req.pulsifi_assessment_id.strip(),
        candidate_identifier=req.candidate_identifier,
        assessment_type=req.assessment_type.strip(),
        event_status=req.event_status,
        event_date=event_date,
        source_type="CONTROLLED_INPUT",
        actor=actor,
        raw_event_id=raw_id,
        project_info=dict(proj),
        campaign_key=proj["project_code"],
        notes=req.notes,
        timestamp_iso=utc_now_iso(),
    )

    log_audit(
        conn,
        actor=actor,
        action="CONTROLLED_INPUT_CAPTURED",
        entity_type="assessment",
        entity_id=req.pulsifi_assessment_id.strip(),
        before=None,
        after={
            "assessment_id": req.pulsifi_assessment_id.strip(),
            "candidate_ref_hash": result["candidate_ref_hash"],
            "ledger_action": result["ledger_action"],
            "tx_code": result["transaction"]["tx_code"] if result["transaction"] else None,
        },
        reason=req.notes or "Controlled internal issuance",
    )
    result["pii_redactions"] = redactions
    result["raw_event_id"] = raw_id
    return result


def parse_system_email_text(raw_text: str) -> dict[str, str]:
    """Parse structured fields from a Pulsifi system notification email."""
    def _extract(patterns: list[str], default: str = "") -> str:
        for pat in patterns:
            m = re.search(pat, raw_text, flags=re.IGNORECASE | re.MULTILINE)
            if m:
                return m.group(1).strip()
        return default

    assessment_id = _extract(
        [
            r"Assessment\s*ID\s*[:#-]\s*([A-Za-z0-9_-]+)",
            r"Reference\s*[:#-]\s*(P-[A-Za-z0-9_-]+)",
        ]
    )
    candidate = _extract(
        [
            r"Candidate(?:\s*Email|\s*Ref(?:erence)?)?\s*[:#-]\s*([^\r\n]+)",
            r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})",
        ]
    )
    campaign = _extract(
        [
            r"(?:Campaign|Role|Position|Project)\s*(?:Name|Key|ID)?\s*[:#-]\s*([^\r\n]+)",
        ]
    )
    assessment_type = _extract(
        [
            r"Assessment\s*Type\s*[:#-]\s*([^\r\n]+)",
            r"Module\s*[:#-]\s*([^\r\n]+)",
        ],
        default="Cognitive",
    )
    status_raw = _extract(
        [
            r"(?:Event\s*)?Status\s*[:#-]\s*([A-Za-z]+)",
        ],
        default="Completed",
    )
    event_date = _extract(
        [
            r"(?:Event\s*Date|Date|Timestamp)\s*[:#-]\s*(\d{4}-\d{2}-\d{2})",
        ],
        default=utc_now_iso()[:10],
    )

    # Normalize status case
    status_norm = next(
        (s for s in VALID_LIFECYCLE_STATUSES if s.lower() == status_raw.lower()),
        "Completed",
    )

    if not assessment_id:
        raise HTTPException(
            status_code=422,
            detail="Could not parse 'Assessment ID' from system email text. Expected e.g. 'Assessment ID: P-10350'.",
        )
    if not candidate:
        raise HTTPException(
            status_code=422,
            detail="Could not parse 'Candidate' email or reference from system email text.",
        )

    return {
        "pulsifi_assessment_id": assessment_id,
        "candidate_identifier": candidate,
        "campaign_key": campaign,
        "assessment_type": assessment_type,
        "event_status": status_norm,
        "event_date": event_date,
    }


def ingest_system_email(
    conn: sqlite3.Connection,
    req: SystemEmailIngestRequest,
    actor: Actor,
) -> dict[str, Any]:
    """Level 3 Pulsifi System Email ingestion with automatic PII scrubbing/hashing."""
    require_roles(actor, {"OPERATIONS", "FINANCE", "ADMIN"}, "Ingest Pulsifi System Email")
    parsed = parse_system_email_text(req.raw_email_text)

    raw_id, is_dup, redactions = _record_raw_event(
        conn,
        source_type="SYSTEM_EMAIL",
        raw_content=req.raw_email_text,
        actor=actor,
        filename=req.subject or "pulsifi-notification.eml",
        reference_for_dup=parsed["pulsifi_assessment_id"],
    )
    if is_dup:
        return {
            "duplicate": True,
            "raw_event_id": raw_id,
            "parsed": {**parsed, "candidate_identifier": anonymize_candidate(parsed["candidate_identifier"])},
            "message": "Duplicate email payload detected and safely ignored (Duplicate exception logged).",
        }

    project_info = resolve_campaign_mapping(conn, parsed["campaign_key"])
    result = _upsert_assessment_and_post_ledger(
        conn,
        pulsifi_assessment_id=parsed["pulsifi_assessment_id"],
        candidate_identifier=parsed["candidate_identifier"],
        assessment_type=parsed["assessment_type"],
        event_status=parsed["event_status"],
        event_date=parsed["event_date"],
        source_type="SYSTEM_EMAIL",
        actor=actor,
        raw_event_id=raw_id,
        project_info=project_info,
        campaign_key=parsed["campaign_key"] or None,
        timestamp_iso=utc_now_iso(),
    )

    log_audit(
        conn,
        actor=actor,
        action="SYSTEM_EMAIL_INGESTED",
        entity_type="raw_ingested_event",
        entity_id=raw_id,
        before=None,
        after={
            "assessment_id": parsed["pulsifi_assessment_id"],
            "candidate_ref_hash": result["candidate_ref_hash"],
            "pii_redactions": redactions,
            "mapped_project": project_info["project_name"] if project_info else None,
            "ledger_action": result["ledger_action"],
        },
        reason=req.subject or "System Email Ingestion",
    )
    return {
        "duplicate": False,
        "raw_event_id": raw_id,
        "pii_redactions": redactions,
        "candidate_ref_hash": result["candidate_ref_hash"],
        "mapped_project": project_info["project_name"] if project_info else None,
        "ledger_action": result["ledger_action"],
        "assessment": result["assessment"],
        "transaction": result["transaction"],
        "exception": result["exception"],
    }


def ingest_downloaded_report_csv(
    conn: sqlite3.Connection,
    filename: str,
    csv_text: str,
    actor: Actor,
) -> dict[str, Any]:
    """Level 2 Official Downloaded Report (CSV) ingestion — ranked ABOVE System Emails."""
    require_roles(actor, {"OPERATIONS", "FINANCE", "ADMIN"}, "Import Official Downloaded Report")

    raw_id, is_dup, redactions = _record_raw_event(
        conn,
        source_type="DOWNLOADED_REPORT",
        raw_content=csv_text,
        actor=actor,
        filename=filename,
        reference_for_dup=filename,
    )
    if is_dup:
        return {
            "duplicate": True,
            "raw_event_id": raw_id,
            "filename": filename,
            "processed_rows": 0,
            "confirmed_count": 0,
            "upgraded_count": 0,
            "exceptions_created": 1,
            "message": f"Report '{filename}' was already ingested (SHA-256 match). Duplicate blocked.",
        }

    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    if not reader.fieldnames:
        raise HTTPException(status_code=422, detail="CSV file is empty or missing headers.")

    def _pick(row: dict[str, str], keys: list[str], default: str = "") -> str:
        lower_map = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        for key in keys:
            val = lower_map.get(key.lower(), "")
            if val:
                return val
        return default

    processed = 0
    confirmed_count = 0
    upgraded_count = 0
    exceptions_created = 0
    row_results = []

    for row in reader:
        assessment_id = _pick(row, ["Assessment ID", "assessment_id", "Pulsifi Assessment ID", "ID"])
        if not assessment_id:
            continue
        candidate = _pick(
            row,
            ["Candidate Email", "Candidate Reference", "candidate", "candidate_email", "candidate_ref"],
            default=f"unknown-{assessment_id}",
        )
        campaign = _pick(row, ["Campaign", "Campaign Key", "Pulsifi Campaign", "Role", "Project Code"])
        assessment_type = _pick(row, ["Assessment Type", "Type", "Module"], default="Cognitive")
        status_raw = _pick(row, ["Status", "Event Status", "Assessment Status"], default="Completed")
        status_norm = next(
            (s for s in VALID_LIFECYCLE_STATUSES if s.lower() == status_raw.lower()),
            "Completed",
        )
        event_date = _pick(
            row,
            ["Event Date", "Completed Date", "Date", "Sent Date"],
            default=utc_now_iso()[:10],
        )[:10]

        project_info = resolve_campaign_mapping(conn, campaign)
        res = _upsert_assessment_and_post_ledger(
            conn,
            pulsifi_assessment_id=assessment_id,
            candidate_identifier=candidate,
            assessment_type=assessment_type,
            event_status=status_norm,
            event_date=event_date,
            source_type="DOWNLOADED_REPORT",
            actor=actor,
            raw_event_id=raw_id,
            project_info=project_info,
            campaign_key=campaign or None,
            timestamp_iso=f"{event_date}T12:00:00Z",
        )
        processed += 1
        if res["ledger_action"] == "POSTED_CONFIRMED":
            confirmed_count += 1
        elif res["ledger_action"] == "UPGRADED_PENDING_TO_CONFIRMED":
            upgraded_count += 1
        if res["exception"]:
            exceptions_created += 1

        row_results.append(
            {
                "assessment_id": assessment_id,
                "candidate_ref_hash": res["candidate_ref_hash"],
                "ledger_action": res["ledger_action"],
                "mapped": project_info is not None,
                "exception_code": res["exception"]["exception_code"] if res["exception"] else None,
            }
        )

    if exceptions_created > 0:
        conn.execute(
            "UPDATE raw_ingested_events SET processing_status = 'Partial' WHERE id = ?",
            (raw_id,),
        )

    log_audit(
        conn,
        actor=actor,
        action="DOWNLOADED_REPORT_IMPORTED",
        entity_type="raw_ingested_event",
        entity_id=raw_id,
        before=None,
        after={
            "filename": filename,
            "processed_rows": processed,
            "confirmed_count": confirmed_count,
            "upgraded_count": upgraded_count,
            "exceptions_created": exceptions_created,
            "pii_redactions": redactions,
        },
        reason=f"Imported Level 2 Downloaded Report '{filename}'",
    )

    return {
        "duplicate": False,
        "raw_event_id": raw_id,
        "filename": filename,
        "pii_redactions": redactions,
        "processed_rows": processed,
        "confirmed_count": confirmed_count,
        "upgraded_count": upgraded_count,
        "exceptions_created": exceptions_created,
        "rows": row_results,
    }


def map_campaign_and_backfill(
    conn: sqlite3.Connection,
    req: CampaignMappingCreateRequest,
    actor: Actor,
) -> dict[str, Any]:
    """Create a Pulsifi Campaign -> Project mapping and retroactively attribute pending records."""
    require_roles(actor, {"OPERATIONS", "FINANCE", "ADMIN"}, "Map Pulsifi Campaign to Project")

    proj = conn.execute(
        """
        SELECT p.id AS project_id, p.code AS project_code, p.name AS project_name,
               p.client_id, p.partner_id, p.pool_owner_type
        FROM projects p WHERE p.id = ?
        """,
        (req.project_id,),
    ).fetchone()
    if not proj:
        raise HTTPException(status_code=404, detail=f"Project {req.project_id} not found.")

    now = utc_now_iso()
    key = req.pulsifi_campaign_key.strip()
    existing = conn.execute(
        "SELECT id FROM campaign_mappings WHERE LOWER(pulsifi_campaign_key) = LOWER(?)", (key,)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE campaign_mappings SET project_id = ?, naming_convention_hint = ?, active = 1 WHERE id = ?",
            (req.project_id, req.naming_convention_hint, existing["id"]),
        )
        mapping_id = int(existing["id"])
    else:
        cur = conn.execute(
            """
            INSERT INTO campaign_mappings (
                pulsifi_campaign_key, project_id, naming_convention_hint, active, created_by, created_at
            ) VALUES (?, ?, ?, 1, ?, ?)
            """,
            (key, req.project_id, req.naming_convention_hint, actor.name, now),
        )
        mapping_id = int(cur.lastrowid)

    # Backfill unattributed assessments matching this campaign key
    unmapped_assessments = conn.execute(
        """
        SELECT * FROM assessments
        WHERE LOWER(COALESCE(pulsifi_campaign_key, '')) = LOWER(?)
          AND project_id IS NULL
        """,
        (key,),
    ).fetchall()

    backfilled_count = 0
    for a in unmapped_assessments:
        conn.execute(
            "UPDATE assessments SET client_id = ?, partner_id = ?, project_id = ? WHERE id = ?",
            (proj["client_id"], proj["partner_id"], proj["project_id"], a["id"]),
        )
        # Supersede any Pending UNASSIGNED transaction and append properly attributed Confirmed row
        pending_txs = conn.execute(
            """
            SELECT * FROM credit_transactions
            WHERE assessment_id = ? AND status = 'Pending' AND pool_owner_type = 'UNASSIGNED'
            """,
            (a["id"],),
        ).fetchall()
        for ptx in pending_txs:
            conn.execute(
                "UPDATE credit_transactions SET status = 'Superseded' WHERE id = ?",
                (ptx["id"],),
            )
            new_status = "Confirmed" if int(ptx["evidence_level"]) <= 3 else "Pending"
            tx_code = next_tx_code(conn)
            conn.execute(
                """
                INSERT INTO credit_transactions (
                    tx_code, tx_date, period_month, tx_type, client_id, partner_id, project_id,
                    pool_owner_type, assessment_id, reference_code, units, status,
                    evidence_level, source_type, parent_transaction_id, credit_rule_id,
                    raw_event_id, notes, created_by, created_at
                ) VALUES (?, ?, ?, 'Usage', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tx_code,
                    ptx["tx_date"],
                    ptx["period_month"],
                    proj["client_id"],
                    proj["partner_id"],
                    proj["project_id"],
                    proj["pool_owner_type"],
                    a["id"],
                    ptx["reference_code"],
                    ptx["units"],
                    new_status,
                    ptx["evidence_level"],
                    ptx["source_type"],
                    ptx["id"],
                    ptx["credit_rule_id"],
                    ptx["raw_event_id"],
                    f"Attributed via campaign mapping '{key}' -> {proj['project_name']}",
                    actor.name,
                    now,
                ),
            )
        backfilled_count += 1

    # Auto-resolve matching Unknown Mapping exceptions
    conn.execute(
        """
        UPDATE exceptions
        SET status = 'Resolved',
            resolution_notes = ?,
            resolved_by = ?,
            resolved_at = ?
        WHERE category = 'Unknown Mapping'
          AND LOWER(COALESCE(campaign_key, '')) = LOWER(?)
          AND status IN ('Open', 'In Review')
        """,
        (
            f"Mapped campaign '{key}' to project '{proj['project_name']}' ({backfilled_count} record(s) attributed).",
            actor.name,
            now,
            key,
        ),
    )

    log_audit(
        conn,
        actor=actor,
        action="CAMPAIGN_MAPPED",
        entity_type="campaign_mapping",
        entity_id=mapping_id,
        before=None,
        after={
            "pulsifi_campaign_key": key,
            "project_id": proj["project_id"],
            "project_name": proj["project_name"],
            "backfilled_assessments": backfilled_count,
        },
        reason=f"Mapped Pulsifi campaign '{key}' to {proj['project_name']}",
        timestamp=now,
    )

    return {
        "mapping_id": mapping_id,
        "pulsifi_campaign_key": key,
        "project_id": proj["project_id"],
        "project_name": proj["project_name"],
        "backfilled_assessments": backfilled_count,
    }
