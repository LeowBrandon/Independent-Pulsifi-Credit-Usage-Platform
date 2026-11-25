"""Unified Balance Engine (§11 & §12 harmonized) and §16 Health Evaluation."""
from __future__ import annotations

import sqlite3
from typing import Any

from ..config import evaluate_health_tier


def compute_balance_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    """Compute harmonized Confirmed, Estimated, and Official balances directly from the ledger.

    Harmonized Formulas (§11 + §12 fix):
      Confirmed Balance = Opening + Top-Ups + Approved Adjustments + Refunds/Reversals - Confirmed Usage - Expiry
      Estimated Balance = Confirmed Balance - Pending Usage
      Official Balance  = Latest verified ending balance from Pulsifi Official Monthly Statement
    """
    row = conn.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN status = 'Confirmed' AND tx_type = 'Opening Balance' THEN units ELSE 0 END), 0) AS opening_balance,
            COALESCE(SUM(CASE WHEN status = 'Confirmed' AND tx_type = 'Top-Up' THEN units ELSE 0 END), 0) AS top_ups,
            COALESCE(SUM(CASE WHEN status = 'Confirmed' AND tx_type = 'Adjustment' THEN units ELSE 0 END), 0) AS approved_adjustments,
            COALESCE(SUM(CASE WHEN status = 'Confirmed' AND tx_type = 'Usage' THEN -units ELSE 0 END), 0) AS gross_confirmed_usage,
            COALESCE(SUM(CASE WHEN status = 'Confirmed' AND tx_type IN ('Refund', 'Reversal') THEN units ELSE 0 END), 0) AS refunds_and_reversals,
            COALESCE(SUM(CASE WHEN status = 'Confirmed' AND tx_type = 'Expiry' THEN -units ELSE 0 END), 0) AS expired_units,
            COALESCE(SUM(CASE WHEN status = 'Confirmed' THEN units ELSE 0 END), 0) AS confirmed_balance,
            COALESCE(SUM(CASE WHEN status = 'Pending' AND units < 0 THEN -units ELSE 0 END), 0) AS pending_usage,
            COALESCE(SUM(CASE WHEN status = 'Pending Approval' THEN units ELSE 0 END), 0) AS pending_approval_units,
            COALESCE(SUM(CASE WHEN status = 'Pending Approval' THEN 1 ELSE 0 END), 0) AS pending_approval_count
        FROM credit_transactions
        """
    ).fetchone()

    opening_balance = int(row["opening_balance"])
    top_ups = int(row["top_ups"])
    total_funded = opening_balance + top_ups
    approved_adjustments = int(row["approved_adjustments"])
    gross_confirmed_usage = int(row["gross_confirmed_usage"])
    refunds_and_reversals = int(row["refunds_and_reversals"])
    net_confirmed_usage = gross_confirmed_usage - refunds_and_reversals
    expired_units = int(row["expired_units"])
    confirmed_balance = int(row["confirmed_balance"])
    pending_usage = int(row["pending_usage"])
    estimated_balance = confirmed_balance - pending_usage
    total_estimated_usage = net_confirmed_usage + pending_usage

    confirmed_remaining_pct = round((confirmed_balance / total_funded) * 100, 1) if total_funded > 0 else 0.0
    estimated_remaining_pct = round((estimated_balance / total_funded) * 100, 1) if total_funded > 0 else 0.0
    utilization_pct = round((total_estimated_usage / total_funded) * 100, 1) if total_funded > 0 else 0.0

    # Strict §16 health tier evaluated on conservative Estimated Balance %
    health = evaluate_health_tier(estimated_remaining_pct)
    confirmed_health = evaluate_health_tier(confirmed_remaining_pct)

    # Latest Official Balance from Reconciliation
    latest_recon = conn.execute(
        """
        SELECT recon_code, period_month, ending_official, ending_internal_confirmed,
               variance_units, match_rate_pct, status, run_at, excel_parallel_balance
        FROM reconciliations
        ORDER BY period_month DESC, id DESC
        LIMIT 1
        """
    ).fetchone()

    official_balance = int(latest_recon["ending_official"]) if latest_recon else None
    recon_gap = (confirmed_balance - official_balance) if official_balance is not None else 0

    # Open exceptions count (synced live across Overview, Activity, and Exceptions)
    open_exceptions = int(
        conn.execute(
            "SELECT COUNT(*) FROM exceptions WHERE status IN ('Open', 'In Review')"
        ).fetchone()[0]
    )

    # Advisory trailing 3-month burn rate (Phase 2 expands to predictive runway)
    monthly_rows = conn.execute(
        """
        SELECT period_month,
               COALESCE(SUM(CASE WHEN status = 'Confirmed' AND tx_type = 'Usage' THEN -units
                                 WHEN status = 'Confirmed' AND tx_type IN ('Refund', 'Reversal') THEN -units
                                 ELSE 0 END), 0) AS confirmed_used,
               COALESCE(SUM(CASE WHEN status = 'Pending' AND units < 0 THEN -units ELSE 0 END), 0) AS pending_used
        FROM credit_transactions
        WHERE tx_type IN ('Usage', 'Refund', 'Reversal')
          AND status IN ('Confirmed', 'Pending')
        GROUP BY period_month
        ORDER BY period_month ASC
        """
    ).fetchall()

    monthly_trend = [
        {
            "period_month": r["period_month"],
            "confirmed_used": int(r["confirmed_used"]),
            "pending_used": int(r["pending_used"]),
            "total_used": int(r["confirmed_used"]) + int(r["pending_used"]),
        }
        for r in monthly_rows
    ]

    # Use last 3 completed/active months with usage for advisory burn estimate
    recent_burns = [m["total_used"] for m in monthly_trend[-3:] if m["total_used"] > 0]
    avg_monthly_burn = round(sum(recent_burns) / len(recent_burns), 1) if recent_burns else 0.0
    advisory_runway_months = (
        round(estimated_balance / avg_monthly_burn, 1) if avg_monthly_burn > 0 else None
    )

    # Financial valuation (weighted average unit cost from active credit batches)
    batch_stats = conn.execute(
        """
        SELECT COALESCE(SUM(purchased_units), 0) AS batch_units,
               COALESCE(SUM(purchased_units * unit_cost), 0.0) AS total_spend
        FROM credit_batches
        """
    ).fetchone()
    batch_units = int(batch_stats["batch_units"])
    total_spend = float(batch_stats["total_spend"])
    avg_unit_cost = round(total_spend / batch_units, 2) if batch_units > 0 else 0.0

    return {
        "opening_balance": opening_balance,
        "top_ups": top_ups,
        "total_funded": total_funded,
        "approved_adjustments": approved_adjustments,
        "confirmed_usage": net_confirmed_usage,
        "expired_units": expired_units,
        "confirmed_balance": confirmed_balance,
        "pending_usage": pending_usage,
        "estimated_balance": estimated_balance,
        "total_estimated_usage": total_estimated_usage,
        "pending_approval_units": int(row["pending_approval_units"]),
        "pending_approval_count": int(row["pending_approval_count"]),
        "confirmed_remaining_pct": confirmed_remaining_pct,
        "estimated_remaining_pct": estimated_remaining_pct,
        "utilization_pct": utilization_pct,
        "health": health,
        "confirmed_health": confirmed_health,
        "official_balance": official_balance,
        "official_period": latest_recon["period_month"] if latest_recon else None,
        "official_recon_code": latest_recon["recon_code"] if latest_recon else None,
        "official_recon_status": latest_recon["status"] if latest_recon else None,
        "official_match_rate_pct": float(latest_recon["match_rate_pct"]) if latest_recon else None,
        "reconciliation_gap": recon_gap,
        "open_exceptions": open_exceptions,
        "avg_monthly_burn": avg_monthly_burn,
        "advisory_runway_months": advisory_runway_months,
        "avg_unit_cost_usd": avg_unit_cost,
        "estimated_remaining_value_usd": round(estimated_balance * avg_unit_cost, 2),
        "total_contract_spend_usd": round(total_spend, 2),
        "monthly_trend": monthly_trend,
    }


def compute_pool_breakdown(conn: sqlite3.Connection) -> dict[str, Any]:
    """Compute Client-Funded and Partner-Funded pool utilization with zero double-counting.

    Invariant:
      SUM(client_pools.confirmed_used) + SUM(partner_pools.confirmed_used) + unassigned.confirmed_used
      == balance_summary.confirmed_usage
    """
    client_rows = conn.execute(
        """
        SELECT c.id, c.code, c.name, c.allocated_credits, c.alert_threshold_pct, c.status,
               COALESCE(SUM(CASE WHEN t.status = 'Confirmed' AND t.pool_owner_type = 'CLIENT'
                                      AND t.tx_type IN ('Usage', 'Refund', 'Reversal')
                                 THEN -t.units ELSE 0 END), 0) AS confirmed_used,
               COALESCE(SUM(CASE WHEN t.status = 'Pending' AND t.pool_owner_type = 'CLIENT'
                                      AND t.units < 0
                                 THEN -t.units ELSE 0 END), 0) AS pending_used,
               COALESCE(SUM(CASE WHEN t.status = 'Confirmed' AND t.pool_owner_type = 'CLIENT'
                                      AND t.tx_type = 'Adjustment'
                                 THEN t.units ELSE 0 END), 0) AS adjustments
        FROM clients c
        LEFT JOIN credit_transactions t ON t.client_id = c.id
        GROUP BY c.id
        ORDER BY confirmed_used DESC, c.name ASC
        """
    ).fetchall()

    client_pools = []
    for r in client_rows:
        allocated = int(r["allocated_credits"])
        conf_used = int(r["confirmed_used"])
        pend_used = int(r["pending_used"])
        if allocated == 0 and conf_used == 0 and pend_used == 0:
            continue
        adj = int(r["adjustments"])
        est_used = conf_used + pend_used
        remaining = allocated + adj - est_used
        rem_pct = round((remaining / allocated) * 100, 1) if allocated > 0 else 0.0
        util_pct = round((est_used / allocated) * 100, 1) if allocated > 0 else 0.0
        client_pools.append(
            {
                "id": r["id"],
                "code": r["code"],
                "name": r["name"],
                "pool_type": "CLIENT",
                "allocated": allocated,
                "confirmed_used": conf_used,
                "pending_used": pend_used,
                "estimated_used": est_used,
                "adjustments": adj,
                "remaining": remaining,
                "remaining_pct": rem_pct,
                "utilization_pct": util_pct,
                "health": evaluate_health_tier(rem_pct),
                "status": r["status"],
            }
        )

    partner_rows = conn.execute(
        """
        SELECT p.id, p.code, p.name, p.partner_type, p.allocated_credits, p.alert_threshold_pct, p.status,
               COALESCE(SUM(CASE WHEN t.status = 'Confirmed' AND t.pool_owner_type = 'PARTNER'
                                      AND t.tx_type IN ('Usage', 'Refund', 'Reversal')
                                 THEN -t.units ELSE 0 END), 0) AS confirmed_used,
               COALESCE(SUM(CASE WHEN t.status = 'Pending' AND t.pool_owner_type = 'PARTNER'
                                      AND t.units < 0
                                 THEN -t.units ELSE 0 END), 0) AS pending_used,
               COALESCE(SUM(CASE WHEN t.status = 'Confirmed' AND t.pool_owner_type = 'PARTNER'
                                      AND t.tx_type = 'Adjustment'
                                 THEN t.units ELSE 0 END), 0) AS adjustments
        FROM partners p
        LEFT JOIN credit_transactions t ON t.partner_id = p.id
        GROUP BY p.id
        ORDER BY confirmed_used DESC, p.name ASC
        """
    ).fetchall()

    partner_pools = []
    for r in partner_rows:
        allocated = int(r["allocated_credits"])
        conf_used = int(r["confirmed_used"])
        pend_used = int(r["pending_used"])
        adj = int(r["adjustments"])
        est_used = conf_used + pend_used
        remaining = allocated + adj - est_used
        rem_pct = round((remaining / allocated) * 100, 1) if allocated > 0 else 0.0
        util_pct = round((est_used / allocated) * 100, 1) if allocated > 0 else 0.0
        partner_pools.append(
            {
                "id": r["id"],
                "code": r["code"],
                "name": r["name"],
                "pool_type": "PARTNER",
                "partner_type": r["partner_type"],
                "allocated": allocated,
                "confirmed_used": conf_used,
                "pending_used": pend_used,
                "estimated_used": est_used,
                "adjustments": adj,
                "remaining": remaining,
                "remaining_pct": rem_pct,
                "utilization_pct": util_pct,
                "health": evaluate_health_tier(rem_pct),
                "status": r["status"],
            }
        )

    unassigned_row = conn.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN status = 'Confirmed' AND tx_type IN ('Usage', 'Refund', 'Reversal')
                              THEN -units ELSE 0 END), 0) AS confirmed_used,
            COALESCE(SUM(CASE WHEN status = 'Pending' AND units < 0
                              THEN -units ELSE 0 END), 0) AS pending_used
        FROM credit_transactions
        WHERE pool_owner_type = 'UNASSIGNED'
        """
    ).fetchone()

    unassigned = {
        "confirmed_used": int(unassigned_row["confirmed_used"]),
        "pending_used": int(unassigned_row["pending_used"]),
        "estimated_used": int(unassigned_row["confirmed_used"]) + int(unassigned_row["pending_used"]),
    }

    total_client_confirmed = sum(c["confirmed_used"] for c in client_pools)
    total_partner_confirmed = sum(p["confirmed_used"] for p in partner_pools)
    total_client_pending = sum(c["pending_used"] for c in client_pools)
    total_partner_pending = sum(p["pending_used"] for p in partner_pools)

    return {
        "client_pools": client_pools,
        "partner_pools": partner_pools,
        "unassigned": unassigned,
        "reconciliation_check": {
            "client_confirmed_used": total_client_confirmed,
            "partner_confirmed_used": total_partner_confirmed,
            "unassigned_confirmed_used": unassigned["confirmed_used"],
            "sum_confirmed_used": total_client_confirmed + total_partner_confirmed + unassigned["confirmed_used"],
            "sum_pending_used": total_client_pending + total_partner_pending + unassigned["pending_used"],
        },
    }


def compute_active_alerts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Generate dynamic, data-driven alerts strictly aligned with §16 thresholds."""
    summary = compute_balance_summary(conn)
    pools = compute_pool_breakdown(conn)
    alerts: list[dict[str, Any]] = []

    # 1. Master pool §16 health alert
    tier = summary["health"]["tier"]
    if tier in ("YELLOW", "ORANGE", "RED"):
        severity = "High" if tier == "RED" else "Medium" if tier == "ORANGE" else "Watch"
        alerts.append(
            {
                "id": "master-balance-health",
                "category": "Low-Balance Alert",
                "severity": severity,
                "badge": summary["health"]["badge"],
                "title": f"Master Pool {summary['health']['label']} ({summary['estimated_remaining_pct']}% remaining)",
                "detail": (
                    f"Estimated balance is {summary['estimated_balance']:,} units "
                    f"(Confirmed: {summary['confirmed_balance']:,} − Pending: {summary['pending_usage']:,}) "
                    f"out of {summary['total_funded']:,} funded."
                ),
                "target_view": "overview",
            }
        )

    # 2. Reconciliation variance alert
    if summary["reconciliation_gap"] != 0:
        sign = "+" if summary["reconciliation_gap"] > 0 else ""
        alerts.append(
            {
                "id": "recon-variance",
                "category": "Reconciliation Variance",
                "severity": "High",
                "badge": "red",
                "title": f"Reconciliation variance: {sign}{summary['reconciliation_gap']:,} units ({summary['official_period']})",
                "detail": (
                    f"Confirmed internal balance ({summary['confirmed_balance']:,}) differs from "
                    f"Pulsifi Official Statement ({summary['official_balance']:,})."
                ),
                "target_view": "reconciliation",
            }
        )

    # 3. Pending Maker-Checker Approvals
    if summary["pending_approval_count"] > 0:
        alerts.append(
            {
                "id": "maker-checker-pending",
                "category": "Maker-Checker Approval",
                "severity": "Medium",
                "badge": "yellow",
                "title": f"{summary['pending_approval_count']} adjustment(s) awaiting Finance approval",
                "detail": (
                    f"Total pending adjustment value: {summary['pending_approval_units']:+,} units. "
                    f"Segregation of duties requires Finance sign-off before posting."
                ),
                "target_view": "ledger",
            }
        )

    # 4. Individual Client / Partner Pool utilization alerts (<= 20% remaining -> Orange/Red)
    for pool in pools["client_pools"] + pools["partner_pools"]:
        if pool["allocated"] > 0 and pool["health"]["tier"] in ("ORANGE", "RED"):
            alerts.append(
                {
                    "id": f"pool-{pool['pool_type'].lower()}-{pool['id']}",
                    "category": "Overuse / Pool Alert",
                    "severity": "High" if pool["health"]["tier"] == "RED" else "Medium",
                    "badge": pool["health"]["badge"],
                    "title": f"{pool['name']} at {pool['utilization_pct']}% utilization",
                    "detail": (
                        f"{pool['remaining']:,} of {pool['allocated']:,} units remaining "
                        f"({pool['pool_type'].title()} pool · {pool['health']['label']})."
                    ),
                    "target_view": "pools",
                }
            )

    # 5. Open Exceptions summary
    if summary["open_exceptions"] > 0:
        alerts.append(
            {
                "id": "open-exceptions",
                "category": "Exception Queue",
                "severity": "Medium",
                "badge": "orange",
                "title": f"{summary['open_exceptions']} open exception(s) require operational review",
                "detail": "Includes missing statement lines, unmapped campaigns, or blocked duplicates.",
                "target_view": "exceptions",
            }
        )

    return alerts
