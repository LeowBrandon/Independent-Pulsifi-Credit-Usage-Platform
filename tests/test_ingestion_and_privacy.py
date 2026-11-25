"""Tests for PII scrubbing/hashing, SHA-256 idempotency, evidence upgrades, and effective-dated rules."""
from __future__ import annotations

from app.security import anonymize_candidate


def test_pii_anonymization_and_scrubbing_on_email_ingestion(api_client):
    """Verify raw candidate emails are NEVER persisted in assessments or raw_ingested_events."""
    raw_email = (
        "Assessment ID: P-10901\n"
        "Candidate Email: secret.person@private-domain.com\n"
        "Campaign Name: ABC-GRAD-2026\n"
        "Assessment Type: Cognitive\n"
        "Event Status: Completed\n"
        "Event Date: 2026-09-20\n"
    )
    status, _, body = api_client.request(
        "POST",
        "/api/ingest/system-email",
        json_body={"raw_email_text": raw_email, "subject": "Completed Notification"},
        headers={"X-Actor-Role": "OPERATIONS"},
    )
    assert status == 200
    assert body["duplicate"] is False
    assert body["pii_redactions"] >= 1
    expected_hash = anonymize_candidate("secret.person@private-domain.com")
    assert body["candidate_ref_hash"] == expected_hash
    assert "secret.person" not in body["assessment"]["candidate_ref_hash"]

    # Check raw_ingested_events preview contains zero raw PII
    st_gov, _, gov = api_client.request("GET", "/api/governance")
    assert st_gov == 200
    raw_ev = next(r for r in gov["raw_events"] if r["id"] == body["raw_event_id"])
    assert "secret.person@private-domain.com" not in raw_ev["payload_preview"]
    assert expected_hash in raw_ev["payload_preview"]

    # Re-ingesting exact same email must be blocked by SHA-256 idempotency (no double deduction)
    st_dup, _, dup_body = api_client.request(
        "POST",
        "/api/ingest/system-email",
        json_body={"raw_email_text": raw_email, "subject": "Completed Notification"},
        headers={"X-Actor-Role": "OPERATIONS"},
    )
    assert st_dup == 200
    assert dup_body["duplicate"] is True


def test_pending_controlled_input_upgraded_by_downloaded_report_no_double_count(api_client):
    """Verify L4 Controlled Input posts as Pending and L2 Downloaded Report upgrades without double counting."""
    _, _, before_ov = api_client.request("GET", "/api/overview")
    conf_before = before_ov["balance"]["confirmed_balance"]
    est_before = before_ov["balance"]["estimated_balance"]

    # 1. Capture Level 4 Controlled Input (Sent) -> Cognitive (5 units Pending)
    _, _, pools = api_client.request("GET", "/api/pools")
    abc_grad = next(p for p in pools["projects"] if p["code"] == "ABC-GRAD")

    st1, _, cap = api_client.request(
        "POST",
        "/api/ingest/controlled-input",
        json_body={
            "pulsifi_assessment_id": "P-10950",
            "candidate_identifier": "upgrade.tester@candidate.example",
            "project_id": abc_grad["id"],
            "assessment_type": "Cognitive",
            "event_status": "Sent",
            "event_date": "2026-09-20",
        },
        headers={"X-Actor-Role": "OPERATIONS"},
    )
    assert st1 == 200
    assert cap["transaction"]["status"] == "Pending"

    # Confirmed unchanged, Estimated decreased by 5
    _, _, mid_ov = api_client.request("GET", "/api/overview")
    assert mid_ov["balance"]["confirmed_balance"] == conf_before
    assert mid_ov["balance"]["estimated_balance"] == est_before - 5

    # 2. Upload Level 2 Downloaded Report confirming completion of P-10950
    csv_report = (
        "Assessment ID,Candidate Email,Campaign,Assessment Type,Status,Event Date\n"
        "P-10950,upgrade.tester@candidate.example,ABC-GRAD-2026,Cognitive,Completed,2026-09-21\n"
    )
    st2, _, rep = api_client.request(
        "GET", "/api/health"
    )
    assert st2 == 200
    st_up, _, up = api_client.post_multipart(
        "/api/ingest/downloaded-report",
        filename="pulsifi_upgrade_test.csv",
        file_content=csv_report,
        headers={"X-Actor-Role": "OPERATIONS"},
    )
    assert st_up == 200
    assert up["upgraded_count"] == 1

    # Confirmed decreased by 5, Estimated STILL est_before - 5 (ZERO double counting!)
    _, _, after_ov = api_client.request("GET", "/api/overview")
    assert after_ov["balance"]["confirmed_balance"] == conf_before - 5
    assert after_ov["balance"]["estimated_balance"] == est_before - 5


def test_effective_dated_credit_rules_protect_history(api_client):
    """Verify H1 Leadership rule (8 units) applies to May dates while H2 rule (10 units) applies to Sep."""
    raw_h1 = (
        "Assessment ID: P-10988\n"
        "Candidate Email: historic.lead@candidate.example\n"
        "Campaign Name: XYZ-LEAD-2026\n"
        "Assessment Type: Leadership\n"
        "Event Status: Completed\n"
        "Event Date: 2026-05-15\n"
    )
    st, _, res = api_client.request(
        "POST",
        "/api/ingest/system-email",
        json_body={"raw_email_text": raw_h1},
        headers={"X-Actor-Role": "OPERATIONS"},
    )
    assert st == 200
    assert res["transaction"]["units"] == -8


def test_unknown_campaign_mapping_backfill_workflow(api_client):
    """Verify unmapped campaign generates Unknown Mapping exception and 1-click mapping attributes it."""
    _, _, pools = api_client.request("GET", "/api/pools")
    acme_proj = next(p for p in pools["projects"] if p["code"] == "ACME-MGR")

    # Seed already includes P-10305 with campaign UNMAPPED-SG-FINTECH-Q3
    _, _, excs = api_client.request("GET", "/api/exceptions?category=Unknown+Mapping&status=Open")
    unmapped_exc = next(e for e in excs["items"] if e["campaign_key"] == "UNMAPPED-SG-FINTECH-Q3")

    # Resolve with 1-click mapping to ACME-MGR
    st, _, resolved = api_client.request(
        "POST",
        f"/api/exceptions/{unmapped_exc['id']}/resolve",
        json_body={
            "status": "Resolved",
            "resolution_notes": "Confirmed with project lead this campaign belongs to Acme Manager Pipeline",
            "map_to_project_id": acme_proj["id"],
        },
        headers={"X-Actor-Role": "OPERATIONS"},
    )
    assert st == 200
    assert resolved["backfill"]["backfilled_assessments"] == 1

    # Unassigned usage should now be 0!
    _, _, pools_after = api_client.request("GET", "/api/pools")
    assert pools_after["unassigned"]["estimated_used"] == 0
