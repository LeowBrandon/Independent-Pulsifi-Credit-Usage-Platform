"""Deterministic, 100% mathematically reconciled demo seed dataset for the MVP."""
from __future__ import annotations

import csv
import io
import sqlite3

from .config import SAMPLE_DATA_DIR
from .security import Actor, anonymize_candidate
from .services.audit import log_audit
from .services.ingestion import _create_exception_if_needed, _record_raw_event, _upsert_assessment_and_post_ledger
from .services.reconciliation import run_reconciliation

OPS_ACTOR = Actor(name="ops.lead@consultingfirm.com", role="OPERATIONS")
FINANCE_ACTOR = Actor(name="finance.controller@consultingfirm.com", role="FINANCE")
ADMIN_ACTOR = Actor(name="platform.admin@consultingfirm.com", role="ADMIN")


# 42 Confirmed Completed September 2026 assessments totaling exactly 410 units:
#   ABC Ltd (CLIENT):        130 units (16 records)
#   XYZ Group (CLIENT):       95 units (10 records)
#   Acme Holdings (CLIENT):   55 units ( 6 records)
#   Partner Alpha (PARTNER):  65 units ( 4 records -> total 490+65=555/650 = 85.4% ORANGE!)
#   Partner Beta (PARTNER):   40 units ( 4 records -> total 330+40=370/500 = 74.0% YELLOW!)
#   Partner Gamma (PARTNER):  25 units ( 2 records -> total 210+25=235/350 = 67.1% GREEN!)
#   Sum = 130 + 95 + 55 + 65 + 40 + 25 = 410 units!
SEP_CONFIRMED_ASSESSMENTS = [
    # (assessment_id, candidate_email, project_code, assessment_type, date, source_type, recon_match_mode)
    # ABC Ltd — Graduate Hiring & Sales Academy (130 units)
    ("P-10261", "aisha.tan@candidate.example", "ABC-GRAD", "Cognitive", "2026-09-02", "DOWNLOADED_REPORT", "EXACT"),
    ("P-10262", "bryan.lim@candidate.example", "ABC-GRAD", "Cognitive", "2026-09-02", "DOWNLOADED_REPORT", "EXACT"),
    ("P-10263", "chloe.ng@candidate.example", "ABC-GRAD", "Personality", "2026-09-03", "SYSTEM_EMAIL", "EXACT"),
    ("P-10264", "daniel.koh@candidate.example", "ABC-GRAD", "Leadership", "2026-09-03", "DOWNLOADED_REPORT", "EXACT"),
    ("P-10265", "evelyn.wong@candidate.example", "ABC-GRAD", "Leadership", "2026-09-04", "DOWNLOADED_REPORT", "EXACT"),
    ("P-10266", "farid.hassan@candidate.example", "ABC-SALES", "Sales Aptitude", "2026-09-04", "SYSTEM_EMAIL", "EXACT"),
    ("P-10267", "grace.chen@candidate.example", "ABC-SALES", "Leadership", "2026-09-05", "DOWNLOADED_REPORT", "EXACT"),
    ("P-10268", "hannah.lee@candidate.example", "ABC-GRAD", "Executive Suite", "2026-09-06", "DOWNLOADED_REPORT", "EXACT"),
    ("P-10269", "ivan.chua@candidate.example", "ABC-GRAD", "Leadership", "2026-09-07", "SYSTEM_EMAIL", "TIER2_NO_ID"),
    ("P-10270", "jasmine.goh@candidate.example", "ABC-SALES", "Sales Aptitude", "2026-09-08", "DOWNLOADED_REPORT", "EXACT"),
    ("P-10271", "kevin.ong@candidate.example", "ABC-GRAD", "Leadership", "2026-09-09", "DOWNLOADED_REPORT", "EXACT"),
    ("P-10272", "liwei.teoh@candidate.example", "ABC-GRAD", "Leadership", "2026-09-10", "SYSTEM_EMAIL", "EXACT"),
    ("P-10273", "maya.rajan@candidate.example", "ABC-SALES", "Personality", "2026-09-11", "DOWNLOADED_REPORT", "EXACT"),
    ("P-10291", "nathan.low@candidate.example", "ABC-GRAD", "Cognitive", "2026-09-12", "SYSTEM_EMAIL", "EXACT"),
    ("P-10294", "olivia.yeo@candidate.example", "ABC-GRAD", "Cognitive", "2026-09-12", "DOWNLOADED_REPORT", "EXACT"),
    ("P-10296", "priya.nair@candidate.example", "ABC-SALES", "Leadership", "2026-09-13", "SYSTEM_EMAIL", "EXACT"),
    # XYZ Group — Leadership Bench (95 units)
    ("P-10274", "quentin.ho@candidate.example", "XYZ-LEAD", "Leadership", "2026-09-02", "DOWNLOADED_REPORT", "EXACT"),
    ("P-10275", "rachel.sim@candidate.example", "XYZ-LEAD", "Leadership", "2026-09-03", "SYSTEM_EMAIL", "EXACT"),
    ("P-10276", "samuel.wee@candidate.example", "XYZ-LEAD", "Executive Suite", "2026-09-04", "DOWNLOADED_REPORT", "EXACT"),
    ("P-10277", "tessa.chia@candidate.example", "XYZ-LEAD", "Leadership", "2026-09-05", "DOWNLOADED_REPORT", "EXACT"),
    ("P-10278", "umar.malik@candidate.example", "XYZ-LEAD", "Cognitive", "2026-09-06", "SYSTEM_EMAIL", "TIER2_NO_ID"),
    ("P-10279", "valerie.fong@candidate.example", "XYZ-LEAD", "Leadership", "2026-09-08", "DOWNLOADED_REPORT", "EXACT"),
    ("P-10280", "wayne.teo@candidate.example", "XYZ-LEAD", "Leadership", "2026-09-09", "DOWNLOADED_REPORT", "EXACT"),
    ("P-10281", "xin.zhao@candidate.example", "XYZ-LEAD", "Personality", "2026-09-10", "SYSTEM_EMAIL", "TIER3_DATE_SHIFT"),
    ("P-10292", "yasmin.ali@candidate.example", "XYZ-LEAD", "Leadership", "2026-09-12", "SYSTEM_EMAIL", "EXACT"),
    ("P-10298", "zachary.kwan@candidate.example", "XYZ-LEAD", "Leadership", "2026-09-14", "DOWNLOADED_REPORT", "EXACT"),
    # Acme Holdings — Manager Pipeline (55 units)
    ("P-10282", "adrian.yap@candidate.example", "ACME-MGR", "Leadership", "2026-09-03", "DOWNLOADED_REPORT", "EXACT"),
    ("P-10283", "bella.soh@candidate.example", "ACME-MGR", "Leadership", "2026-09-05", "SYSTEM_EMAIL", "EXACT"),
    ("P-10284", "calvin.seet@candidate.example", "ACME-MGR", "Executive Suite", "2026-09-07", "DOWNLOADED_REPORT", "EXACT"),
    ("P-10285", "diana.pang@candidate.example", "ACME-MGR", "Cognitive", "2026-09-09", "DOWNLOADED_REPORT", "EXACT"),
    ("P-10286", "edwin.liew@candidate.example", "ACME-MGR", "Leadership", "2026-09-11", "SYSTEM_EMAIL", "TIER2_NO_ID"),
    ("P-10287", "fiona.tay@candidate.example", "ACME-MGR", "Personality", "2026-09-13", "DOWNLOADED_REPORT", "EXACT"),
    # Partner Alpha — Reseller Executive Search (65 units)
    ("P-10288", "gavin.loh@candidate.example", "PALPHA-EXEC", "Executive Suite", "2026-09-04", "DOWNLOADED_REPORT", "EXACT"),
    ("P-10289", "helen.choo@candidate.example", "PALPHA-EXEC", "Executive Suite", "2026-09-06", "DOWNLOADED_REPORT", "EXACT"),
    ("P-10290", "ian.mok@candidate.example", "PALPHA-EXEC", "Executive Suite", "2026-09-09", "SYSTEM_EMAIL", "EXACT"),
    ("P-10299", "joanne.ang@candidate.example", "PALPHA-EXEC", "Executive Suite", "2026-09-13", "DOWNLOADED_REPORT", "EXACT"),
    ("P-10300", "kenneth.foo@candidate.example", "PALPHA-EXEC", "Cognitive", "2026-09-14", "SYSTEM_EMAIL", "TIER3_DATE_SHIFT"),
    # Partner Beta — Reseller Tech Hiring (40 units)
    ("P-10301", "leonard.neo@candidate.example", "PBETA-TECH", "Leadership", "2026-09-05", "DOWNLOADED_REPORT", "EXACT"),
    ("P-10302", "melissa.khor@candidate.example", "PBETA-TECH", "Leadership", "2026-09-08", "SYSTEM_EMAIL", "EXACT"),
    ("P-10303", "nicholas.toh@candidate.example", "PBETA-TECH", "Leadership", "2026-09-11", "DOWNLOADED_REPORT", "EXACT"),
    ("P-10304", "paulina.see@candidate.example", "PBETA-TECH", "Leadership", "2026-09-14", "DOWNLOADED_REPORT", "EXACT"),
    # Partner Gamma — Reseller Ops Assessment (25 units)
    ("P-10307", "raymond.gan@candidate.example", "PGAMMA-OPS", "Executive Suite", "2026-09-07", "DOWNLOADED_REPORT", "EXACT"),
    ("P-10308", "sharon.lau@candidate.example", "PGAMMA-OPS", "Leadership", "2026-09-12", "SYSTEM_EMAIL", "EXACT"),
]
# Quick unit sum verification:
# ABC: 5+5+5+10+10+5+10+15+10+5+10+10+5+5+5+10 = 125? Let's make P-10296 Executive Suite?
# Wait: let's compute exact sums in code below and verify!
# ABC: Cognitive(5)x4=20, Personality(5)x2=10, Sales(5)x2=10, Leadership(10)x7=70, Exec(15)x1=15 => 125!
# Let's make P-10270 Leadership (10) so ABC = 130! Let's check exact arithmetic cleanly!


def _unit_for_type(assessment_type: str) -> int:
    return {
        "Cognitive": 5,
        "Personality": 5,
        "Sales Aptitude": 5,
        "Leadership": 10,
        "Executive Suite": 15,
    }[assessment_type]


def build_official_sep_statement_csv(confirmed_records: list[tuple[str, ...]]) -> str:
    """Generate the realistic September 2026 Pulsifi Official Monthly Statement CSV."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["Row Type", "Assessment ID", "Candidate Email", "Date", "Assessment Type", "Units", "Campaign"]
    )
    writer.writerow(["Opening", "OPENING-2026-09", "", "2026-09-01", "", "690", ""])
    writer.writerow(["Top-Up", "INV-PUL-2026-09", "", "2026-09-01", "", "1000", ""])

    for aid, email, proj_code, a_type, dt, _src, mode in confirmed_records:
        units = _unit_for_type(a_type)
        if mode == "EXACT":
            writer.writerow(["Usage", aid, email, dt, a_type, str(units), proj_code])
        elif mode == "TIER2_NO_ID":
            # Pulsifi monthly statement omitted internal prefix -> triggers Tier 2 Candidate+Date (90%)
            writer.writerow(["Usage", "", email, dt, a_type, str(units), proj_code])
        elif mode == "TIER3_DATE_SHIFT":
            # Timezone shift (+1 day) and missing ID -> triggers Tier 3 Candidate+Type (80%)
            day = int(dt[-2:]) + 1
            shifted_date = f"{dt[:8]}{day:02d}"
            writer.writerow(["Usage", "", email, shifted_date, a_type, str(units), proj_code])

    # 3 uncaptured records billed by Pulsifi (30 units total -> Tier 4 Missing Record exceptions!)
    writer.writerow(["Usage", "P-10311", "wendy.quek@candidate.example", "2026-09-15", "Leadership", "10", "XYZ-LEAD"])
    writer.writerow(["Usage", "P-10312", "xander.cho@candidate.example", "2026-09-16", "Leadership", "10", "ABC-GRAD"])
    writer.writerow(["Usage", "P-10313", "yvonne.heng@candidate.example", "2026-09-17", "Leadership", "10", "ACME-MGR"])
    return buf.getvalue()


def seed_database(conn: sqlite3.Connection, write_sample_csv: bool = True) -> None:
    """Populate database if empty with 100% mathematically reconciled data."""
    count = int(conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0])
    if count > 0:
        return

    # Fix P-10270 to Leadership so ABC = 130, total confirmed Sep = 410 exact
    sep_confirmed = [
        (aid, em, pc, ("Leadership" if aid == "P-10270" else at), dt, src, mode)
        for (aid, em, pc, at, dt, src, mode) in SEP_CONFIRMED_ASSESSMENTS
    ]
    assert sum(_unit_for_type(r[3]) for r in sep_confirmed) == 410

    # 1. Clients (3 Client-Funded direct pools + 1 Channel placeholder with 0 allocation)
    clients_data = [
        ("ABC", "ABC Ltd", 1500, 20.0, "hr.ops@abcltd.example", "2026-04-01T00:00:00Z"),
        ("XYZ", "XYZ Group", 1300, 20.0, "talent@xyzgroup.example", "2026-04-01T00:00:00Z"),
        ("ACME", "Acme Holdings", 800, 20.0, "people@acmeholdings.example", "2026-04-01T00:00:00Z"),
        ("CHANNEL", "Channel Reseller Clients", 0, 20.0, "channel@consultingfirm.com", "2026-04-01T00:00:00Z"),
    ]
    client_ids: dict[str, int] = {}
    for code, name, alloc, thresh, email, ts in clients_data:
        cur = conn.execute(
            """
            INSERT INTO clients (code, name, allocated_credits, alert_threshold_pct, contact_email, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'Active', ?)
            """,
            (code, name, alloc, thresh, email, ts),
        )
        client_ids[code] = int(cur.lastrowid)

    # 2. Partners (3 independent Reseller credit pools)
    partners_data = [
        ("PALPHA", "Partner Alpha", "RESELLER_POOL", 650, 20.0, "billing@partneralpha.example", "2026-04-01T00:00:00Z"),
        ("PBETA", "Partner Beta", "RESELLER_POOL", 500, 20.0, "ops@partnerbeta.example", "2026-04-01T00:00:00Z"),
        ("PGAMMA", "Partner Gamma", "RESELLER_POOL", 350, 20.0, "finance@partnergamma.example", "2026-04-01T00:00:00Z"),
    ]
    partner_ids: dict[str, int] = {}
    for code, name, ptype, alloc, thresh, email, ts in partners_data:
        cur = conn.execute(
            """
            INSERT INTO partners (code, name, partner_type, allocated_credits, alert_threshold_pct, contact_email, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'Active', ?)
            """,
            (code, name, ptype, alloc, thresh, email, ts),
        )
        partner_ids[code] = int(cur.lastrowid)

    # 3. Projects (Explicit pool_owner_type prevents Client vs Partner double-counting)
    projects_data = [
        ("ABC-GRAD", "Graduate Hiring 2026", "ABC", None, "CLIENT"),
        ("ABC-SALES", "Sales Academy Cohort", "ABC", None, "CLIENT"),
        ("XYZ-LEAD", "Leadership Bench", "XYZ", None, "CLIENT"),
        ("ACME-MGR", "Manager Pipeline", "ACME", None, "CLIENT"),
        ("PALPHA-EXEC", "Alpha Executive Search", "CHANNEL", "PALPHA", "PARTNER"),
        ("PBETA-TECH", "Beta Tech Hiring", "CHANNEL", "PBETA", "PARTNER"),
        ("PGAMMA-OPS", "Gamma Ops Assessment", "CHANNEL", "PGAMMA", "PARTNER"),
    ]
    project_map: dict[str, dict[str, object]] = {}
    for code, name, c_code, p_code, pool_owner in projects_data:
        cur = conn.execute(
            """
            INSERT INTO projects (code, name, client_id, partner_id, pool_owner_type, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'Active', '2026-04-01T00:00:00Z')
            """,
            (
                code,
                name,
                client_ids[c_code],
                partner_ids[p_code] if p_code else None,
                pool_owner,
            ),
        )
        project_map[code] = {
            "project_id": int(cur.lastrowid),
            "project_code": code,
            "project_name": name,
            "client_id": client_ids[c_code],
            "partner_id": partner_ids[p_code] if p_code else None,
            "pool_owner_type": pool_owner,
        }

    # 4. Pulsifi Campaign -> Project Mappings (Solves Attribution Gap Blind Spot)
    mappings_data = [
        ("ABC-GRAD-2026", "ABC-GRAD", "Standard convention: [CLIENT]-[PROJECT]-[YEAR]"),
        ("ABC Graduate Hiring", "ABC-GRAD", "Legacy Pulsifi role title alias"),
        ("ABC-SALES-2026", "ABC-SALES", "Standard convention: [CLIENT]-[PROJECT]-[YEAR]"),
        ("XYZ-LEAD-2026", "XYZ-LEAD", "Standard convention: [CLIENT]-[PROJECT]-[YEAR]"),
        ("XYZ Leadership Bench", "XYZ-LEAD", "Legacy Pulsifi campaign title alias"),
        ("ACME-MGR-2026", "ACME-MGR", "Standard convention: [CLIENT]-[PROJECT]-[YEAR]"),
        ("PALPHA-EXEC-2026", "PALPHA-EXEC", "Partner Alpha reseller campaign prefix"),
        ("PBETA-TECH-2026", "PBETA-TECH", "Partner Beta reseller campaign prefix"),
        ("PGAMMA-OPS-2026", "PGAMMA-OPS", "Partner Gamma reseller campaign prefix"),
    ]
    for campaign_key, proj_code, hint in mappings_data:
        conn.execute(
            """
            INSERT INTO campaign_mappings (
                pulsifi_campaign_key, project_id, naming_convention_hint, active, created_by, created_at
            ) VALUES (?, ?, ?, 1, ?, '2026-04-01T08:00:00Z')
            """,
            (campaign_key, project_map[proj_code]["project_id"], hint, ADMIN_ACTOR.name),
        )

    # 5. Effective-Dated Credit Rules (Protects historical transactions from mid-year rate changes)
    rules_data = [
        ("Cognitive", "Completed", 5, 1, "2026-01-01", None, "Standard cognitive battery (5 units)"),
        ("Personality", "Completed", 5, 1, "2026-01-01", None, "Work personality profile (5 units)"),
        ("Sales Aptitude", "Completed", 5, 1, "2026-01-01", None, "Commercial & sales readiness (5 units)"),
        ("Leadership", "Completed", 8, 1, "2026-01-01", "2026-06-30", "H1 2026 contract rate (superseded Jul 1)"),
        ("Leadership", "Completed", 10, 1, "2026-07-01", None, "H2 2026 updated Leadership suite rate (10 units)"),
        ("Executive Suite", "Completed", 15, 1, "2026-01-01", None, "Full C-suite multi-module bundle (15 units)"),
    ]
    for atype, trig, units, refund, eff_from, eff_to, notes in rules_data:
        conn.execute(
            """
            INSERT INTO credit_rules (
                assessment_type, trigger_event, credit_units, refund_on_cancel,
                effective_from, effective_to, notes, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '2026-04-01T08:00:00Z')
            """,
            (atype, trig, units, refund, eff_from, eff_to, notes, ADMIN_ACTOR.name),
        )

    # 6. Credit Batches & Funding Ledger Entries (Total Funded = 5,000 units = $59,000)
    batches = [
        ("PUL-2026-Q2", "INV-PUL-2026-04", 3000, 12.00, "2026-04-01", "2027-03-31", "Opening Balance", "OPENING_BALANCE", "Initial annual bulk pack"),
        ("PUL-2026-Q3A", "INV-PUL-2026-07", 1000, 11.50, "2026-07-01", "2027-06-30", "Top-Up", "OFFICIAL_INVOICE", "Q3 volume tier top-up"),
        ("PUL-2026-Q3B", "INV-PUL-2026-09", 1000, 11.50, "2026-09-01", "2027-08-31", "Top-Up", "OFFICIAL_INVOICE", "Sep expansion top-up"),
    ]
    tx_counter = 26000
    for batch_ref, inv_ref, units, cost, pdate, exp_date, tx_type, src_type, notes in batches:
        cur_b = conn.execute(
            """
            INSERT INTO credit_batches (
                batch_ref, invoice_ref, purchased_units, unit_cost, currency,
                purchased_at, expires_at, notes, status
            ) VALUES (?, ?, ?, ?, 'USD', ?, ?, ?, 'Active')
            """,
            (batch_ref, inv_ref, units, cost, pdate, exp_date, notes),
        )
        tx_counter += 1
        conn.execute(
            """
            INSERT INTO credit_transactions (
                tx_code, tx_date, period_month, tx_type, pool_owner_type, reference_code,
                units, status, evidence_level, source_type, batch_id, notes,
                created_by, created_at, approved_by, approved_at
            ) VALUES (?, ?, ?, ?, 'MASTER', ?, ?, 'Confirmed', 1, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"TX-{tx_counter}",
                pdate,
                pdate[:7],
                tx_type,
                inv_ref,
                units,
                src_type,
                int(cur_b.lastrowid),
                f"{notes} ({batch_ref})",
                FINANCE_ACTOR.name,
                f"{pdate}T09:00:00Z",
                FINANCE_ACTOR.name,
                f"{pdate}T09:00:00Z",
            ),
        )

    # 7. Historical Confirmed Monthly Usage (Apr–Aug 2026 = 3,310 units exact)
    # Reconciled against finalized monthly statements; zero discrepancy through Aug 31.
    hist_usage = [
        # (month, date, project_code, units)
        ("2026-04", "2026-04-30", "ABC-GRAD", 150),
        ("2026-04", "2026-04-30", "XYZ-LEAD", 130),
        ("2026-04", "2026-04-30", "ACME-MGR", 80),
        ("2026-04", "2026-04-30", "PALPHA-EXEC", 75),
        ("2026-04", "2026-04-30", "PBETA-TECH", 50),
        ("2026-04", "2026-04-30", "PGAMMA-OPS", 35),
        ("2026-05", "2026-05-31", "ABC-GRAD", 175),
        ("2026-05", "2026-05-31", "XYZ-LEAD", 150),
        ("2026-05", "2026-05-31", "ACME-MGR", 95),
        ("2026-05", "2026-05-31", "PALPHA-EXEC", 90),
        ("2026-05", "2026-05-31", "PBETA-TECH", 60),
        ("2026-05", "2026-05-31", "PGAMMA-OPS", 40),
        ("2026-06", "2026-06-30", "ABC-SALES", 195),
        ("2026-06", "2026-06-30", "XYZ-LEAD", 165),
        ("2026-06", "2026-06-30", "ACME-MGR", 105),
        ("2026-06", "2026-06-30", "PALPHA-EXEC", 100),
        ("2026-06", "2026-06-30", "PBETA-TECH", 70),
        ("2026-06", "2026-06-30", "PGAMMA-OPS", 45),
        ("2026-07", "2026-07-31", "ABC-GRAD", 215),
        ("2026-07", "2026-07-31", "XYZ-LEAD", 180),
        ("2026-07", "2026-07-31", "ACME-MGR", 115),
        ("2026-07", "2026-07-31", "PALPHA-EXEC", 110),
        ("2026-07", "2026-07-31", "PBETA-TECH", 75),
        ("2026-07", "2026-07-31", "PGAMMA-OPS", 45),
        ("2026-08", "2026-08-31", "ABC-GRAD", 220),
        ("2026-08", "2026-08-31", "XYZ-LEAD", 185),
        ("2026-08", "2026-08-31", "ACME-MGR", 120),
        ("2026-08", "2026-08-31", "PALPHA-EXEC", 115),
        ("2026-08", "2026-08-31", "PBETA-TECH", 75),
        ("2026-08", "2026-08-31", "PGAMMA-OPS", 45),
    ]
    for period, dt, proj_code, units in hist_usage:
        pinfo = project_map[proj_code]
        tx_counter += 1
        conn.execute(
            """
            INSERT INTO credit_transactions (
                tx_code, tx_date, period_month, tx_type, client_id, partner_id, project_id,
                pool_owner_type, reference_code, units, status, evidence_level, source_type,
                notes, created_by, created_at, approved_by, approved_at
            ) VALUES (?, ?, ?, 'Usage', ?, ?, ?, ?, ?, ?, 'Confirmed', 1, 'OFFICIAL_STATEMENT', ?, ?, ?, ?, ?)
            """,
            (
                f"TX-{tx_counter}",
                dt,
                period,
                pinfo["client_id"],
                pinfo["partner_id"],
                pinfo["project_id"],
                pinfo["pool_owner_type"],
                f"STMT-{period}-{proj_code}",
                -units,
                f"Reconciled {period} monthly usage ({pinfo['project_name']})",
                FINANCE_ACTOR.name,
                f"{dt}T18:00:00Z",
                FINANCE_ACTOR.name,
                f"{dt}T18:00:00Z",
            ),
        )

    # Finalized August 2026 Reconciliation (Month 1 of 2-Month Excel Parallel Run)
    conn.execute(
        """
        INSERT INTO reconciliations (
            recon_code, period_month, official_filename,
            opening_internal, opening_official, topups_internal, topups_official,
            usage_internal, usage_official, adjustments_internal, adjustments_official,
            ending_internal_confirmed, ending_internal_estimated, ending_official,
            variance_units, match_rate_pct, exact_matches, tier2_matches, tier3_matches,
            unmatched_official, unmatched_internal, excel_parallel_balance,
            status, run_by, run_at, finalized_by, finalized_at
        ) VALUES (
            'REC-2026-08-01', '2026-08', 'pulsifi_official_statement_2026_08.csv',
            1450, 1450, 0, 0, 760, 760, 0, 0,
            690, 690, 690, 0, 100.0, 94, 0, 0, 0, 0, 690,
            'Finalized', ?, '2026-09-02T10:00:00Z', ?, '2026-09-02T15:30:00Z'
        )
        """,
        (OPS_ACTOR.name, FINANCE_ACTOR.name),
    )

    # 8. September 2026 Individual Assessments — Confirmed (42 records = 410 units)
    for aid, email, proj_code, a_type, dt, src_type, _mode in sep_confirmed:
        pinfo = project_map[proj_code]
        raw_payload = (
            f"Source={src_type} | AssessmentID={aid} | Candidate={email} | "
            f"Campaign={proj_code}-2026 | Type={a_type} | Status=Completed | Date={dt}"
        )
        raw_id, _dup, _red = _record_raw_event(
            conn,
            source_type=src_type,
            raw_content=raw_payload,
            actor=OPS_ACTOR,
            filename=(f"pulsifi_export_{dt}.csv" if src_type == "DOWNLOADED_REPORT" else f"notif_{aid}.eml"),
            reference_for_dup=aid,
            ingested_at=f"{dt}T11:30:00Z",
        )
        res = _upsert_assessment_and_post_ledger(
            conn,
            pulsifi_assessment_id=aid,
            candidate_identifier=email,
            assessment_type=a_type,
            event_status="Completed",
            event_date=dt,
            source_type=src_type,
            actor=OPS_ACTOR,
            raw_event_id=raw_id,
            project_info=pinfo,
            campaign_key=f"{proj_code}-2026",
            timestamp_iso=f"{dt}T11:30:00Z",
        )
        # Populate realistic earlier lifecycle timestamps (Created -> Sent -> Started -> Completed)
        aid_db = res["assessment"]["id"]
        conn.execute(
            """
            UPDATE assessments
            SET created_at = ?, sent_at = ?, started_at = ?, completed_at = ?
            WHERE id = ?
            """,
            (f"{dt}T08:00:00Z", f"{dt}T08:15:00Z", f"{dt}T09:45:00Z", f"{dt}T11:20:00Z", aid_db),
        )

    # 9. September 2026 Pending Controlled Inputs (5 records = 35 units)
    pending_inputs = [
        ("P-10293", "zoe.lim@candidate.example", "ACME-MGR", "Personality", "Sent", "2026-09-14"),
        ("P-10309", "aaron.ng@candidate.example", "ABC-GRAD", "Cognitive", "Started", "2026-09-15"),
        ("P-10310", "bianca.tan@candidate.example", "XYZ-LEAD", "Leadership", "Sent", "2026-09-15"),
        ("P-10314", "cindy.wong@candidate.example", "PALPHA-EXEC", "Leadership", "Started", "2026-09-16"),
        ("P-10315", "derek.koh@candidate.example", "PBETA-TECH", "Cognitive", "Sent", "2026-09-16"),
    ]
    for aid, email, proj_code, a_type, status, dt in pending_inputs:
        pinfo = project_map[proj_code]
        raw_id, _dup, _red = _record_raw_event(
            conn,
            source_type="CONTROLLED_INPUT",
            raw_content=f"ControlledInput|{aid}|{email}|{proj_code}|{a_type}|{status}|{dt}",
            actor=OPS_ACTOR,
            reference_for_dup=aid,
            ingested_at=f"{dt}T10:00:00Z",
        )
        res = _upsert_assessment_and_post_ledger(
            conn,
            pulsifi_assessment_id=aid,
            candidate_identifier=email,
            assessment_type=a_type,
            event_status=status,
            event_date=dt,
            source_type="CONTROLLED_INPUT",
            actor=OPS_ACTOR,
            raw_event_id=raw_id,
            project_info=pinfo,
            campaign_key=proj_code,
            notes="Awaiting Pulsifi Downloaded Report or System Email confirmation",
            timestamp_iso=f"{dt}T10:00:00Z",
        )
        aid_db = res["assessment"]["id"]
        conn.execute(
            "UPDATE assessments SET created_at = ?, sent_at = ? WHERE id = ?",
            (f"{dt}T09:30:00Z", f"{dt}T09:45:00Z", aid_db),
        )

    # 10. 1 Unmapped Campaign System Email (10 units Pending UNASSIGNED + Unknown Mapping exception!)
    raw_unmapped_id, _dup, _red = _record_raw_event(
        conn,
        source_type="SYSTEM_EMAIL",
        raw_content=(
            "Assessment ID: P-10305\nCandidate Email: elaine.chong@candidate.example\n"
            "Campaign: UNMAPPED-SG-FINTECH-Q3\nAssessment Type: Leadership\nStatus: Completed\nDate: 2026-09-15"
        ),
        actor=OPS_ACTOR,
        filename="notif_P-10305.eml",
        reference_for_dup="P-10305",
        ingested_at="2026-09-15T14:20:00Z",
    )
    _upsert_assessment_and_post_ledger(
        conn,
        pulsifi_assessment_id="P-10305",
        candidate_identifier="elaine.chong@candidate.example",
        assessment_type="Leadership",
        event_status="Completed",
        event_date="2026-09-15",
        source_type="SYSTEM_EMAIL",
        actor=OPS_ACTOR,
        raw_event_id=raw_unmapped_id,
        project_info=None,
        campaign_key="UNMAPPED-SG-FINTECH-Q3",
        timestamp_iso="2026-09-15T14:20:00Z",
    )

    # 11. 3 Non-Billable Lifecycle Assessments (Cancelled, Failed, Expired -> 0 units deducted)
    non_billable = [
        ("P-10295", "frank.chen@candidate.example", "XYZ-LEAD", "Leadership", "Cancelled", "2026-09-12"),
        ("P-10297", "gloria.lim@candidate.example", "ACME-MGR", "Cognitive", "Failed", "2026-09-13"),
        ("P-10306", "henry.ong@candidate.example", "ABC-SALES", "Personality", "Expired", "2026-09-15"),
    ]
    for aid, email, proj_code, a_type, status, dt in non_billable:
        pinfo = project_map[proj_code]
        raw_id, _dup, _red = _record_raw_event(
            conn,
            source_type="SYSTEM_EMAIL",
            raw_content=f"SystemEmail|{aid}|{email}|{proj_code}|{a_type}|{status}|{dt}",
            actor=OPS_ACTOR,
            filename=f"notif_{aid}.eml",
            reference_for_dup=aid,
            ingested_at=f"{dt}T16:00:00Z",
        )
        res = _upsert_assessment_and_post_ledger(
            conn,
            pulsifi_assessment_id=aid,
            candidate_identifier=email,
            assessment_type=a_type,
            event_status=status,
            event_date=dt,
            source_type="SYSTEM_EMAIL",
            actor=OPS_ACTOR,
            raw_event_id=raw_id,
            project_info=pinfo,
            campaign_key=f"{proj_code}-2026",
            timestamp_iso=f"{dt}T16:00:00Z",
        )
        aid_db = res["assessment"]["id"]
        conn.execute(
            "UPDATE assessments SET created_at = ?, sent_at = ? WHERE id = ?",
            (f"{dt}T08:30:00Z", f"{dt}T09:00:00Z", aid_db),
        )

    # 12. 1 Blocked Duplicate Event (triggers Duplicate Open Exception cleanly)
    _create_exception_if_needed(
        conn,
        category="Duplicate",
        severity="Medium",
        reference_code="P-10275",
        owner_role="OPERATIONS",
        client_id=client_ids["XYZ"],
        suggested_action=(
            "Duplicate Pulsifi System Email for P-10275 blocked by SHA-256 idempotency guard. "
            "Original Confirmed ledger entry preserved without double-counting."
        ),
        created_at="2026-09-14T09:10:00Z",
    )

    # 13. Adjustments: 1 Finance-Approved (+20) and 1 Pending Approval (+15 Maker-Checker demo)
    adj1_code = f"TX-{26000 + int(conn.execute('SELECT COALESCE(MAX(id),0)+1 FROM credit_transactions').fetchone()[0])}"
    conn.execute(
        """
        INSERT INTO credit_transactions (
            tx_code, tx_date, period_month, tx_type, client_id, project_id, pool_owner_type,
            reference_code, units, status, evidence_level, source_type, notes,
            created_by, created_at, approved_by, approved_at
        ) VALUES (?, '2026-09-10', '2026-09', 'Adjustment', ?, ?, 'CLIENT',
                  'ADJ-2026-084', 20, 'Confirmed', 5, 'MANUAL_ADJUSTMENT',
                  'Credit memo from Pulsifi support for August technical retake outage (verified email ticket #8841)',
                  ?, '2026-09-10T10:00:00Z', ?, '2026-09-10T14:30:00Z')
        """,
        (
            adj1_code,
            client_ids["ABC"],
            project_map["ABC-GRAD"]["project_id"],
            OPS_ACTOR.name,
            FINANCE_ACTOR.name,
        ),
    )

    adj2_code = f"TX-{26000 + int(conn.execute('SELECT COALESCE(MAX(id),0)+1 FROM credit_transactions').fetchone()[0])}"
    conn.execute(
        """
        INSERT INTO credit_transactions (
            tx_code, tx_date, period_month, tx_type, client_id, project_id, pool_owner_type,
            reference_code, units, status, evidence_level, source_type, notes,
            created_by, created_at
        ) VALUES (?, '2026-09-16', '2026-09', 'Adjustment', ?, ?, 'CLIENT',
                  'ADJ-2026-092', 15, 'Pending Approval', 5, 'MANUAL_ADJUSTMENT',
                  'Ops request: credit reversal for candidate browser crash on XYZ Leadership Bench (awaiting Finance Checker sign-off)',
                  ?, '2026-09-16T11:15:00Z')
        """,
        (
            adj2_code,
            client_ids["XYZ"],
            project_map["XYZ-LEAD"]["project_id"],
            OPS_ACTOR.name,
        ),
    )

    # 14. Run REAL September 2026 Monthly Reconciliation using our 4-Tier Matching Engine
    official_csv = build_official_sep_statement_csv(sep_confirmed)
    if write_sample_csv:
        SAMPLE_DATA_DIR.mkdir(parents=True, exist_ok=True)
        (SAMPLE_DATA_DIR / "pulsifi_official_statement_2026_09.csv").write_text(
            official_csv, encoding="utf-8"
        )

    run_reconciliation(
        conn,
        period_month="2026-09",
        filename="pulsifi_official_statement_2026_09.csv",
        csv_text=official_csv,
        actor=FINANCE_ACTOR,
        excel_parallel_balance=1295,
        run_at="2026-09-18T09:00:00Z",
    )

    # 15. Initial Governance Audit Log entries
    log_audit(
        conn,
        actor=ADMIN_ACTOR,
        action="CREDIT_RULES_CONFIGURED",
        entity_type="credit_rules",
        entity_id="2026-H2",
        before={"Leadership": 8},
        after={"Leadership": 10, "effective_from": "2026-07-01"},
        reason="Updated Leadership assessment unit rate for H2 2026 contract without mutating H1 history",
        timestamp="2026-07-01T08:00:00Z",
    )
    log_audit(
        conn,
        actor=FINANCE_ACTOR,
        action="ADJUSTMENT_APPROVED",
        entity_type="credit_transaction",
        entity_id=adj1_code,
        before={"status": "Pending Approval", "approved_by": None},
        after={"status": "Confirmed", "approved_by": FINANCE_ACTOR.name},
        reason="Verified Pulsifi support ticket #8841 (+20 units)",
        timestamp="2026-09-10T14:30:00Z",
    )
