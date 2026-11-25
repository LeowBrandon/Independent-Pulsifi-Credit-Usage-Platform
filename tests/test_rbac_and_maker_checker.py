"""Tests for RBAC Segregation of Duties (Maker-Checker) and append-only reversals."""
from __future__ import annotations


def test_maker_checker_segregation_of_duties(api_client):
    """Operations can submit an adjustment, CANNOT approve it; Finance Checker approves it cleanly."""
    # 1. Operations submits adjustment (+25)
    st_sub, _, tx = api_client.request(
        "POST",
        "/api/ledger/adjustments",
        json_body={
            "tx_date": "2026-09-19",
            "units": 25,
            "reference_code": "ADJ-TEST-001",
            "reason": "Verified Pulsifi retake credit waiver per ticket #9912",
        },
        headers={"X-Actor-Role": "OPERATIONS", "X-Actor-Name": "ops.user@firm.com"},
    )
    assert st_sub == 200
    assert tx["status"] == "Pending Approval"
    tx_id = tx["id"]

    # 2. Operations tries to approve -> BLOCKED (403)
    st_ops_block, _, _ = api_client.request(
        "POST",
        f"/api/ledger/adjustments/{tx_id}/decision",
        json_body={"decision": "APPROVE", "reason": "Self approval attempt"},
        headers={"X-Actor-Role": "OPERATIONS", "X-Actor-Name": "ops.user@firm.com"},
    )
    assert st_ops_block == 403

    # 3. Same user spoofing FINANCE role to self-approve -> STILL BLOCKED (403 Maker != Checker)
    st_self_block, _, err = api_client.request(
        "POST",
        f"/api/ledger/adjustments/{tx_id}/decision",
        json_body={"decision": "APPROVE", "reason": "Self approval as finance"},
        headers={"X-Actor-Role": "FINANCE", "X-Actor-Name": "ops.user@firm.com"},
    )
    assert st_self_block == 403
    assert "Maker-Checker" in err["detail"]

    # 4. Distinct Finance controller approves -> SUCCEEDS (200) and updates Confirmed Balance
    _, _, ov_before = api_client.request("GET", "/api/overview")
    st_fin, _, approved = api_client.request(
        "POST",
        f"/api/ledger/adjustments/{tx_id}/decision",
        json_body={"decision": "APPROVE", "reason": "Ticket #9912 verified against Pulsifi email"},
        headers={"X-Actor-Role": "FINANCE", "X-Actor-Name": "finance.controller@firm.com"},
    )
    assert st_fin == 200
    assert approved["status"] == "Confirmed"
    assert approved["approved_by"] == "finance.controller@firm.com"

    _, _, ov_after = api_client.request("GET", "/api/overview")
    assert ov_after["balance"]["confirmed_balance"] == ov_before["balance"]["confirmed_balance"] + 25


def test_append_only_reversal_workflow(api_client):
    """Reversals append a linked offsetting entry without modifying original Confirmed row."""
    _, _, ledger = api_client.request("GET", "/api/ledger?tx_type=Usage&status=Confirmed")
    orig = next(t for t in ledger["items"] if t["reference_code"] == "P-10291")
    _, _, ov_before = api_client.request("GET", "/api/overview")

    # Operations cannot post direct reversal -> 403
    st_block, _, _ = api_client.request(
        "POST",
        f"/api/ledger/{orig['id']}/reverse",
        json_body={"reason": "Incorrectly attributed"},
        headers={"X-Actor-Role": "OPERATIONS"},
    )
    assert st_block == 403

    # Finance posts append-only Reversal -> 200
    st_rev, _, rev = api_client.request(
        "POST",
        f"/api/ledger/{orig['id']}/reverse",
        json_body={"reason": "Candidate withdrew before scoring; Pulsifi waived charge"},
        headers={"X-Actor-Role": "FINANCE"},
    )
    assert st_rev == 200
    assert rev["tx_type"] == "Reversal"
    assert rev["units"] == -orig["units"]
    assert rev["parent_transaction_id"] == orig["id"]

    # Double reversal blocked -> 409
    st_dup, _, _ = api_client.request(
        "POST",
        f"/api/ledger/{orig['id']}/reverse",
        json_body={"reason": "Attempt second reversal"},
        headers={"X-Actor-Role": "FINANCE"},
    )
    assert st_dup == 409

    # Confirmed balance increased by reversed amount
    _, _, ov_after = api_client.request("GET", "/api/overview")
    assert ov_after["balance"]["confirmed_balance"] == ov_before["balance"]["confirmed_balance"] - orig["units"]
