"""4-Tier Confidence-Scored Monthly Reconciliation Engine & Parallel-Run Cutover Tracker."""
from __future__ import annotations

import csv
import io
import sqlite3
from typing import Any

from fastapi import HTTPException

from ..security import Actor, anonymize_candidate, require_roles
from .audit import log_audit, utc_now_iso
from .ingestion import _create_exception_if_needed, _record_raw_event


def _next_recon_code(conn: sqlite3.Connection, period_month: str) -> str:
    cnt = int(
        conn.execute(
            "SELECT COUNT(*) FROM reconciliations WHERE period_month = ?", (period_month,)
        ).fetchone()[0]
    )
    return f"REC-{period_month}-{cnt + 1:02d}"


def run_reconciliation(
    conn: sqlite3.Connection,
    *,
    period_month: str,
    filename: str,
    csv_text: str,
    actor: Actor,
    excel_parallel_balance: int | None = None,
    run_at: str | None = None,
) -> dict[str, Any]:
    """Run the 4-tier matching engine against an uploaded Pulsifi Official Monthly Statement CSV.

    Matching Tiers (§18):
      Tier 1 (100%): Exact Pulsifi Assessment ID
      Tier 2 ( 90%): Anonymized Candidate Hash + Event Date
      Tier 3 ( 80%): Anonymized Candidate Hash + Assessment Type
      Tier 4 ( <80% / 0%): Unmatched Official Record -> Missing Record Exception
    """
    require_roles(actor, {"FINANCE", "OPERATIONS", "ADMIN"}, "Run Monthly Reconciliation")
    now = run_at or utc_now_iso()

    # Record PII-scrubbed official statement in raw_ingested_events (Level 1 Authoritative)
    raw_id, _is_dup, redactions = _record_raw_event(
        conn,
        source_type="OFFICIAL_STATEMENT",
        raw_content=f"{period_month}::{filename}::{csv_text}",
        actor=actor,
        filename=filename,
        reference_for_dup=f"STMT-{period_month}",
        ingested_at=now,
    )

    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    if not reader.fieldnames:
        raise HTTPException(status_code=422, detail="Official statement CSV is empty or missing headers.")

    def _pick(row: dict[str, str], keys: list[str], default: str = "") -> str:
        lower_map = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        for key in keys:
            val = lower_map.get(key.lower(), "")
            if val:
                return val
        return default

    # Compute Internal Period Ledger Totals
    opening_row = conn.execute(
        """
        SELECT COALESCE(SUM(units), 0) AS opening_bal
        FROM credit_transactions
        WHERE status = 'Confirmed' AND period_month < ?
        """,
        (period_month,),
    ).fetchone()
    opening_internal = int(opening_row["opening_bal"])

    period_row = conn.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN status = 'Confirmed' AND tx_type IN ('Opening Balance', 'Top-Up')
                              THEN units ELSE 0 END), 0) AS topups,
            COALESCE(SUM(CASE WHEN status = 'Confirmed' AND tx_type = 'Usage' THEN -units
                              WHEN status = 'Confirmed' AND tx_type IN ('Refund', 'Reversal') THEN -units
                              ELSE 0 END), 0) AS usage_net,
            COALESCE(SUM(CASE WHEN status = 'Confirmed' AND tx_type = 'Adjustment'
                              THEN units ELSE 0 END), 0) AS adjustments
        FROM credit_transactions
        WHERE period_month = ?
        """,
        (period_month,),
    ).fetchone()
    topups_internal = int(period_row["topups"])
    usage_internal = int(period_row["usage_net"])
    adjustments_internal = int(period_row["adjustments"])
    ending_internal_confirmed = opening_internal + topups_internal + adjustments_internal - usage_internal

    pending_total_row = conn.execute(
        """
        SELECT COALESCE(SUM(-units), 0) AS pending_usage
        FROM credit_transactions
        WHERE status = 'Pending' AND period_month <= ? AND units < 0
        """,
        (period_month,),
    ).fetchone()
    ending_internal_estimated = ending_internal_confirmed - int(pending_total_row["pending_usage"])

    # Parse Official Statement rows
    official_usage_rows: list[dict[str, Any]] = []
    opening_official: int | None = None
    topups_official: int | None = None
    adjustments_official = 0

    for idx, row in enumerate(reader, start=1):
        row_type = _pick(row, ["Row Type", "row_type", "Entry Type", "Line Type"], default="Usage").lower()
        units_str = _pick(row, ["Units", "Credit Units", "units", "Credits"], default="0")
        try:
            units_val = abs(int(float(units_str)))
            signed_val = int(float(units_str))
        except ValueError:
            units_val = 0
            signed_val = 0

        if row_type in ("opening", "opening balance"):
            opening_official = signed_val
            continue
        if row_type in ("top-up", "topup", "purchase"):
            topups_official = (topups_official or 0) + units_val
            continue
        if row_type == "adjustment":
            adjustments_official += signed_val
            continue

        official_id = _pick(row, ["Assessment ID", "assessment_id", "Pulsifi Assessment ID", "Reference"])
        candidate_raw = _pick(
            row,
            ["Candidate Email", "Candidate Reference", "candidate", "candidate_ref", "candidate_email"],
        )
        candidate_hash = anonymize_candidate(candidate_raw) if candidate_raw else ""
        ev_date = _pick(row, ["Date", "Event Date", "Completed Date", "tx_date"])[:10]
        a_type = _pick(row, ["Assessment Type", "Type", "Module"], default="Cognitive")
        official_usage_rows.append(
            {
                "row_num": idx,
                "assessment_id": official_id,
                "candidate_hash": candidate_hash,
                "date": ev_date,
                "assessment_type": a_type,
                "units": units_val,
            }
        )

    if opening_official is None:
        opening_official = opening_internal
    if topups_official is None:
        topups_official = topups_internal
    usage_official = sum(r["units"] for r in official_usage_rows)
    ending_official = opening_official + topups_official + adjustments_official - usage_official
    variance_units = ending_internal_confirmed - ending_official

    # Load internal confirmed usage transactions for the target period
    internal_txs = [
        dict(r)
        for r in conn.execute(
            """
            SELECT t.id, t.tx_code, t.tx_date, t.reference_code, ABS(t.units) AS abs_units,
                   t.assessment_id, a.pulsifi_assessment_id, a.candidate_ref_hash, a.assessment_type
            FROM credit_transactions t
            LEFT JOIN assessments a ON a.id = t.assessment_id
            WHERE t.period_month = ?
              AND t.status = 'Confirmed'
              AND t.tx_type = 'Usage'
            ORDER BY t.tx_date ASC, t.id ASC
            """,
            (period_month,),
        ).fetchall()
    ]

    matched_tx_ids: set[int] = set()
    lines: list[dict[str, Any]] = []
    exact_matches = 0
    tier2_matches = 0
    tier3_matches = 0
    unmatched_official = 0

    for off in official_usage_rows:
        matched_tx = None
        tier = "4_UNMATCHED_OFFICIAL"
        confidence = 0
        note = ""

        # Tier 1: Exact Assessment ID (100%)
        if off["assessment_id"]:
            for tx in internal_txs:
                if tx["id"] in matched_tx_ids:
                    continue
                internal_aid = (tx["pulsifi_assessment_id"] or tx["reference_code"] or "").strip()
                if internal_aid and internal_aid.lower() == off["assessment_id"].strip().lower():
                    matched_tx = tx
                    tier = "1_EXACT_ID"
                    confidence = 100
                    exact_matches += 1
                    note = f"Exact Assessment ID match with {tx['tx_code']}"
                    break

        # Tier 2: Candidate Hash + Event Date (90%)
        if matched_tx is None and off["candidate_hash"] and off["date"]:
            for tx in internal_txs:
                if tx["id"] in matched_tx_ids:
                    continue
                if (
                    tx["candidate_ref_hash"] == off["candidate_hash"]
                    and tx["tx_date"] == off["date"]
                ):
                    matched_tx = tx
                    tier = "2_CANDIDATE_DATE"
                    confidence = 90
                    tier2_matches += 1
                    note = (
                        f"Fallback Candidate+Date match with {tx['tx_code']} "
                        f"(internal ID: {tx['pulsifi_assessment_id'] or tx['reference_code']})"
                    )
                    break

        # Tier 3: Candidate Hash + Assessment Type (80%)
        if matched_tx is None and off["candidate_hash"] and off["assessment_type"]:
            for tx in internal_txs:
                if tx["id"] in matched_tx_ids:
                    continue
                if (
                    tx["candidate_ref_hash"] == off["candidate_hash"]
                    and (tx["assessment_type"] or "").lower() == off["assessment_type"].lower()
                ):
                    matched_tx = tx
                    tier = "3_CANDIDATE_TYPE"
                    confidence = 80
                    tier3_matches += 1
                    note = (
                        f"Potential Candidate+Type match with {tx['tx_code']} "
                        f"(date delta: internal {tx['tx_date']} vs official {off['date']})"
                    )
                    break

        if matched_tx is not None:
            matched_tx_ids.add(int(matched_tx["id"]))
            internal_units = int(matched_tx["abs_units"])
            unit_var = internal_units - off["units"]
            match_status = "Matched" if (unit_var == 0 and confidence >= 90) else "Needs Review"
            if unit_var != 0:
                note += f" · Unit variance {unit_var:+d}"
            lines.append(
                {
                    "official_row_num": off["row_num"],
                    "official_assessment_id": off["assessment_id"] or "—",
                    "official_candidate_hash": off["candidate_hash"] or "—",
                    "official_date": off["date"],
                    "official_type": off["assessment_type"],
                    "official_units": off["units"],
                    "matched_transaction_id": matched_tx["id"],
                    "matched_assessment_id": matched_tx["assessment_id"],
                    "internal_units": internal_units,
                    "match_tier": tier,
                    "match_confidence": confidence,
                    "unit_variance": unit_var,
                    "match_status": match_status,
                    "notes": note,
                }
            )
        else:
            unmatched_official += 1
            lines.append(
                {
                    "official_row_num": off["row_num"],
                    "official_assessment_id": off["assessment_id"] or f"ROW-{off['row_num']}",
                    "official_candidate_hash": off["candidate_hash"] or "—",
                    "official_date": off["date"],
                    "official_type": off["assessment_type"],
                    "official_units": off["units"],
                    "matched_transaction_id": None,
                    "matched_assessment_id": None,
                    "internal_units": 0,
                    "match_tier": "4_UNMATCHED_OFFICIAL",
                    "match_confidence": 0,
                    "unit_variance": -off["units"],
                    "match_status": "Missing Internal",
                    "notes": "Present on Pulsifi Official Statement but missing from Confirmed internal ledger.",
                }
            )

    # Record any internal confirmed usage transactions not matched on official statement
    unmatched_internal = 0
    for tx in internal_txs:
        if tx["id"] not in matched_tx_ids:
            unmatched_internal += 1
            lines.append(
                {
                    "official_row_num": None,
                    "official_assessment_id": tx["pulsifi_assessment_id"] or tx["reference_code"],
                    "official_candidate_hash": tx["candidate_ref_hash"] or "—",
                    "official_date": tx["tx_date"],
                    "official_type": tx["assessment_type"] or "Usage",
                    "official_units": 0,
                    "matched_transaction_id": tx["id"],
                    "matched_assessment_id": tx["assessment_id"],
                    "internal_units": int(tx["abs_units"]),
                    "match_tier": "5_INTERNAL_ONLY",
                    "match_confidence": 0,
                    "unit_variance": int(tx["abs_units"]),
                    "match_status": "Internal Only",
                    "notes": f"Confirmed internally ({tx['tx_code']}) but absent from Pulsifi statement.",
                }
            )

    total_official = len(official_usage_rows)
    matched_count = exact_matches + tier2_matches + tier3_matches
    match_rate_pct = round((matched_count / total_official) * 100, 1) if total_official > 0 else 100.0
    recon_status = "Matched" if (variance_units == 0 and unmatched_official == 0 and unmatched_internal == 0) else "Review Required"
    recon_code = _next_recon_code(conn, period_month)

    cur = conn.execute(
        """
        INSERT INTO reconciliations (
            recon_code, period_month, official_filename,
            opening_internal, opening_official,
            topups_internal, topups_official,
            usage_internal, usage_official,
            adjustments_internal, adjustments_official,
            ending_internal_confirmed, ending_internal_estimated, ending_official,
            variance_units, match_rate_pct,
            exact_matches, tier2_matches, tier3_matches,
            unmatched_official, unmatched_internal,
            excel_parallel_balance, status, run_by, run_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            recon_code,
            period_month,
            filename,
            opening_internal,
            opening_official,
            topups_internal,
            topups_official,
            usage_internal,
            usage_official,
            adjustments_internal,
            adjustments_official,
            ending_internal_confirmed,
            ending_internal_estimated,
            ending_official,
            variance_units,
            match_rate_pct,
            exact_matches,
            tier2_matches,
            tier3_matches,
            unmatched_official,
            unmatched_internal,
            excel_parallel_balance,
            recon_status,
            actor.name,
            now,
        ),
    )
    recon_id = int(cur.lastrowid)

    for ln in lines:
        conn.execute(
            """
            INSERT INTO reconciliation_lines (
                reconciliation_id, official_row_num, official_assessment_id,
                official_candidate_hash, official_date, official_type, official_units,
                matched_transaction_id, matched_assessment_id, internal_units,
                match_tier, match_confidence, unit_variance, match_status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                recon_id,
                ln["official_row_num"],
                ln["official_assessment_id"],
                ln["official_candidate_hash"],
                ln["official_date"],
                ln["official_type"],
                ln["official_units"],
                ln["matched_transaction_id"],
                ln["matched_assessment_id"],
                ln["internal_units"],
                ln["match_tier"],
                ln["match_confidence"],
                ln["unit_variance"],
                ln["match_status"],
                ln["notes"],
            ),
        )

        # Auto-create Missing Record exception for each unmatched official line
        if ln["match_tier"] == "4_UNMATCHED_OFFICIAL":
            _create_exception_if_needed(
                conn,
                category="Missing Record",
                severity="High",
                reference_code=ln["official_assessment_id"],
                owner_role="OPERATIONS",
                linked_event_id=raw_id,
                suggested_action=(
                    f"Pulsifi statement ({period_month}) billed {ln['official_units']} units for "
                    f"{ln['official_assessment_id']} ({ln['official_type']} on {ln['official_date']}), "
                    f"missing from internal ledger. Verify source evidence & backfill."
                ),
                created_at=now,
            )

    # Create period-level Balance Difference exception if variance != 0
    if variance_units != 0:
        exc = _create_exception_if_needed(
            conn,
            category="Balance Difference",
            severity="High",
            reference_code=recon_code,
            owner_role="FINANCE",
            linked_event_id=raw_id,
            suggested_action=(
                f"Period {period_month} variance is {variance_units:+d} units "
                f"(Usage diff: {usage_internal - usage_official:+d}, Adj diff: {adjustments_internal - adjustments_official:+d}). "
                f"Investigate {unmatched_official} missing record(s) and confirm timing adjustments."
            ),
            created_at=now,
        )
        conn.execute(
            "UPDATE exceptions SET linked_recon_id = ? WHERE id = ?",
            (recon_id, exc["id"]),
        )

    log_audit(
        conn,
        actor=actor,
        action="RECONCILIATION_RUN",
        entity_type="reconciliation",
        entity_id=recon_code,
        before=None,
        after={
            "period_month": period_month,
            "filename": filename,
            "ending_internal_confirmed": ending_internal_confirmed,
            "ending_official": ending_official,
            "variance_units": variance_units,
            "match_rate_pct": match_rate_pct,
            "pii_redactions": redactions,
        },
        reason=f"4-tier reconciliation executed for {period_month}",
        timestamp=now,
    )

    return get_reconciliation_detail(conn, recon_id)


def get_reconciliation_detail(conn: sqlite3.Connection, recon_id: int) -> dict[str, Any]:
    recon = conn.execute("SELECT * FROM reconciliations WHERE id = ?", (recon_id,)).fetchone()
    if not recon:
        raise HTTPException(status_code=404, detail="Reconciliation run not found.")

    lines = conn.execute(
        """
        SELECT rl.*, t.tx_code AS matched_tx_code,
               c.name AS client_name, pr.name AS project_name
        FROM reconciliation_lines rl
        LEFT JOIN credit_transactions t ON t.id = rl.matched_transaction_id
        LEFT JOIN clients c ON c.id = t.client_id
        LEFT JOIN projects pr ON pr.id = t.project_id
        WHERE rl.reconciliation_id = ?
        ORDER BY rl.match_confidence ASC, COALESCE(rl.official_row_num, 9999) ASC
        """,
        (recon_id,),
    ).fetchall()

    result = dict(recon)
    result["lines"] = [dict(l) for l in lines]
    return result


def finalize_reconciliation(
    conn: sqlite3.Connection,
    recon_id: int,
    actor: Actor,
    excel_parallel_balance: int | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Finance sign-off on a monthly reconciliation run (optionally logging Excel parallel-run balance)."""
    require_roles(actor, {"FINANCE"}, "Finalize Monthly Reconciliation")
    recon = conn.execute("SELECT * FROM reconciliations WHERE id = ?", (recon_id,)).fetchone()
    if not recon:
        raise HTTPException(status_code=404, detail="Reconciliation run not found.")

    now = utc_now_iso()
    before = {
        "status": recon["status"],
        "excel_parallel_balance": recon["excel_parallel_balance"],
    }
    conn.execute(
        """
        UPDATE reconciliations
        SET status = 'Finalized',
            excel_parallel_balance = COALESCE(?, excel_parallel_balance),
            finalized_by = ?,
            finalized_at = ?
        WHERE id = ?
        """,
        (excel_parallel_balance, actor.name, now, recon_id),
    )

    # Resolve period-level Balance Difference exception if Finance explicitly signs off
    conn.execute(
        """
        UPDATE exceptions
        SET status = 'Resolved',
            resolution_notes = ?,
            resolved_by = ?,
            resolved_at = ?
        WHERE linked_recon_id = ? AND status IN ('Open', 'In Review')
        """,
        (
            notes or f"Finance finalized reconciliation {recon['recon_code']}.",
            actor.name,
            now,
            recon_id,
        ),
    )

    log_audit(
        conn,
        actor=actor,
        action="RECONCILIATION_FINALIZED",
        entity_type="reconciliation",
        entity_id=recon["recon_code"],
        before=before,
        after={
            "status": "Finalized",
            "excel_parallel_balance": excel_parallel_balance
            if excel_parallel_balance is not None
            else recon["excel_parallel_balance"],
            "finalized_by": actor.name,
        },
        reason=notes or f"Monthly reconciliation sign-off for {recon['period_month']}",
        timestamp=now,
    )
    return get_reconciliation_detail(conn, recon_id)
