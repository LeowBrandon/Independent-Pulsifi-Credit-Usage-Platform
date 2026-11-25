-- ============================================================================
-- Independent Pulsifi Credit Usage Platform — Production PostgreSQL 16+ DDL
-- Mirrors the hardened 12-table SQLite MVP schema with append-only & SoD triggers.
-- ============================================================================

CREATE TABLE clients (
    id SERIAL PRIMARY KEY,
    code VARCHAR(32) NOT NULL UNIQUE,
    name VARCHAR(160) NOT NULL UNIQUE,
    allocated_credits INTEGER NOT NULL DEFAULT 0 CHECK (allocated_credits >= 0),
    alert_threshold_pct NUMERIC(5,2) NOT NULL DEFAULT 20.00,
    contact_email VARCHAR(255),
    status VARCHAR(24) NOT NULL DEFAULT 'Active' CHECK (status IN ('Active', 'Paused', 'Archived')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE partners (
    id SERIAL PRIMARY KEY,
    code VARCHAR(32) NOT NULL UNIQUE,
    name VARCHAR(160) NOT NULL UNIQUE,
    partner_type VARCHAR(32) NOT NULL DEFAULT 'RESELLER_POOL'
        CHECK (partner_type IN ('RESELLER_POOL', 'ADVISORY_OVERSIGHT')),
    allocated_credits INTEGER NOT NULL DEFAULT 0 CHECK (allocated_credits >= 0),
    alert_threshold_pct NUMERIC(5,2) NOT NULL DEFAULT 20.00,
    contact_email VARCHAR(255),
    status VARCHAR(24) NOT NULL DEFAULT 'Active' CHECK (status IN ('Active', 'Paused', 'Archived')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE projects (
    id SERIAL PRIMARY KEY,
    code VARCHAR(48) NOT NULL UNIQUE,
    name VARCHAR(200) NOT NULL,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    partner_id INTEGER REFERENCES partners(id),
    pool_owner_type VARCHAR(16) NOT NULL DEFAULT 'CLIENT'
        CHECK (pool_owner_type IN ('CLIENT', 'PARTNER')),
    status VARCHAR(24) NOT NULL DEFAULT 'Active' CHECK (status IN ('Active', 'Completed', 'Paused')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE campaign_mappings (
    id SERIAL PRIMARY KEY,
    pulsifi_campaign_key VARCHAR(160) NOT NULL UNIQUE,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    naming_convention_hint VARCHAR(255),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by VARCHAR(160) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE credit_batches (
    id SERIAL PRIMARY KEY,
    batch_ref VARCHAR(64) NOT NULL UNIQUE,
    invoice_ref VARCHAR(64) NOT NULL,
    purchased_units INTEGER NOT NULL CHECK (purchased_units > 0),
    unit_cost NUMERIC(10,2) NOT NULL CHECK (unit_cost >= 0),
    currency VARCHAR(8) NOT NULL DEFAULT 'USD',
    purchased_at DATE NOT NULL,
    expires_at DATE NOT NULL,
    notes TEXT,
    status VARCHAR(24) NOT NULL DEFAULT 'Active' CHECK (status IN ('Active', 'Depleted', 'Expired'))
);

CREATE TABLE credit_rules (
    id SERIAL PRIMARY KEY,
    assessment_type VARCHAR(80) NOT NULL,
    trigger_event VARCHAR(24) NOT NULL CHECK (trigger_event IN ('Sent', 'Started', 'Completed')),
    credit_units INTEGER NOT NULL CHECK (credit_units >= 0),
    refund_on_cancel BOOLEAN NOT NULL DEFAULT TRUE,
    effective_from DATE NOT NULL,
    effective_to DATE,
    notes TEXT,
    created_by VARCHAR(160) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE raw_ingested_events (
    id BIGSERIAL PRIMARY KEY,
    payload_hash CHAR(64) NOT NULL UNIQUE,
    source_type VARCHAR(32) NOT NULL CHECK (source_type IN (
        'OFFICIAL_STATEMENT', 'OFFICIAL_INVOICE', 'OPENING_BALANCE',
        'DOWNLOADED_REPORT', 'SYSTEM_EMAIL', 'CONTROLLED_INPUT', 'MANUAL_ADJUSTMENT'
    )),
    evidence_level SMALLINT NOT NULL CHECK (evidence_level BETWEEN 1 AND 5),
    filename VARCHAR(255),
    scrubbed_payload TEXT NOT NULL,
    pii_redactions_count INTEGER NOT NULL DEFAULT 0,
    processing_status VARCHAR(24) NOT NULL DEFAULT 'Processed'
        CHECK (processing_status IN ('Processed', 'Duplicate', 'Exception', 'Partial')),
    ingested_by VARCHAR(160) NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE assessments (
    id BIGSERIAL PRIMARY KEY,
    pulsifi_assessment_id VARCHAR(80) NOT NULL UNIQUE,
    pulsifi_campaign_key VARCHAR(160),
    candidate_ref_hash VARCHAR(32) NOT NULL,
    client_id INTEGER REFERENCES clients(id),
    partner_id INTEGER REFERENCES partners(id),
    project_id INTEGER REFERENCES projects(id),
    assessment_type VARCHAR(80) NOT NULL,
    current_status VARCHAR(24) NOT NULL CHECK (current_status IN (
        'Created', 'Sent', 'Started', 'Completed', 'Cancelled', 'Failed', 'Expired'
    )),
    created_at TIMESTAMPTZ,
    sent_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    failed_at TIMESTAMPTZ,
    expired_at TIMESTAMPTZ,
    credit_units_applied INTEGER NOT NULL DEFAULT 0,
    credit_rule_id INTEGER REFERENCES credit_rules(id),
    evidence_level SMALLINT NOT NULL CHECK (evidence_level BETWEEN 1 AND 5),
    source_type VARCHAR(32) NOT NULL,
    raw_event_id BIGINT REFERENCES raw_ingested_events(id)
);

CREATE TABLE credit_transactions (
    id BIGSERIAL PRIMARY KEY,
    tx_code VARCHAR(48) NOT NULL UNIQUE,
    tx_date DATE NOT NULL,
    period_month CHAR(7) NOT NULL,
    tx_type VARCHAR(24) NOT NULL CHECK (tx_type IN (
        'Opening Balance', 'Top-Up', 'Usage', 'Reversal', 'Adjustment', 'Refund', 'Expiry'
    )),
    client_id INTEGER REFERENCES clients(id),
    partner_id INTEGER REFERENCES partners(id),
    project_id INTEGER REFERENCES projects(id),
    pool_owner_type VARCHAR(16) CHECK (pool_owner_type IN ('CLIENT', 'PARTNER', 'UNASSIGNED', 'MASTER')),
    assessment_id BIGINT REFERENCES assessments(id),
    reference_code VARCHAR(80) NOT NULL,
    units INTEGER NOT NULL,
    status VARCHAR(24) NOT NULL CHECK (status IN (
        'Confirmed', 'Pending', 'Pending Approval', 'Superseded', 'Cancelled', 'Rejected'
    )),
    evidence_level SMALLINT NOT NULL CHECK (evidence_level BETWEEN 1 AND 5),
    source_type VARCHAR(32) NOT NULL,
    parent_transaction_id BIGINT REFERENCES credit_transactions(id),
    credit_rule_id INTEGER REFERENCES credit_rules(id),
    raw_event_id BIGINT REFERENCES raw_ingested_events(id),
    batch_id INTEGER REFERENCES credit_batches(id),
    notes TEXT,
    created_by VARCHAR(160) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_by VARCHAR(160),
    approved_at TIMESTAMPTZ
);

CREATE TABLE reconciliations (
    id BIGSERIAL PRIMARY KEY,
    recon_code VARCHAR(48) NOT NULL UNIQUE,
    period_month CHAR(7) NOT NULL,
    official_filename VARCHAR(255) NOT NULL,
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
    match_rate_pct NUMERIC(5,2) NOT NULL,
    exact_matches INTEGER NOT NULL DEFAULT 0,
    tier2_matches INTEGER NOT NULL DEFAULT 0,
    tier3_matches INTEGER NOT NULL DEFAULT 0,
    unmatched_official INTEGER NOT NULL DEFAULT 0,
    unmatched_internal INTEGER NOT NULL DEFAULT 0,
    excel_parallel_balance INTEGER,
    status VARCHAR(24) NOT NULL CHECK (status IN ('Matched', 'Review Required', 'Finalized')),
    run_by VARCHAR(160) NOT NULL,
    run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finalized_by VARCHAR(160),
    finalized_at TIMESTAMPTZ
);

CREATE TABLE reconciliation_lines (
    id BIGSERIAL PRIMARY KEY,
    reconciliation_id BIGINT NOT NULL REFERENCES reconciliations(id) ON DELETE CASCADE,
    official_row_num INTEGER,
    official_assessment_id VARCHAR(80),
    official_candidate_hash VARCHAR(32),
    official_date DATE,
    official_type VARCHAR(80),
    official_units INTEGER NOT NULL DEFAULT 0,
    matched_transaction_id BIGINT REFERENCES credit_transactions(id),
    matched_assessment_id BIGINT REFERENCES assessments(id),
    internal_units INTEGER NOT NULL DEFAULT 0,
    match_tier VARCHAR(32) NOT NULL CHECK (match_tier IN (
        '1_EXACT_ID', '2_CANDIDATE_DATE', '3_CANDIDATE_TYPE', '4_UNMATCHED_OFFICIAL', '5_INTERNAL_ONLY'
    )),
    match_confidence SMALLINT NOT NULL CHECK (match_confidence IN (100, 90, 80, 0)),
    unit_variance INTEGER NOT NULL DEFAULT 0,
    match_status VARCHAR(24) NOT NULL CHECK (match_status IN ('Matched', 'Needs Review', 'Missing Internal', 'Internal Only')),
    notes TEXT
);

CREATE TABLE exceptions (
    id BIGSERIAL PRIMARY KEY,
    exception_code VARCHAR(48) NOT NULL UNIQUE,
    category VARCHAR(32) NOT NULL CHECK (category IN (
        'Balance Difference', 'Duplicate', 'Missing Record', 'Unknown Mapping', 'Rule Mismatch', 'Overuse Alert'
    )),
    severity VARCHAR(16) NOT NULL CHECK (severity IN ('High', 'Medium', 'Low')),
    reference_code VARCHAR(80) NOT NULL,
    owner_role VARCHAR(32) NOT NULL,
    client_id INTEGER REFERENCES clients(id),
    partner_id INTEGER REFERENCES partners(id),
    campaign_key VARCHAR(160),
    linked_event_id BIGINT REFERENCES raw_ingested_events(id),
    linked_assessment_id BIGINT REFERENCES assessments(id),
    linked_tx_id BIGINT REFERENCES credit_transactions(id),
    linked_recon_id BIGINT REFERENCES reconciliations(id),
    suggested_action TEXT NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'Open' CHECK (status IN ('Open', 'In Review', 'Resolved', 'Dismissed')),
    assigned_to VARCHAR(160),
    resolution_notes TEXT,
    resolved_by VARCHAR(160),
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE audit_logs (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor_name VARCHAR(160) NOT NULL,
    actor_role VARCHAR(32) NOT NULL,
    action VARCHAR(80) NOT NULL,
    entity_type VARCHAR(48) NOT NULL,
    entity_id VARCHAR(64) NOT NULL,
    before_json JSONB,
    after_json JSONB,
    reason TEXT
);

-- Immutability & Maker-Checker Trigger Functions
CREATE OR REPLACE FUNCTION enforce_ledger_immutability() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'credit_transactions is append-only: DELETE is prohibited';
    END IF;
    IF OLD.status IN ('Confirmed', 'Superseded', 'Cancelled', 'Rejected') THEN
        RAISE EXCEPTION 'Posted ledger rows are immutable; append a Reversal transaction instead';
    END IF;
    IF OLD.status = 'Pending' AND (
        NEW.status NOT IN ('Superseded', 'Cancelled')
        OR NEW.units <> OLD.units
        OR NEW.tx_type <> OLD.tx_type
        OR NEW.created_by <> OLD.created_by
    ) THEN
        RAISE EXCEPTION 'Pending rows may only transition to Superseded/Cancelled with unchanged amounts';
    END IF;
    IF OLD.status = 'Pending Approval' AND (
        NEW.status NOT IN ('Confirmed', 'Rejected')
        OR NEW.approved_by IS NULL
        OR LOWER(NEW.approved_by) = LOWER(OLD.created_by)
        OR NEW.units <> OLD.units
    ) THEN
        RAISE EXCEPTION 'Maker-Checker violation: distinct Finance approver required';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_credit_transactions_guard
BEFORE UPDATE OR DELETE ON credit_transactions
FOR EACH ROW EXECUTE FUNCTION enforce_ledger_immutability();

CREATE OR REPLACE FUNCTION enforce_audit_immutability() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_logs is immutable: % is prohibited', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_audit_logs_guard
BEFORE UPDATE OR DELETE ON audit_logs
FOR EACH ROW EXECUTE FUNCTION enforce_audit_immutability();
