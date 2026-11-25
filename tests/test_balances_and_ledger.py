"""Tests verifying harmonized §11/§12 balance formulas, §16 tiers, pool reconciliation, and immutability."""
from __future__ import annotations

import sqlite3

import pytest

from app.config import EVIDENCE_HIERARCHY, evaluate_health_tier
from app.services.balance import compute_balance_summary, compute_pool_breakdown


def test_harmonized_balance_formulas_and_seed_math(seeded_db):
    """Verify §11 and §12 formulas agree 100% and seed totals reconcile exactly."""
    with seeded_db.session() as conn:
        summary = compute_balance_summary(conn)
        pools = compute_pool_breakdown(conn)

    # Exact formula checks:
    # Confirmed = Opening (3000) + Top-Ups (2000) + Approved Adj (20) - Confirmed Usage (3720) = 1300
    assert summary["opening_balance"] == 3000
    assert summary["top_ups"] == 2000
    assert summary["total_funded"] == 5000
    assert summary["approved_adjustments"] == 20
    assert summary["confirmed_usage"] == 3720
    assert summary["confirmed_balance"] == (
        summary["opening_balance"]
        + summary["top_ups"]
        + summary["approved_adjustments"]
        - summary["confirmed_usage"]
        - summary["expired_units"]
    )
    assert summary["confirmed_balance"] == 1300

    # Estimated = Confirmed (1300) - Pending Usage (45) = 1255
    assert summary["pending_usage"] == 45
    assert summary["estimated_balance"] == summary["confirmed_balance"] - summary["pending_usage"]
    assert summary["estimated_balance"] == 1255

    # Pending Approval adjustments (+15) MUST NOT affect Confirmed or Estimated until Finance approves
    assert summary["pending_approval_count"] == 1
    assert summary["pending_approval_units"] == 15

    # Official Balance from Sep statement (690 + 1000 - 440 = 1250), Gap = +50
    assert summary["official_balance"] == 1250
    assert summary["reconciliation_gap"] == 50

    # §16 Health Tier check: 1255 / 5000 = 25.1% -> strictly YELLOW (20-30%)
    assert summary["estimated_remaining_pct"] == 25.1
    assert summary["health"]["tier"] == "YELLOW"

    # Zero double-counting invariant: Client Pools + Partner Pools + Unassigned == Exact Ledger Usage
    check = pools["reconciliation_check"]
    assert check["sum_confirmed_used"] == summary["confirmed_usage"]
    assert check["sum_pending_used"] == summary["pending_usage"]


def test_section16_health_thresholds():
    """Verify strict §16 alert boundaries: Green >30%, Yellow 20-30%, Orange 10-20%, Red <10%."""
    assert evaluate_health_tier(30.7)["tier"] == "GREEN"
    assert evaluate_health_tier(30.1)["tier"] == "GREEN"
    assert evaluate_health_tier(30.0)["tier"] == "YELLOW"
    assert evaluate_health_tier(20.0)["tier"] == "YELLOW"
    assert evaluate_health_tier(19.9)["tier"] == "ORANGE"
    assert evaluate_health_tier(10.0)["tier"] == "ORANGE"
    assert evaluate_health_tier(9.9)["tier"] == "RED"


def test_evidence_hierarchy_reranked():
    """Verify Official Downloaded Report (L2) ranks ABOVE Pulsifi System Email (L3)."""
    assert EVIDENCE_HIERARCHY["OFFICIAL_STATEMENT"]["level"] == 1
    assert EVIDENCE_HIERARCHY["DOWNLOADED_REPORT"]["level"] == 2
    assert EVIDENCE_HIERARCHY["SYSTEM_EMAIL"]["level"] == 3
    assert EVIDENCE_HIERARCHY["CONTROLLED_INPUT"]["level"] == 4
    assert EVIDENCE_HIERARCHY["MANUAL_ADJUSTMENT"]["level"] == 5
    assert (
        EVIDENCE_HIERARCHY["DOWNLOADED_REPORT"]["level"]
        < EVIDENCE_HIERARCHY["SYSTEM_EMAIL"]["level"]
    )


def test_cross_screen_data_consistency(api_client):
    """Verify P-10294 attribution and Open Exception counts match across all endpoints."""
    st1, _, overview = api_client.request("GET", "/api/overview")
    st2, _, activity = api_client.request("GET", "/api/assessments")
    st3, _, ledger = api_client.request("GET", "/api/ledger")
    st4, _, exceptions = api_client.request("GET", "/api/exceptions")
    assert (st1, st2, st3, st4) == (200, 200, 200, 200)

    # Open exception count MUST match across Overview, Activity, and Exceptions
    open_rows = [e for e in exceptions["items"] if e["status"] in ("Open", "In Review")]
    assert overview["balance"]["open_exceptions"] == len(open_rows)
    assert overview["pipeline_counts"]["OPEN_EXCEPTIONS"] == len(open_rows)
    assert activity["pipeline"]["open_exceptions"] == len(open_rows)
    assert exceptions["summary"]["open_count"] == len(open_rows)

    # P-10294 must have identical client, project, and status in Activity and Ledger
    act_row = next(a for a in activity["items"] if a["pulsifi_assessment_id"] == "P-10294")
    led_row = next(t for t in ledger["items"] if t["reference_code"] == "P-10294")
    assert act_row["client_name"] == "ABC Ltd"
    assert led_row["client_name"] == "ABC Ltd"
    assert act_row["project_name"] == "Graduate Hiring 2026"
    assert led_row["project_name"] == "Graduate Hiring 2026"
    assert act_row["current_status"] == "Completed"
    assert led_row["status"] == "Confirmed"


def test_append_only_ledger_and_audit_immutability_triggers(seeded_db):
    """Verify SQLite triggers block UPDATE and DELETE on Confirmed ledger rows and audit_logs."""
    with seeded_db.session() as conn:
        tx = conn.execute(
            "SELECT id FROM credit_transactions WHERE status = 'Confirmed' LIMIT 1"
        ).fetchone()
        assert tx is not None

        with pytest.raises(sqlite3.IntegrityError, match="DELETE is prohibited"):
            conn.execute("DELETE FROM credit_transactions WHERE id = ?", (tx["id"],))

        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                "UPDATE credit_transactions SET units = 99999 WHERE id = ?", (tx["id"],)
            )

        audit_row = conn.execute("SELECT id FROM audit_logs LIMIT 1").fetchone()
        assert audit_row is not None
        with pytest.raises(sqlite3.IntegrityError, match="audit_logs is immutable"):
            conn.execute("DELETE FROM audit_logs WHERE id = ?", (audit_row["id"],))
        with pytest.raises(sqlite3.IntegrityError, match="audit_logs is immutable"):
            conn.execute(
                "UPDATE audit_logs SET reason = 'tampered' WHERE id = ?", (audit_row["id"],)
            )
