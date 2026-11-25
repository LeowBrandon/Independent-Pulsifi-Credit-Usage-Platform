# Independent Pulsifi Credit Usage Platform — Phase 1 MVP

An external, auditable **Credit Intelligence Layer** for consulting firms managing bulk Pulsifi assessment credits across Clients, Partners, and Projects — built specifically for a **no-API environment** without violating vendor terms of service.

> **Architectural Posture (§26 & §39):** This platform does **not** pretend to be a live Pulsifi balance and performs **zero unauthorized scraping or credential bypass**. It maintains an append-only, evidence-based internal ledger verified monthly against Pulsifi's Official Monthly Billing Statement.

---

## What This MVP Implements (Proposal Review Findings Addressed)

Every contradiction, blind spot, and technical gap identified in the end-to-end proposal review has been resolved directly in code and verified via automated tests:

| Proposal Review Finding | MVP Implementation |
| :--- | :--- |
| **§11 vs §12 Balance Formula Contradiction** | Unified in [`balance.py`](backend/app/services/balance.py): `Confirmed Balance = Opening + Top-Ups + Approved Adjustments + Refunds/Reversals − Confirmed Usage − Expiry`, `Estimated Balance = Confirmed Balance − Pending Usage`, plus side-by-side `Official Balance`. |
| **§16 Health Alert Mismatch** | Strictly enforced everywhere (`Green >30%`, `Yellow 20–30%`, `Orange 10–20%`, `Red <10%`). Seeded master pool sits at `25.1%` (`YELLOW / WATCH`) and Partner Alpha at `14.6%` (`ORANGE / Low Balance`). |
| **Evidence Hierarchy Re-Ranking** | **Official Downloaded Report (L2)** is ranked **above Pulsifi System Email (L3)** for structural reliability; emails serve as the near-real-time timeliness layer; Controlled Internal Input (L4) posts as `Pending` and upgrades cleanly to `Confirmed` without double counting. |
| **Cross-Tab Mock Data Mismatches** | 100% live SQL-derived metrics across all 7 screens. `P-10294` matches identically across Activity, Ledger, and Reconciliation; Open Exception counts sync live everywhere; Client + Partner + Unassigned usage equals exact Ledger usage. |
| **Attribution Gap (#1 Operational Risk)** | Dedicated `campaign_mappings` table + naming convention matcher (`[PROJECT_CODE]`). Unmapped Pulsifi campaigns auto-route to Exceptions (`Unknown Mapping`) and retroactively attribute & confirm pending ledger rows in 1 click. |
| **Undefined Client vs Partner Pool Topology** | Explicit `pool_owner_type` (`CLIENT` vs `PARTNER`) on every project eliminates double-counting; bulk `credit_batches` track unit cost & contract expiry dates. |
| **Effective-Dated Credit Rules** | `credit_rules` evaluates `(assessment_type, trigger_event, effective_from, effective_to)` at assessment date so mid-year tariff changes (e.g., H1 `8` units vs H2 `10` units for Leadership) never retroactively alter history. |
| **Missing Segregation of Duties (SoD)** | Live RBAC (`OPERATIONS`, `FINANCE`, `EXECUTIVE`, `ADMIN`) + **Maker-Checker** enforcement at both API and SQLite/PostgreSQL trigger layers (`approved_by != created_by`). |
| **Incomplete 6-Table Schema & Mutability Risk** | Expanded to **12 production tables** (`raw_ingested_events`, `credit_rules`, `campaign_mappings`, `credit_batches`, `reconciliation_lines`, `exceptions`, `audit_logs`, etc.) with DB triggers enforcing append-only `credit_transactions` and immutable `audit_logs` + [PostgreSQL DDL](backend/schema_postgres.sql). |
| **PDPA / GDPR Candidate PII Exposure** | Salted `HMAC-SHA256` hashing (`CAND-XXXXXXXXXX`) scrubs candidate emails **before** persisting `raw_ingested_events`, `assessments`, or `reconciliation_lines` while preserving cross-source fuzzy matching. |
| **Phase 1 MVP Scope Discipline** | Delivers 1-click **Phase 1 Partner & Client Statements (CSV & Printable PDF)** instead of prematurely building external B2B partner portal auth; includes **2-Month Excel Parallel-Run** tracking in Reconciliation. |
| **Commercial Case & Rebalanced Roadmap** | Documented in [docs/COMMERCIAL_AND_DELIVERY_PLAN.md](docs/COMMERCIAL_AND_DELIVERY_PLAN.md) & [docs/ARCHITECTURE_AND_GOVERNANCE.md](docs/ARCHITECTURE_AND_GOVERNANCE.md). |

---

## Quick Start (Local — Zero External Infrastructure Required)

### Prerequisites
- Python 3.12+

### 1. Install dependencies
```bash
pip install -r backend/requirements.txt
```

### 2. Run the MVP (API + Web UI served together)
```bash
PYTHONPATH=backend uvicorn app.main:app --reload --port 8000
```
Open:
- **Web Application:** `http://localhost:8000`
- **Interactive OpenAPI / Swagger Docs:** `http://localhost:8000/docs`

> On first startup, the app automatically initializes `data/pulsifi_credit_mvp.db` with the hardened 12-table schema, immutability triggers, and a 100% mathematically reconciled September 2026 demo dataset (including a real 4-tier monthly reconciliation run).

### 3. Or run with Docker Compose
```bash
docker compose up --build
```

---

## Interactive Demo Walkthrough

1. **Executive Overview:** Inspect the harmonized formula strip (`3,000 + 2,000 + 20 − 3,720 = 1,300 Confirmed − 45 Pending = 1,255 Estimated` vs `1,250 Official`), §16 `YELLOW (25.1%)` health status, stacked monthly burn chart, and active alerts.
2. **Test Multi-Source Ingestion & PII Scrubbing (`+ Capture / Ingest`):**
   - **L2 Downloaded Report CSV:** Click **"Import Built-In Sample CSV"** to watch `P-10293` upgrade from `Pending` → `Confirmed` (zero double-counting), new records confirm, candidate emails scrub to `CAND-XXXXXXXXXX`, and `PILOT-NEW-CLIENT-2026` auto-generate an `Unknown Mapping` exception.
   - **L3 System Email:** Click **"Load Sample Pulsifi Email"** and ingest to see live regex extraction + PDPA/GDPR PII redaction + SHA-256 idempotency (re-submitting blocks duplicates).
   - **L4 Controlled Input (<30s):** Capture a `Sent` assessment and watch **Estimated Balance** update while **Confirmed Balance** stays protected.
3. **Test Maker-Checker Segregation of Duties (`Credit Ledger`):**
   - Notice pending adjustment `ADJ-2026-092` (`+15 units`) submitted by Operations is locked under `Operations (Maker)`.
   - Switch **Active Role** in the top bar to **`Finance (Checker / Approver)`** to approve/reject it or post an append-only **Reversal**.
4. **Test 1-Click Attribution Backfill (`Exceptions Queue`):**
   - Click **"Map & Resolve"** on the `Unknown Mapping` exception (`UNMAPPED-SG-FINTECH-Q3`) to permanently map the Pulsifi campaign and retroactively confirm its ledger transaction.
5. **Test 4-Tier Reconciliation & Phase 1 Statements (`Reconciliation` & `Pools & Mapping`):**
   - Inspect line-level `100% Exact ID`, `90% Candidate+Date`, `80% Candidate+Type`, and `<80% Missing Internal` matches, record the 2-month Excel Parallel-Run balance, and export any Partner/Client Statement as CSV or Printable PDF.

---

## Running Automated Tests

```bash
pytest -v tests/
```

The test suite (`14` unit & end-to-end integration tests) verifies:
- Harmonized §11/§12 balance formulas & zero pool double-counting invariants
- Strict §16 alert boundaries & re-ranked evidence hierarchy (`L2 Downloaded Report > L3 System Email`)
- SQLite append-only ledger & `audit_logs` immutability triggers
- PDPA/GDPR PII scrubbing/hashing & SHA-256 idempotency deduplication
- `Pending` → `Superseded` + `Confirmed` upgrade path (no double counting)
- Effective-dated credit rule protection (H1 `8` units vs H2 `10` units)
- Maker-Checker RBAC SoD (blocking Operations approval and Finance self-approval)
- 4-tier monthly reconciliation matching, Finance finalization & Phase 1 Partner Statement CSV export

---

## Repository Structure

```text
├── backend/
│   ├── app/
│   │   ├── config.py             # Re-ranked evidence hierarchy & §16 health thresholds
│   │   ├── database.py           # 12-table SQLite schema + append-only & Maker-Checker triggers
│   │   ├── security.py           # Salted HMAC-SHA256 PII scrubbing/hashing + RBAC guards
│   │   ├── schemas.py            # Pydantic v2 API models
│   │   ├── seed.py               # 100% reconciled deterministic demo dataset
│   │   ├── main.py               # FastAPI application + REST endpoints + SPA mount
│   │   └── services/             # audit.py, balance.py, ingestion.py, ledger.py, reconciliation.py
│   ├── schema_postgres.sql       # Production PostgreSQL 16+ DDL mirror
│   └── requirements.txt
├── frontend/                     # Modular Vanilla HTML5 + CSS3 + ES Modules SPA
│   ├── index.html
│   ├── styles/                   # tokens.css, app.css
│   └── js/                       # api.js, format.js, app.js, views/*
├── sample_data/                  # Ready-to-upload CSV reports, Official Statement & System Email
├── docs/
│   ├── ARCHITECTURE_AND_GOVERNANCE.md
│   └── COMMERCIAL_AND_DELIVERY_PLAN.md
├── tests/                        # 14 unit & end-to-end API pytest tests
├── Dockerfile & docker-compose.yml
└── pulsifi_credit_prototype/     # Original static concept mockup (preserved for reference)
```
