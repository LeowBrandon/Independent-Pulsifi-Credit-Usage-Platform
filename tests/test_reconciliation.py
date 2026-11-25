"""Tests for the 4-tier confidence-scored Monthly Reconciliation Engine."""
from __future__ import annotations


def test_seeded_reconciliation_tiers_and_math(api_client):
    """Verify seeded Sep 2026 reconciliation ran all 4 confidence tiers accurately."""
    st, _, data = api_client.request("GET", "/api/reconciliations")
    assert st == 200
    latest = data["latest"]
    assert latest["period_month"] == "2026-09"
    assert latest["opening_internal"] == 690
    assert latest["topups_internal"] == 1000
    assert latest["usage_internal"] == 410
    assert latest["usage_official"] == 440
    assert latest["adjustments_internal"] == 20
    assert latest["adjustments_official"] == 0
    assert latest["ending_internal_confirmed"] == 1300
    assert latest["ending_official"] == 1250
    assert latest["variance_units"] == 50

    # Verify all 4 matching tiers occurred in line-level results (43 matched / 46 official = 93.5%)
    assert latest["exact_matches"] == 38
    assert latest["tier2_matches"] == 3
    assert latest["tier3_matches"] == 2
    assert latest["unmatched_official"] == 3
    assert latest["match_rate_pct"] == 93.5

    tiers = {ln["match_tier"] for ln in latest["lines"]}
    assert tiers >= {
        "1_EXACT_ID",
        "2_CANDIDATE_DATE",
        "3_CANDIDATE_TYPE",
        "4_UNMATCHED_OFFICIAL",
    }

    # Verify ZERO raw candidate emails stored in reconciliation_lines
    for ln in latest["lines"]:
        assert "@" not in (ln["official_candidate_hash"] or "")


def test_finance_finalize_reconciliation_with_excel_parallel_run(api_client):
    """Only Finance can finalize a reconciliation run and record Excel Parallel-Run balance."""
    _, _, data = api_client.request("GET", "/api/reconciliations")
    recon_id = data["latest"]["id"]

    # Operations blocked
    st_ops, _, _ = api_client.request(
        "POST",
        f"/api/reconciliations/{recon_id}/finalize",
        json_body={"excel_parallel_balance": 1300, "notes": "Ops signoff attempt"},
        headers={"X-Actor-Role": "OPERATIONS"},
    )
    assert st_ops == 403

    # Finance succeeds
    st_fin, _, finalized = api_client.request(
        "POST",
        f"/api/reconciliations/{recon_id}/finalize",
        json_body={"excel_parallel_balance": 1300, "notes": "Month 2 parallel run complete"},
        headers={"X-Actor-Role": "FINANCE"},
    )
    assert st_fin == 200
    assert finalized["status"] == "Finalized"
    assert finalized["excel_parallel_balance"] == 1300
    assert finalized["finalized_by"] == "finance.controller@consultingfirm.com"


def test_partner_statement_export_phase1(api_client):
    """Verify Phase 1 Partner Statement JSON and CSV exports work cleanly."""
    _, _, pools = api_client.request("GET", "/api/pools")
    p_alpha = next(p for p in pools["partner_pools"] if p["code"] == "PALPHA")

    st_json, _, stmt = api_client.request("GET", f"/api/statements/PARTNER/{p_alpha['id']}")
    assert st_json == 200
    assert stmt["owner"]["name"] == "Partner Alpha"
    assert stmt["summary"]["confirmed_used"] == p_alpha["confirmed_used"]

    st_csv, hdrs, csv_body = api_client.request(
        "GET", f"/api/statements/PARTNER/{p_alpha['id']}/export.csv"
    )
    assert st_csv == 200
    assert "text/csv" in hdrs["content-type"]
    assert "Partner Alpha" in csv_body
