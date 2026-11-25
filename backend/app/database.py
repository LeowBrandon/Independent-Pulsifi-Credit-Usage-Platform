"""SQLite database initialization, hardened 12-table schema, and immutability triggers."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import DEFAULT_DB_PATH

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    allocated_credits INTEGER NOT NULL DEFAULT 0 CHECK (allocated_credits >= 0),
    alert_threshold_pct REAL NOT NULL DEFAULT 20.0,
    contact_email TEXT,
    status TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Active', 'Paused', 'Archived')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS partners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    partner_type TEXT NOT NULL DEFAULT 'RESELLER_POOL'
        CHECK (partner_type IN ('RESELLER_POOL', 'ADVISORY_OVERSIGHT')),
    allocated_credits INTEGER NOT NULL DEFAULT 0 CHECK (allocated_credits >= 0),
    alert_threshold_pct REAL NOT NULL DEFAULT 20.0,
    contact_email TEXT,
    status TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Active', 'Paused', 'Archived')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    partner_id INTEGER REFERENCES partners(id),
    pool_owner_type TEXT NOT NULL DEFAULT 'CLIENT'
        CHECK (pool_owner_type IN ('CLIENT', 'PARTNER')),
    status TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Active', 'Completed', 'Paused')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS campaign_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pulsifi_campaign_key TEXT NOT NULL UNIQUE,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    naming_convention_hint TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS credit_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_ref TEXT NOT NULL UNIQUE,
    invoice_ref TEXT NOT NULL,
    purchased_units INTEGER NOT NULL CHECK (purchased_units > 0),
    unit_cost REAL NOT NULL CHECK (unit_cost >= 0),
    currency TEXT NOT NULL DEFAULT 'USD',
    purchased_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Active', 'Depleted', 'Expired'))
);

CREATE TABLE IF NOT EXISTS credit_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_type TEXT NOT NULL,
    trigger_event TEXT NOT NULL CHECK (trigger_event IN ('Sent', 'Started', 'Completed')),
    credit_units INTEGER NOT NULL CHECK (credit_units >= 0),
    refund_on_cancel INTEGER NOT NULL DEFAULT 1,
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    notes TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_ingested_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payload_hash TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL CHECK (source_type IN (
        'OFFICIAL_STATEMENT', 'OFFICIAL_INVOICE', 'OPENING_BALANCE',
        'DOWNLOADED_REPORT', 'SYSTEM_EMAIL', 'CONTROLLED_INPUT', 'MANUAL_ADJUSTMENT'
    )),
    evidence_level INTEGER NOT NULL CHECK (evidence_level BETWEEN 1 AND 5),
    filename TEXT,
    scrubbed_payload TEXT NOT NULL,
    pii_redactions_count INTEGER NOT NULL DEFAULT 0,
    processing_status TEXT NOT NULL DEFAULT 'Processed'
        CHECK (processing_status IN ('Processed', 'Duplicate', 'Exception', 'Partial')),
    ingested_by TEXT NOT NULL,
    ingested_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pulsifi_assessment_id TEXT NOT NULL UNIQUE,
    pulsifi_campaign_key TEXT,
    candidate_ref_hash TEXT NOT NULL,
    client_id INTEGER REFERENCES clients(id),
    partner_id INTEGER REFERENCES partners(id),
    project_id INTEGER REFERENCES projects(id),
    assessment_type TEXT NOT NULL,
    current_status TEXT NOT NULL CHECK (current_status IN (
        'Created', 'Sent', 'Started', 'Completed', 'Cancelled', 'Failed', 'Expired'
    )),
    created_at TEXT,
    sent_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    cancelled_at TEXT,
    failed_at TEXT,
    expired_at TEXT,
    credit_units_applied INTEGER NOT NULL DEFAULT 0,
    credit_rule_id INTEGER REFERENCES credit_rules(id),
    evidence_level INTEGER NOT NULL CHECK (evidence_level BETWEEN 1 AND 5),
    source_type TEXT NOT NULL,
    raw_event_id INTEGER REFERENCES raw_ingested_events(id)
);

CREATE TABLE IF NOT EXISTS credit_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_code TEXT NOT NULL UNIQUE,
    tx_date TEXT NOT NULL,
    period_month TEXT NOT NULL,
    tx_type TEXT NOT NULL CHECK (tx_type IN (
        'Opening Balance', 'Top-Up', 'Usage', 'Reversal', 'Adjustment', 'Refund', 'Expiry'
    )),
    client_id INTEGER REFERENCES clients(id),
    partner_id INTEGER REFERENCES partners(id),
    project_id INTEGER REFERENCES projects(id),
    pool_owner_type TEXT CHECK (pool_owner_type IN ('CLIENT', 'PARTNER', 'UNASSIGNED', 'MASTER')),
    assessment_id INTEGER REFERENCES assessments(id),
    reference_code TEXT NOT NULL,
    units INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'Confirmed', 'Pending', 'Pending Approval', 'Superseded', 'Cancelled', 'Rejected'
    )),
    evidence_level INTEGER NOT NULL CHECK (evidence_level BETWEEN 1 AND 5),
    source_type TEXT NOT NULL,
    parent_transaction_id INTEGER REFERENCES credit_transactions(id),
    credit_rule_id INTEGER REFERENCES credit_rules(id),
    raw_event_id INTEGER REFERENCES raw_ingested_events(id),
    batch_id INTEGER REFERENCES credit_batches(id),
    notes TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    approved_by TEXT,
    approved_at TEXT
);

CREATE TABLE IF NOT EXISTS reconciliations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recon_code TEXT NOT NULL UNIQUE,
    period_month TEXT NOT NULL,
    official_filename TEXT NOT NULL,
    opening_internal INTEGER NOT NULL,
    opening_official INTEGER NOT NULL,
    topups_internal INTEGER NOT NULL,
    topups_official INTEGER NOT NULL,
    usage_internal INTEGER NOT NULL,
    usage_official INTEGER NOT NULL,
    adjustments_internal INTEGER NOT NULL,
    adjustments_official INTEGER NOT NULL,
    ending_internal_confirmed INTEGER NOT NULL,
    ending_internal_estimated INTEGER NOT NULL,
    ending_official INTEGER NOT NULL,
    variance_units INTEGER NOT NULL,
    match_rate_pct REAL NOT NULL,
    exact_matches INTEGER NOT NULL DEFAULT 0,
    tier2_matches INTEGER NOT NULL DEFAULT 0,
    tier3_matches INTEGER NOT NULL DEFAULT 0,
    unmatched_official INTEGER NOT NULL DEFAULT 0,
    unmatched_internal INTEGER NOT NULL DEFAULT 0,
    excel_parallel_balance INTEGER,
    status TEXT NOT NULL CHECK (status IN ('Matched', 'Review Required', 'Finalized')),
    run_by TEXT NOT NULL,
    run_at TEXT NOT NULL,
    finalized_by TEXT,
    finalized_at TEXT
);

CREATE TABLE IF NOT EXISTS reconciliation_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reconciliation_id INTEGER NOT NULL REFERENCES reconciliations(id) ON DELETE CASCADE,
    official_row_num INTEGER,
    official_assessment_id TEXT,
    official_candidate_hash TEXT,
    official_date TEXT,
    official_type TEXT,
    official_units INTEGER NOT NULL DEFAULT 0,
    matched_transaction_id INTEGER REFERENCES credit_transactions(id),
    matched_assessment_id INTEGER REFERENCES assessments(id),
    internal_units INTEGER NOT NULL DEFAULT 0,
    match_tier TEXT NOT NULL CHECK (match_tier IN (
        '1_EXACT_ID', '2_CANDIDATE_DATE', '3_CANDIDATE_TYPE', '4_UNMATCHED_OFFICIAL', '5_INTERNAL_ONLY'
    )),
    match_confidence INTEGER NOT NULL CHECK (match_confidence IN (100, 90, 80, 0)),
    unit_variance INTEGER NOT NULL DEFAULT 0,
    match_status TEXT NOT NULL CHECK (match_status IN ('Matched', 'Needs Review', 'Missing Internal', 'Internal Only')),
    notes TEXT
);

CREATE TABLE IF NOT EXISTS exceptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exception_code TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL CHECK (category IN (
        'Balance Difference', 'Duplicate', 'Missing Record', 'Unknown Mapping', 'Rule Mismatch', 'Overuse Alert'
    )),
    severity TEXT NOT NULL CHECK (severity IN ('High', 'Medium', 'Low')),
    reference_code TEXT NOT NULL,
    owner_role TEXT NOT NULL,
    client_id INTEGER REFERENCES clients(id),
    partner_id INTEGER REFERENCES partners(id),
    campaign_key TEXT,
    linked_event_id INTEGER REFERENCES raw_ingested_events(id),
    linked_assessment_id INTEGER REFERENCES assessments(id),
    linked_tx_id INTEGER REFERENCES credit_transactions(id),
    linked_recon_id INTEGER REFERENCES reconciliations(id),
    suggested_action TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Open' CHECK (status IN ('Open', 'In Review', 'Resolved', 'Dismissed')),
    assigned_to TEXT,
    resolution_notes TEXT,
    resolved_by TEXT,
    resolved_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    actor_name TEXT NOT NULL,
    actor_role TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    reason TEXT
);

-- Indexes for query performance
CREATE INDEX IF NOT EXISTS idx_tx_period ON credit_transactions(period_month, status);
CREATE INDEX IF NOT EXISTS idx_tx_client ON credit_transactions(client_id, pool_owner_type);
CREATE INDEX IF NOT EXISTS idx_tx_partner ON credit_transactions(partner_id, pool_owner_type);
CREATE INDEX IF NOT EXISTS idx_tx_assessment ON credit_transactions(assessment_id);
CREATE INDEX IF NOT EXISTS idx_assessments_status ON assessments(current_status);
CREATE INDEX IF NOT EXISTS idx_assessments_candidate ON assessments(candidate_ref_hash);
CREATE INDEX IF NOT EXISTS idx_exceptions_status ON exceptions(status, category);
CREATE INDEX IF NOT EXISTS idx_recon_lines_recon ON reconciliation_lines(reconciliation_id);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_logs(timestamp DESC);

-- =============================================================================
-- APPEND-ONLY FINANCIAL LEDGER & IMMUTABLE AUDIT LOG TRIGGERS
-- =============================================================================

CREATE TRIGGER IF NOT EXISTS trg_ledger_no_delete
BEFORE DELETE ON credit_transactions
BEGIN
    SELECT RAISE(ABORT, 'credit_transactions is append-only: DELETE is prohibited');
END;

CREATE TRIGGER IF NOT EXISTS trg_ledger_immutable_posted
BEFORE UPDATE ON credit_transactions
WHEN OLD.status IN ('Confirmed', 'Superseded', 'Cancelled', 'Rejected')
BEGIN
    SELECT RAISE(ABORT, 'Posted ledger rows are immutable; append a Reversal transaction instead');
END;

CREATE TRIGGER IF NOT EXISTS trg_ledger_pending_guard
BEFORE UPDATE ON credit_transactions
WHEN OLD.status = 'Pending' AND (
    NEW.status NOT IN ('Superseded', 'Cancelled')
    OR NEW.units != OLD.units
    OR NEW.tx_type != OLD.tx_type
    OR NEW.tx_date != OLD.tx_date
    OR NEW.reference_code != OLD.reference_code
    OR NEW.created_by != OLD.created_by
)
BEGIN
    SELECT RAISE(ABORT, 'Pending ledger rows may only transition to Superseded or Cancelled without mutating amounts');
END;

CREATE TRIGGER IF NOT EXISTS trg_ledger_maker_checker_guard
BEFORE UPDATE ON credit_transactions
WHEN OLD.status = 'Pending Approval' AND (
    NEW.status NOT IN ('Confirmed', 'Rejected')
    OR NEW.approved_by IS NULL
    OR LOWER(NEW.approved_by) = LOWER(OLD.created_by)
    OR NEW.units != OLD.units
    OR NEW.tx_type != OLD.tx_type
    OR NEW.tx_date != OLD.tx_date
    OR NEW.created_by != OLD.created_by
)
BEGIN
    SELECT RAISE(ABORT, 'Maker-Checker enforcement: Pending Approval rows require a distinct Finance approver and unchanged amounts');
END;

CREATE TRIGGER IF NOT EXISTS trg_audit_no_update
BEFORE UPDATE ON audit_logs
BEGIN
    SELECT RAISE(ABORT, 'audit_logs is immutable: UPDATE is prohibited');
END;

CREATE TRIGGER IF NOT EXISTS trg_audit_no_delete
BEFORE DELETE ON audit_logs
BEGIN
    SELECT RAISE(ABORT, 'audit_logs is immutable: DELETE is prohibited');
END;
"""


class DatabaseManager:
    """Thin SQLite database manager with foreign keys and immutability enforcement."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.session() as conn:
            conn.executescript(SCHEMA_SQL)
