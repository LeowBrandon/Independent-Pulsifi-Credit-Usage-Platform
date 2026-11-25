# Architecture, Hardened Data Model & Governance Specification

## 1. Architectural Philosophy (§26 & §39)
This platform is an **Independent Credit Intelligence Layer** sitting cleanly outside Pulsifi. It does **not** claim to read a live Pulsifi balance, does **not** reverse-engineer private APIs, and does **not** perform unauthorized scraping or credential circumvention. Instead, it maintains an evidence-based, append-only internal ledger verified monthly against Pulsifi's Official Monthly Billing Statement.

---

## 2. Harmonized Balance Formulas (§11 & §12 Resolved)
All KPIs, dashboards, statements, and reconciliation bridges compute balances dynamically from `credit_transactions`:

- **Confirmed Balance** (Strong Evidence Only — L1–L3 & Finance-Approved Adjustments):
  $$\text{Confirmed Balance} = \text{Opening Balance} + \text{Confirmed Top-Ups} + \text{Approved Adjustments} + \text{Refunds/Reversals} - \text{Confirmed Usage} - \text{Expiry}$$
- **Estimated Balance** (Conservative Operational Runway View):
  $$\text{Estimated Balance} = \text{Confirmed Balance} - \text{Pending Usage}$$
- **Official Balance** (External Authoritative Anchor):
  Latest verified ending balance from Pulsifi's uploaded Official Monthly Billing Statement (`reconciliations.ending_official`).
- **Pending Approval Adjustments**: Tracked transparently in the Maker-Checker queue and **excluded** from both Confirmed and Estimated balances until approved by a distinct Finance Checker.

### Strict §16 Health Thresholds
Applied identically across the Master Pool, Client Pools, and Partner Pools:
| Remaining % | Tier | Status Label |
| :--- | :--- | :--- |
| `> 30.0%` | `GREEN` | Healthy |
| `20.0% – 30.0%` | `YELLOW` | Watch (20–30%) |
| `10.0% – 19.9%` | `ORANGE` | Low Balance (10–20%) |
| `< 10.0%` | `RED` | Critical (<10%) |

---

## 3. Re-Ranked Evidence Hierarchy (Recommendation 5)
| Level | Source Type | Reliability Role | Ledger Posting Behavior |
| :---: | :--- | :--- | :--- |
| **L1** | Official Monthly Statement / Official Invoice / Opening Balance | Authoritative | Confirms top-ups & anchors monthly reconciliation |
| **L2** | **Official Downloaded Report (CSV/Excel)** | **High (Structured)** — *ranked above emails* | Posts `Confirmed`; upgrades matching L4 `Pending` rows cleanly |
| **L3** | **Pulsifi System Email** | **High (Timeliness)** — near-real-time alert | Posts `Confirmed` (if campaign mapped); scrubs candidate PII |
| **L4** | Controlled Internal Input (<30s Form) | Medium (Work-in-Progress) | Posts `Pending` (updates Estimated Balance only) |
| **L5** | Manual Adjustment / Reversal | Controlled (Maker-Checker) | Enters `Pending Approval`; requires Finance Checker sign-off |

---

## 4. Commercial Pool Topology (Zero Double-Counting)
Every `Project` specifies an explicit `pool_owner_type` (`CLIENT` or `PARTNER`):
- **`CLIENT`-funded projects** deduct strictly from the owning `Client`'s allocated credit pool.
- **`PARTNER`-funded reseller projects** deduct strictly from the owning `Partner`'s allocated credit pool.
- **Unmapped campaigns** temporarily record usage under `pool_owner_type = 'UNASSIGNED'` in `Pending` status and raise an `Unknown Mapping` exception. Once Operations maps the Pulsifi campaign key to a project, the `Pending` entry transitions to `Superseded` and a new attributed `Confirmed` row is appended.

**Mathematical Invariant (Unit-Tested):**
$$\sum \text{Client Pools Usage} + \sum \text{Partner Pools Usage} + \text{Unassigned Usage} \equiv \text{Total Ledger Usage}$$

---

## 5. Hardened 12-Table Database Schema
Implemented in SQLite ([database.py](../backend/app/database.py)) for zero-dependency MVP execution and mirrored in production PostgreSQL 16+ DDL ([schema_postgres.sql](../backend/schema_postgres.sql)):

1. `clients` — Direct client master & allocated pools
2. `partners` — Partner master (`RESELLER_POOL` / `ADVISORY_OVERSIGHT`) & allocated pools
3. `projects` — Project attribution with explicit `pool_owner_type`
4. `campaign_mappings` — Pulsifi Campaign/Role name → internal Project mapping & naming convention support
5. `credit_batches` — Bulk contract purchases with `unit_cost`, `currency`, and `expires_at`
6. `credit_rules` — Effective-dated `(assessment_type, trigger_event, effective_from, effective_to) → credit_units`
7. `raw_ingested_events` — PII-scrubbed raw source payloads with `UNIQUE(payload_hash)` SHA-256 idempotency
8. `assessments` — Full lifecycle (`Created → Sent → Started → Completed / Cancelled / Failed / Expired`) with individual timestamps and salted `candidate_ref_hash`
9. `credit_transactions` — **Append-only** ledger with DB triggers blocking `DELETE` and blocking `UPDATE` on posted rows
10. `reconciliations` — Period-level internal vs official summary + Excel Parallel-Run balance check
11. `reconciliation_lines` — Line-level 4-tier match results (`100%`, `90%`, `80%`, `<80%`)
12. `exceptions` & `audit_logs` — Exception workflow queue + trigger-protected immutable audit trail (Before/After JSON)

---

## 6. Privacy (PDPA / GDPR) & Segregation of Duties (SoD)
- **Zero Raw Candidate PII Persisted:** Candidate emails/names are transformed at ingestion via salted `HMAC-SHA256` (`CAND-XXXXXXXXXX`). Deterministic hashing preserves cross-source fuzzy reconciliation (Tier 2 `Candidate + Date`, Tier 3 `Candidate + Type`) without storing personal identifiers.
- **Database + API Maker-Checker Enforcement:** Both the FastAPI security layer (`enforce_maker_checker`) and the SQLite/PostgreSQL trigger (`trg_ledger_maker_checker_guard`) block self-approval (`LOWER(NEW.approved_by) != LOWER(OLD.created_by)`) and require the `FINANCE` role to approve or reject adjustments.
- **Hybrid Integration Path (Option C):** In production, deploy FastAPI + PostgreSQL on Azure App Service / Container Apps, authenticate users via Microsoft Entra ID JWTs, and connect lightweight Power Automate / Microsoft Graph flows solely to forward Pulsifi notification emails to `POST /api/ingest/system-email` and post Teams alerts from `GET /api/overview`.
