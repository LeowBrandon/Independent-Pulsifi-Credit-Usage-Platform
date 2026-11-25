"""Append-only credit ledger, Maker-Checker approvals, reversals, and Phase 1 statements."""
from __future__ import annotations

import csv
import io
import sqlite3
from typing import Any

from fastapi import HTTPException

from ..schemas import AdjustmentRequest, ApprovalDecisionRequest, TopUpRequest
from ..security import Actor, enforce_maker_checker, require_roles
from .audit import log_audit, utc_now_iso


def next_tx_code(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM credit_transactions").fetchone()
    return f"TX-{26000 + int(row['next_id'])}"


def next_exception_code(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM exceptions").fetchone()
    return f"EXC-{int(row['next_id']):04d}"


def submit_adjustment(
    conn: sqlite3.Connection,
    req: AdjustmentRequest,
    actor: Actor,
) -> dict[str, Any]:
    """Submit a manual credit adjustment into Maker-Checker Pending Approval state."""
    require_roles(actor, {"OPERATIONS", "FINANCE", "ADMIN"}, "Submit Credit Adjustment")
    if req.units == 0:
        raise HTTPException(status_code=400, detail="Adjustment units must be non-zero.")

    client_id = None
    partner_id = None
    pool_owner_type = "MASTER"
    if req.project_id is not None:
        proj = conn.execute(
            "SELECT id, client_id, partner_id, pool_owner_type FROM projects WHERE id = ?",
            (req.project_id,),
        ).fetchone()
        if not proj:
            raise HTTPException(status_code=404, detail=f"Project {req.project_id} not found.")
        client_id = proj["client_id"]
        partner_id = proj["partner_id"]
        pool_owner_type = proj["pool_owner_type"]

    tx_code = next_tx_code(conn)
    now = utc_now_iso()
    period_month = req.tx_date[:7]

    cur = conn.execute(
        """
        INSERT INTO credit_transactions (
            tx_code, tx_date, period_month, tx_type, client_id, partner_id, project_id,
            pool_owner_type, reference_code, units, status, evidence_level, source_type,
            notes, created_by, created_at
        ) VALUES (?, ?, ?, 'Adjustment', ?, ?, ?, ?, ?, ?, 'Pending Approval', 5, 'MANUAL_ADJUSTMENT', ?, ?, ?)
        """,
        (
            tx_code,
            req.tx_date,
            period_month,
            client_id,
            partner_id,
            req.project_id,
            pool_owner_type,
            req.reference_code.strip(),
            req.units,
            req.reason.strip(),
            actor.name,
            now,
        ),
    )
    tx_id = int(cur.lastrowid)

    log_audit(
        conn,
        actor=actor,
        action="ADJUSTMENT_SUBMITTED",
        entity_type="credit_transaction",
        entity_id=tx_code,
        before=None,
        after={
            "id": tx_id,
            "tx_code": tx_code,
            "units": req.units,
            "reference_code": req.reference_code,
            "status": "Pending Approval",
        },
        reason=req.reason.strip(),
        timestamp=now,
    )
    return dict(conn.execute("SELECT * FROM credit_transactions WHERE id = ?", (tx_id,)).fetchone())


def decide_adjustment(
    conn: sqlite3.Connection,
    tx_id: int,
    req: ApprovalDecisionRequest,
    actor: Actor,
) -> dict[str, Any]:
    """Finance Checker approves or rejects a Pending Approval adjustment (Maker != Checker)."""
    row = conn.execute("SELECT * FROM credit_transactions WHERE id = ?", (tx_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Transaction not found.")
    if row["status"] != "Pending Approval":
        raise HTTPException(
            status_code=409,
            detail=f"Transaction {row['tx_code']} is '{row['status']}', not 'Pending Approval'.",
        )

    enforce_maker_checker(maker_name=row["created_by"], checker=actor)

    new_status = "Confirmed" if req.decision == "APPROVE" else "Rejected"
    now = utc_now_iso()
    before = dict(row)

    conn.execute(
        """
        UPDATE credit_transactions
        SET status = ?, approved_by = ?, approved_at = ?
        WHERE id = ?
        """,
        (new_status, actor.name, now, tx_id),
    )

    # Auto-resolve any open exception linked to this pending adjustment
    conn.execute(
        """
        UPDATE exceptions
        SET status = 'Resolved',
            resolution_notes = ?,
            resolved_by = ?,
            resolved_at = ?
        WHERE linked_tx_id = ? AND status IN ('Open', 'In Review')
        """,
        (
            f"Finance {req.decision.lower()}d adjustment {row['tx_code']}: {req.reason.strip()}",
            actor.name,
            now,
            tx_id,
        ),
    )

    updated = dict(conn.execute("SELECT * FROM credit_transactions WHERE id = ?", (tx_id,)).fetchone())
    log_audit(
        conn,
        actor=actor,
        action=f"ADJUSTMENT_{req.decision}D",
        entity_type="credit_transaction",
        entity_id=row["tx_code"],
        before={"status": before["status"], "approved_by": before["approved_by"]},
        after={"status": updated["status"], "approved_by": updated["approved_by"]},
        reason=req.reason.strip(),
        timestamp=now,
    )
    return updated


def create_reversal(
    conn: sqlite3.Connection,
    tx_id: int,
    reason: str,
    actor: Actor,
) -> dict[str, Any]:
    """Append an offsetting Reversal transaction instead of mutating/deleting a Confirmed row."""
    require_roles(actor, {"FINANCE"}, "Post Append-Only Ledger Reversal")
    orig = conn.execute("SELECT * FROM credit_transactions WHERE id = ?", (tx_id,)).fetchone()
    if not orig:
        raise HTTPException(status_code=404, detail="Original transaction not found.")
    if orig["status"] != "Confirmed":
        raise HTTPException(
            status_code=409,
            detail=f"Only Confirmed transactions can be reversed (current status: {orig['status']}).",
        )
    if orig["tx_type"] == "Reversal":
        raise HTTPException(status_code=400, detail="Cannot reverse a reversal transaction.")

    existing = conn.execute(
        "SELECT tx_code FROM credit_transactions WHERE parent_transaction_id = ? AND tx_type = 'Reversal'",
        (tx_id,),
    ).fetchone()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Transaction {orig['tx_code']} was already reversed by {existing['tx_code']}.",
        )

    tx_code = next_tx_code(conn)
    now = utc_now_iso()
    tx_date = now[:10]

    cur = conn.execute(
        """
        INSERT INTO credit_transactions (
            tx_code, tx_date, period_month, tx_type, client_id, partner_id, project_id,
            pool_owner_type, assessment_id, reference_code, units, status,
            evidence_level, source_type, parent_transaction_id, notes,
            created_by, created_at, approved_by, approved_at
        ) VALUES (?, ?, ?, 'Reversal', ?, ?, ?, ?, ?, ?, ?, 'Confirmed', 5, 'MANUAL_ADJUSTMENT', ?, ?, ?, ?, ?, ?)
        """,
        (
            tx_code,
            tx_date,
            orig["period_month"],
            orig["client_id"],
            orig["partner_id"],
            orig["project_id"],
            orig["pool_owner_type"],
            orig["assessment_id"],
            f"REV-{orig['tx_code']}",
            -int(orig["units"]),
            tx_id,
            f"Reversal of {orig['tx_code']}: {reason.strip()}",
            actor.name,
            now,
            actor.name,
            now,
        ),
    )
    rev_id = int(cur.lastrowid)
    rev_row = dict(conn.execute("SELECT * FROM credit_transactions WHERE id = ?", (rev_id,)).fetchone())

    log_audit(
        conn,
        actor=actor,
        action="LEDGER_REVERSAL_POSTED",
        entity_type="credit_transaction",
        entity_id=tx_code,
        before={"parent_tx_code": orig["tx_code"], "parent_units": orig["units"]},
        after={"reversal_tx_code": tx_code, "reversal_units": rev_row["units"]},
        reason=reason.strip(),
        timestamp=now,
    )
    return rev_row


def record_topup(
    conn: sqlite3.Connection,
    req: TopUpRequest,
    actor: Actor,
) -> dict[str, Any]:
    """Record an official bulk credit Top-Up invoice with batch expiry and unit cost."""
    require_roles(actor, {"FINANCE", "ADMIN"}, "Record Official Credit Top-Up")
    now = utc_now_iso()

    existing_batch = conn.execute(
        "SELECT id FROM credit_batches WHERE batch_ref = ?", (req.batch_ref.strip(),)
    ).fetchone()
    if existing_batch:
        raise HTTPException(status_code=409, detail=f"Batch reference '{req.batch_ref}' already exists.")

    cur_batch = conn.execute(
        """
        INSERT INTO credit_batches (
            batch_ref, invoice_ref, purchased_units, unit_cost, currency,
            purchased_at, expires_at, notes, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Active')
        """,
        (
            req.batch_ref.strip(),
            req.invoice_ref.strip(),
            req.units,
            req.unit_cost,
            req.currency.upper(),
            req.tx_date,
            req.expires_at,
            req.notes,
        ),
    )
    batch_id = int(cur_batch.lastrowid)
    tx_code = next_tx_code(conn)

    cur_tx = conn.execute(
        """
        INSERT INTO credit_transactions (
            tx_code, tx_date, period_month, tx_type, pool_owner_type,
            reference_code, units, status, evidence_level, source_type,
            batch_id, notes, created_by, created_at, approved_by, approved_at
        ) VALUES (?, ?, ?, 'Top-Up', 'MASTER', ?, ?, 'Confirmed', 1, 'OFFICIAL_INVOICE', ?, ?, ?, ?, ?, ?)
        """,
        (
            tx_code,
            req.tx_date,
            req.tx_date[:7],
            req.invoice_ref.strip(),
            req.units,
            batch_id,
            req.notes or f"Bulk purchase batch {req.batch_ref} ({req.currency} {req.unit_cost:.2f}/unit)",
            actor.name,
            now,
            actor.name,
            now,
        ),
    )
    tx_id = int(cur_tx.lastrowid)
    tx_row = dict(conn.execute("SELECT * FROM credit_transactions WHERE id = ?", (tx_id,)).fetchone())

    log_audit(
        conn,
        actor=actor,
        action="TOPUP_RECORDED",
        entity_type="credit_batch",
        entity_id=req.batch_ref.strip(),
        before=None,
        after={
            "tx_code": tx_code,
            "units": req.units,
            "unit_cost": req.unit_cost,
            "expires_at": req.expires_at,
        },
        reason=req.notes or f"Invoice {req.invoice_ref}",
        timestamp=now,
    )
    return tx_row


def query_ledger(
    conn: sqlite3.Connection,
    tx_type: str | None = None,
    status: str | None = None,
    period_month: str | None = None,
    search: str | None = None,
    include_superseded: bool = False,
) -> list[dict[str, Any]]:
    """Query joined credit ledger transactions."""
    clauses = []
    params: list[Any] = []
    if not include_superseded and not status:
        clauses.append("t.status != 'Superseded'")
    if tx_type and tx_type != "all":
        clauses.append("t.tx_type = ?")
        params.append(tx_type)
    if status and status != "all":
        clauses.append("t.status = ?")
        params.append(status)
    if period_month and period_month != "all":
        clauses.append("t.period_month = ?")
        params.append(period_month)
    if search:
        like = f"%{search.strip()}%"
        clauses.append(
            "(t.tx_code LIKE ? OR t.reference_code LIKE ? OR COALESCE(c.name, '') LIKE ? "
            "OR COALESCE(p.name, '') LIKE ? OR COALESCE(pr.name, '') LIKE ? OR COALESCE(t.notes, '') LIKE ?)"
        )
        params.extend([like, like, like, like, like, like])

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        SELECT t.*,
               c.name AS client_name, c.code AS client_code,
               p.name AS partner_name, p.code AS partner_code,
               pr.name AS project_name, pr.code AS project_code,
               a.pulsifi_assessment_id, a.candidate_ref_hash, a.assessment_type,
               parent_t.tx_code AS parent_tx_code,
               EXISTS(
                   SELECT 1 FROM credit_transactions rev
                   WHERE rev.parent_transaction_id = t.id AND rev.tx_type = 'Reversal'
               ) AS is_reversed
        FROM credit_transactions t
        LEFT JOIN clients c ON c.id = t.client_id
        LEFT JOIN partners p ON p.id = t.partner_id
        LEFT JOIN projects pr ON pr.id = t.project_id
        LEFT JOIN assessments a ON a.id = t.assessment_id
        LEFT JOIN credit_transactions parent_t ON parent_t.id = t.parent_transaction_id
        {where_sql}
        ORDER BY t.tx_date DESC, t.id DESC
        """,
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def render_ledger_csv(rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "Date",
            "Period",
            "Transaction Code",
            "Type",
            "Pool Owner",
            "Client",
            "Partner",
            "Project",
            "Reference",
            "Units",
            "Status",
            "Evidence Level",
            "Source",
            "Created By",
            "Approved By",
            "Parent Tx",
            "Notes",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r["tx_date"],
                r["period_month"],
                r["tx_code"],
                r["tx_type"],
                r["pool_owner_type"] or "",
                r.get("client_name") or "",
                r.get("partner_name") or "",
                r.get("project_name") or "",
                r["reference_code"],
                r["units"],
                r["status"],
                f"L{r['evidence_level']}",
                r["source_type"],
                r["created_by"],
                r.get("approved_by") or "",
                r.get("parent_tx_code") or "",
                r.get("notes") or "",
            ]
        )
    return buf.getvalue()


def build_pool_statement(
    conn: sqlite3.Connection,
    pool_type: str,
    pool_id: int,
    period_month: str | None = None,
) -> dict[str, Any]:
    """Generate a Phase 1 Client or Partner Credit Statement (CSV / Printable Report)."""
    ptype = pool_type.upper()
    if ptype == "CLIENT":
        owner = conn.execute("SELECT * FROM clients WHERE id = ?", (pool_id,)).fetchone()
        col = "t.client_id"
    elif ptype == "PARTNER":
        owner = conn.execute("SELECT * FROM partners WHERE id = ?", (pool_id,)).fetchone()
        col = "t.partner_id"
    else:
        raise HTTPException(status_code=400, detail="pool_type must be CLIENT or PARTNER.")

    if not owner:
        raise HTTPException(status_code=404, detail=f"{ptype} pool {pool_id} not found.")

    params: list[Any] = [pool_id, ptype]
    period_filter = ""
    if period_month and period_month != "all":
        period_filter = "AND t.period_month = ?"
        params.append(period_month)

    txs = conn.execute(
        f"""
        SELECT t.tx_date, t.period_month, t.tx_code, t.tx_type, t.reference_code,
               t.units, t.status, t.evidence_level, t.source_type, t.notes,
               c.name AS client_name, pr.name AS project_name,
               a.assessment_type, a.candidate_ref_hash
        FROM credit_transactions t
        LEFT JOIN clients c ON c.id = t.client_id
        LEFT JOIN projects pr ON pr.id = t.project_id
        LEFT JOIN assessments a ON a.id = t.assessment_id
        WHERE {col} = ? AND t.pool_owner_type = ?
          AND t.status IN ('Confirmed', 'Pending')
          {period_filter}
        ORDER BY t.tx_date DESC, t.id DESC
        """,
        params,
    ).fetchall()

    items = [dict(r) for r in txs]
    confirmed_used = sum(-r["units"] for r in items if r["status"] == "Confirmed" and r["tx_type"] in ("Usage", "Refund", "Reversal"))
    pending_used = sum(-r["units"] for r in items if r["status"] == "Pending" and r["units"] < 0)
    adjustments = sum(r["units"] for r in items if r["status"] == "Confirmed" and r["tx_type"] == "Adjustment")
    allocated = int(owner["allocated_credits"])
    remaining = allocated + adjustments - confirmed_used - pending_used

    return {
        "generated_at": utc_now_iso(),
        "pool_type": ptype,
        "owner": dict(owner),
        "period_filter": period_month or "All Periods",
        "summary": {
            "allocated_credits": allocated,
            "confirmed_used": confirmed_used,
            "pending_used": pending_used,
            "approved_adjustments": adjustments,
            "estimated_remaining": remaining,
        },
        "transactions": items,
        "disclaimer": (
            "Independent internal credit statement derived from firm ledger evidence. "
            "Confirmed figures are verified against Pulsifi official monthly reconciliation statements."
        ),
    }
