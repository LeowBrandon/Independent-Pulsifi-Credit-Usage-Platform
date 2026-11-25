# Executive Commercial Summary, Discovery Gate & Rebalanced Delivery Plan

## 1. Quantitative Business Case & Target KPIs (Baseline Template)
Before committing full production build spend, populate actual firm baselines during Week 1–2 Discovery:

| Value Driver | Typical Baseline (Manual Excel) | Phase 1 MVP Target KPI | Verification Method |
| :--- | :--- | :--- | :--- |
| **Auto-Capture Rate** | 0% (100% manual logging) | **≥ 90–95%** of assessments auto-captured via L2 Reports + L3 Emails | `raw_ingested_events` source ratio |
| **Month-End Reconciliation Effort** | 2–3 staff days / month | **≤ 2 hours / month** (exception-only review) | Reconciliation run logs & Finance sign-off |
| **Unexplained Monthly Variance** | 2%–5% disputed / written off | **< 1.0%** unexplained variance (all gaps classified in Exception Queue) | `reconciliations.variance_units / usage_official` |
| **Balance Blindness / Overuse Risk** | Discovered only at month-end | **Real-time §16 tiered alerts** (Yellow 20–30%, Orange 10–20%, Red <10%) | Active alert audit & pool utilization |
| **Partner Reporting Friction** | Manual spreadsheet slicing | **1-click CSV / Printable Statement** per Partner/Client | Phase 1 Statement export logs |

---

## 2. Rough-Order-of-Magnitude (ROM) Cost Comparison

| Dimension | Option A: Microsoft-Centric (Power Platform / Dataverse) | Option B: Pure Custom (React + FastAPI + PostgreSQL + Azure) | **Option C: Recommended Hybrid (This MVP Core + M365 Connectors)** |
| :--- | :--- | :--- | :--- |
| **Phase 1 Build Effort** | 8–10 weeks (1 Power Platform dev + analyst) | 12–14 weeks (full-stack engineer + DevOps) | **10–12 weeks** (Python/Web core + thin Power Automate connectors) |
| **Estimated Build ROM** | \$18k – \$30k | \$35k – \$55k | **\$24k – \$40k** |
| **Annual Run / Licensing** | \$6k – \$14k/yr (Dataverse capacity + Power Apps/BI Pro + B2B guest friction) | \$3k – \$6k/yr (Azure Container Apps + Managed PostgreSQL) | **\$3.5k – \$7k/yr** (Azure hosting + existing M365 Outlook/Teams) |
| **Append-Only Ledger & 4-Tier Fuzzy Matching** | Difficult to unit-test & govern in Power Automate/Power Query | Native SQL triggers + unit-tested Python engine | **Native SQL triggers + unit-tested Python engine** |
| **External Partner Portal Readiness (Phase 2)** | High Entra B2B & Power Pages licensing friction | Clean multi-tenant auth ready | **Clean Phase 1 statements → seamless Phase 2 portal** |

---

## 3. Mandatory Week 1–2 Discovery Go/No-Go Phase Gate
Before advancing past Discovery, Operations and Finance must collect **3–6 months of real Pulsifi artifacts** and confirm:

1. **Identifier Audit:** Confirm whether `Assessment ID`, `Campaign / Role Name`, `Candidate Email`, and `Completion Date` appear consistently across Pulsifi system emails, downloadable reports, and official monthly billing statements.
2. **Contractual Billing Rules:** Confirm exact deduction trigger (`Sent` vs `Completed`), cancellation/expiry refund behavior, retake rules, and bulk credit expiry dates.
3. **Permitted Export Channels:** Verify with Pulsifi account management whether scheduled CSV/SFTP report exports or webhook notifications are available under the firm's commercial tier.
4. **Commercial Pool & Naming Rulebook:** Sign off on Client-funded vs Partner-funded pool rules and mandate the `[PROJECT_CODE]` naming convention inside Pulsifi campaigns (backed by the `campaign_mappings` table).

> **Go / No-Go Criterion:** Proceed to full automated ingestion if ≥ 85% of historical Pulsifi billing rows can be attributed via Campaign Naming + Downloaded Reports/Emails. Otherwise, prioritize L2 Scheduled Report Uploads + L4 Frictionless Issuance Form.

---

## 4. Rebalanced Delivery Schedule & 2-Month Excel Parallel Run

| Phase / Weeks | Milestone & Scope (Aligned MVP Boundaries) | Exit Gate |
| :--- | :--- | :--- |
| **Weeks 1–2** | **Discovery & Artifact Audit** (Pulsifi emails, exports, statements, credit rulebook, campaign naming) | **Go/No-Go Phase Gate** signed by Ops + Finance |
| **Weeks 3–5** | **Core Ledger, Schema, RBAC & Multi-Source Ingestion** (PostgreSQL triggers, PII HMAC hashing, L2 CSV + L3 Email + L4 Controlled Input) | 100% unit tests passing on append-only ledger & Maker-Checker |
| **Weeks 6–8** | **4-Tier Reconciliation Engine & Exception Queue** (*expanded from 1 week to 3 weeks*) — 100%/90%/80%/<80% matching, `reconciliation_lines`, backfill workflows | Tested against 3 months of real historical Pulsifi statements |
| **Weeks 9–10** | **Executive Dashboard, Pool Tracking, Phase 1 Statements & UAT** (No external B2B partner portal yet; CSV/PDF partner statements delivered) | UAT sign-off by Finance, Ops & Leadership |
| **Weeks 11–18 (2 Billing Cycles)** | **2-Month Parallel Run Against Legacy Excel** — Run platform alongside existing Excel workbook for 2 full month-end closes | **Cutover Gate:** Variance vs Official Statement < 1% and fully explained for 2 consecutive closes → retire Excel |
| **Phase 2 (Post-Cutover)** | External B2B Partner Portal (read-only SSO), Predictive Credit Runway Forecasting, Automated Teams Alerts, Authorized Browser Fallback (only if contractually approved) | Separate Phase 2 approval |
