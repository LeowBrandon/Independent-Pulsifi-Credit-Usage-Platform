"""FastAPI application for the Independent Pulsifi Credit Usage Platform (Phase 1 MVP)."""
from __future__ import annotations

import csv
import io
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .config import DEFAULT_DB_PATH, EVIDENCE_HIERARCHY, FRONTEND_DIR, SAMPLE_DATA_DIR
from .database import DatabaseManager
from .schemas import (
    AdjustmentRequest,
    ApprovalDecisionRequest,
    CampaignMappingCreateRequest,
    ControlledInputRequest,
    CreditRuleCreateRequest,
    ExceptionResolveRequest,
    FinalizeReconciliationRequest,
    ReversalRequest,
    SystemEmailIngestRequest,
    TopUpRequest,
)
from .security import Actor, DEFAULT_ACTORS, get_actor, require_roles
from .seed import seed_database
from .services.audit import log_audit, utc_now_iso
from .services.balance import compute_active_alerts, compute_balance_summary, compute_pool_breakdown
from .services.ingestion import (
    ingest_controlled_input,
    ingest_downloaded_report_csv,
    ingest_system_email,
    map_campaign_and_backfill,
)
from .services.ledger import (
    build_pool_statement,
    create_reversal,
    decide_adjustment,
    query_ledger,
    record_topup,
    render_ledger_csv,
    submit_adjustment,
)
from .services.reconciliation import (
    finalize_reconciliation,
    get_reconciliation_detail,
    run_reconciliation,
)


def create_app(db_path: Path | str | None = None, seed: bool = True) -> FastAPI:
    """Create and configure the FastAPI application (factory pattern for clean testing)."""
    db = DatabaseManager(db_path or DEFAULT_DB_PATH)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        db.init_schema()
        if seed:
            with db.session() as conn:
                seed_database(conn, write_sample_csv=(db_path is None))
        yield

    app = FastAPI(
        title="Independent Pulsifi Credit Usage Platform — MVP",
        description=(
            "External, auditable credit intelligence ledger, multi-source ingestion pipeline, "
            "Maker-Checker governance control plane, and 4-tier monthly reconciliation engine."
        ),
        version="1.0.0-mvp",
        lifespan=lifespan,
    )
    app.state.db = db

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -------------------------------------------------------------------------
    # Health & Meta
    # -------------------------------------------------------------------------
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": "1.0.0-mvp",
            "architecture_posture": "Independent Evidence-Based Ledger (No Pulsifi API Bypass)",
            "roles": DEFAULT_ACTORS,
            "evidence_hierarchy": EVIDENCE_HIERARCHY,
        }

    # -------------------------------------------------------------------------
    # Executive Overview
    # -------------------------------------------------------------------------
    @app.get("/api/overview")
    def get_overview() -> dict[str, Any]:
        with db.session() as conn:
            balance = compute_balance_summary(conn)
            pools = compute_pool_breakdown(conn)
            alerts = compute_active_alerts(conn)
            batches = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM credit_batches ORDER BY expires_at ASC"
                ).fetchall()
            ]
            pipeline_rows = conn.execute(
                """
                SELECT source_type, COUNT(*) AS cnt
                FROM assessments
                GROUP BY source_type
                """
            ).fetchall()
            pipeline_counts = {r["source_type"]: int(r["cnt"]) for r in pipeline_rows}
            recent_audit = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM audit_logs ORDER BY timestamp DESC, id DESC LIMIT 6"
                ).fetchall()
            ]
        return {
            "balance": balance,
            "pools": pools,
            "alerts": alerts,
            "batches": batches,
            "pipeline_counts": {
                "DOWNLOADED_REPORT": pipeline_counts.get("DOWNLOADED_REPORT", 0),
                "SYSTEM_EMAIL": pipeline_counts.get("SYSTEM_EMAIL", 0),
                "CONTROLLED_INPUT": pipeline_counts.get("CONTROLLED_INPUT", 0),
                "OPEN_EXCEPTIONS": balance["open_exceptions"],
            },
            "evidence_hierarchy": EVIDENCE_HIERARCHY,
            "recent_audit": recent_audit,
        }

    # -------------------------------------------------------------------------
    # Assessment Lifecycle & Multi-Source Capture
    # -------------------------------------------------------------------------
    @app.get("/api/assessments")
    def list_assessments(
        status: str | None = Query(default=None),
        source_type: str | None = Query(default=None),
        search: str | None = Query(default=None),
    ) -> dict[str, Any]:
        with db.session() as conn:
            clauses = []
            params: list[Any] = []
            if status and status != "all":
                clauses.append("a.current_status = ?")
                params.append(status)
            if source_type and source_type != "all":
                clauses.append("a.source_type = ?")
                params.append(source_type)
            if search:
                like = f"%{search.strip()}%"
                clauses.append(
                    "(a.pulsifi_assessment_id LIKE ? OR a.candidate_ref_hash LIKE ? "
                    "OR COALESCE(c.name, '') LIKE ? OR COALESCE(p.name, '') LIKE ? "
                    "OR COALESCE(pr.name, '') LIKE ? OR COALESCE(a.pulsifi_campaign_key, '') LIKE ?)"
                )
                params.extend([like, like, like, like, like, like])

            where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = conn.execute(
                f"""
                SELECT a.*,
                       c.name AS client_name,
                       p.name AS partner_name,
                       pr.name AS project_name,
                       pr.code AS project_code,
                       pr.pool_owner_type
                FROM assessments a
                LEFT JOIN clients c ON c.id = a.client_id
                LEFT JOIN partners p ON p.id = a.partner_id
                LEFT JOIN projects pr ON pr.id = a.project_id
                {where_sql}
                ORDER BY COALESCE(a.completed_at, a.started_at, a.sent_at, a.created_at) DESC, a.id DESC
                """,
                params,
            ).fetchall()

            counts = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN source_type = 'DOWNLOADED_REPORT' THEN 1 ELSE 0 END) AS downloaded_reports,
                    SUM(CASE WHEN source_type = 'SYSTEM_EMAIL' THEN 1 ELSE 0 END) AS system_emails,
                    SUM(CASE WHEN source_type = 'CONTROLLED_INPUT' THEN 1 ELSE 0 END) AS controlled_inputs,
                    COUNT(*) AS total_assessments
                FROM assessments
                """
            ).fetchone()
            open_exceptions = int(
                conn.execute(
                    "SELECT COUNT(*) FROM exceptions WHERE status IN ('Open', 'In Review')"
                ).fetchone()[0]
            )
            pii_redactions = int(
                conn.execute(
                    "SELECT COALESCE(SUM(pii_redactions_count), 0) FROM raw_ingested_events"
                ).fetchone()[0]
            )

        return {
            "items": [dict(r) for r in rows],
            "pipeline": {
                "downloaded_reports": int(counts["downloaded_reports"] or 0),
                "system_emails": int(counts["system_emails"] or 0),
                "controlled_inputs": int(counts["controlled_inputs"] or 0),
                "open_exceptions": open_exceptions,
                "total_assessments": int(counts["total_assessments"] or 0),
                "pii_redactions_total": pii_redactions,
            },
        }

    @app.get("/api/assessments/{assessment_id}")
    def get_assessment_detail(assessment_id: int) -> dict[str, Any]:
        with db.session() as conn:
            row = conn.execute(
                """
                SELECT a.*,
                       c.name AS client_name, p.name AS partner_name,
                       pr.name AS project_name, pr.code AS project_code, pr.pool_owner_type,
                       cr.credit_units AS rule_units, cr.trigger_event AS rule_trigger,
                       cr.effective_from AS rule_effective_from
                FROM assessments a
                LEFT JOIN clients c ON c.id = a.client_id
                LEFT JOIN partners p ON p.id = a.partner_id
                LEFT JOIN projects pr ON pr.id = a.project_id
                LEFT JOIN credit_rules cr ON cr.id = a.credit_rule_id
                WHERE a.id = ?
                """,
                (assessment_id,),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Assessment not found.")
            txs = [
                dict(t)
                for t in conn.execute(
                    "SELECT * FROM credit_transactions WHERE assessment_id = ? ORDER BY id ASC",
                    (assessment_id,),
                ).fetchall()
            ]
            raw_event = None
            if row["raw_event_id"]:
                re_row = conn.execute(
                    "SELECT * FROM raw_ingested_events WHERE id = ?", (row["raw_event_id"],)
                ).fetchone()
                raw_event = dict(re_row) if re_row else None

        return {"assessment": dict(row), "transactions": txs, "raw_event": raw_event}

    @app.post("/api/ingest/controlled-input")
    def api_ingest_controlled_input(
        req: ControlledInputRequest,
        actor: Actor = Depends(get_actor),
    ) -> dict[str, Any]:
        with db.session() as conn:
            return ingest_controlled_input(conn, req, actor)

    @app.post("/api/ingest/system-email")
    def api_ingest_system_email(
        req: SystemEmailIngestRequest,
        actor: Actor = Depends(get_actor),
    ) -> dict[str, Any]:
        with db.session() as conn:
            return ingest_system_email(conn, req, actor)

    @app.post("/api/ingest/downloaded-report")
    async def api_ingest_downloaded_report(
        file: UploadFile = File(...),
        actor: Actor = Depends(get_actor),
    ) -> dict[str, Any]:
        raw_bytes = await file.read()
        try:
            csv_text = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="Uploaded CSV must be UTF-8 encoded.") from exc
        with db.session() as conn:
            return ingest_downloaded_report_csv(
                conn, filename=file.filename or "pulsifi_report.csv", csv_text=csv_text, actor=actor
            )

    # -------------------------------------------------------------------------
    # Append-Only Credit Ledger & Maker-Checker Approvals
    # -------------------------------------------------------------------------
    @app.get("/api/ledger")
    def api_list_ledger(
        tx_type: str | None = Query(default=None),
        status: str | None = Query(default=None),
        period_month: str | None = Query(default=None),
        search: str | None = Query(default=None),
        include_superseded: bool = Query(default=False),
    ) -> dict[str, Any]:
        with db.session() as conn:
            items = query_ledger(
                conn,
                tx_type=tx_type,
                status=status,
                period_month=period_month,
                search=search,
                include_superseded=include_superseded,
            )
            pending_approvals = query_ledger(conn, status="Pending Approval")
            balance = compute_balance_summary(conn)
            periods = [
                r["period_month"]
                for r in conn.execute(
                    "SELECT DISTINCT period_month FROM credit_transactions ORDER BY period_month DESC"
                ).fetchall()
            ]
        return {
            "items": items,
            "pending_approvals": pending_approvals,
            "balance": balance,
            "periods": periods,
        }

    @app.get("/api/ledger/export.csv")
    def api_export_ledger_csv(
        tx_type: str | None = Query(default=None),
        status: str | None = Query(default=None),
        period_month: str | None = Query(default=None),
        search: str | None = Query(default=None),
    ) -> PlainTextResponse:
        with db.session() as conn:
            rows = query_ledger(
                conn, tx_type=tx_type, status=status, period_month=period_month, search=search
            )
        csv_content = render_ledger_csv(rows)
        return PlainTextResponse(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="pulsifi-credit-ledger.csv"'},
        )

    @app.post("/api/ledger/adjustments")
    def api_submit_adjustment(
        req: AdjustmentRequest,
        actor: Actor = Depends(get_actor),
    ) -> dict[str, Any]:
        with db.session() as conn:
            return submit_adjustment(conn, req, actor)

    @app.post("/api/ledger/adjustments/{tx_id}/decision")
    def api_decide_adjustment(
        tx_id: int,
        req: ApprovalDecisionRequest,
        actor: Actor = Depends(get_actor),
    ) -> dict[str, Any]:
        with db.session() as conn:
            return decide_adjustment(conn, tx_id, req, actor)

    @app.post("/api/ledger/{tx_id}/reverse")
    def api_reverse_transaction(
        tx_id: int,
        req: ReversalRequest,
        actor: Actor = Depends(get_actor),
    ) -> dict[str, Any]:
        with db.session() as conn:
            return create_reversal(conn, tx_id, req.reason, actor)

    @app.post("/api/ledger/topups")
    def api_record_topup(
        req: TopUpRequest,
        actor: Actor = Depends(get_actor),
    ) -> dict[str, Any]:
        with db.session() as conn:
            return record_topup(conn, req, actor)

    # -------------------------------------------------------------------------
    # Clients, Partners, Phase 1 Statements & Campaign Mappings
    # -------------------------------------------------------------------------
    @app.get("/api/pools")
    def api_get_pools() -> dict[str, Any]:
        with db.session() as conn:
            pools = compute_pool_breakdown(conn)
            projects = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT p.*, c.name AS client_name, c.code AS client_code,
                           pa.name AS partner_name, pa.code AS partner_code
                    FROM projects p
                    JOIN clients c ON c.id = p.client_id
                    LEFT JOIN partners pa ON pa.id = p.partner_id
                    ORDER BY p.pool_owner_type ASC, p.name ASC
                    """
                ).fetchall()
            ]
            mappings = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT cm.*, p.code AS project_code, p.name AS project_name,
                           p.pool_owner_type, c.name AS client_name, pa.name AS partner_name
                    FROM campaign_mappings cm
                    JOIN projects p ON p.id = cm.project_id
                    JOIN clients c ON c.id = p.client_id
                    LEFT JOIN partners pa ON pa.id = p.partner_id
                    ORDER BY cm.created_at DESC, cm.id DESC
                    """
                ).fetchall()
            ]
        return {**pools, "projects": projects, "campaign_mappings": mappings}

    @app.post("/api/campaign-mappings")
    def api_create_campaign_mapping(
        req: CampaignMappingCreateRequest,
        actor: Actor = Depends(get_actor),
    ) -> dict[str, Any]:
        with db.session() as conn:
            return map_campaign_and_backfill(conn, req, actor)

    @app.get("/api/statements/{pool_type}/{pool_id}")
    def api_get_statement(
        pool_type: str,
        pool_id: int,
        period_month: str | None = Query(default=None),
    ) -> dict[str, Any]:
        with db.session() as conn:
            return build_pool_statement(conn, pool_type, pool_id, period_month)

    @app.get("/api/statements/{pool_type}/{pool_id}/export.csv")
    def api_export_statement_csv(
        pool_type: str,
        pool_id: int,
        period_month: str | None = Query(default=None),
    ) -> PlainTextResponse:
        with db.session() as conn:
            stmt = build_pool_statement(conn, pool_type, pool_id, period_month)

        buf = io.StringIO()
        writer = csv.writer(buf)
        owner_name = stmt["owner"]["name"]
        writer.writerow(["Independent Pulsifi Credit Usage Statement", owner_name])
        writer.writerow(["Pool Type", stmt["pool_type"], "Period", stmt["period_filter"]])
        writer.writerow(["Allocated", stmt["summary"]["allocated_credits"], "Confirmed Used", stmt["summary"]["confirmed_used"]])
        writer.writerow(["Pending Used", stmt["summary"]["pending_used"], "Estimated Remaining", stmt["summary"]["estimated_remaining"]])
        writer.writerow([])
        writer.writerow(["Date", "Tx Code", "Type", "Project", "Reference", "Assessment Type", "Candidate Ref", "Units", "Status", "Evidence Level", "Source"])
        for t in stmt["transactions"]:
            writer.writerow(
                [
                    t["tx_date"],
                    t["tx_code"],
                    t["tx_type"],
                    t.get("project_name") or "",
                    t["reference_code"],
                    t.get("assessment_type") or "",
                    t.get("candidate_ref_hash") or "",
                    t["units"],
                    t["status"],
                    f"L{t['evidence_level']}",
                    t["source_type"],
                ]
            )
        safe_code = stmt["owner"]["code"].lower()
        return PlainTextResponse(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="credit-statement-{safe_code}.csv"'
            },
        )

    # -------------------------------------------------------------------------
    # Exceptions Queue
    # -------------------------------------------------------------------------
    @app.get("/api/exceptions")
    def api_list_exceptions(
        category: str | None = Query(default=None),
        status: str | None = Query(default=None),
    ) -> dict[str, Any]:
        with db.session() as conn:
            clauses = []
            params: list[Any] = []
            if category and category != "all":
                clauses.append("e.category = ?")
                params.append(category)
            if status and status != "all":
                clauses.append("e.status = ?")
                params.append(status)
            where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = conn.execute(
                f"""
                SELECT e.*, c.name AS client_name, p.name AS partner_name
                FROM exceptions e
                LEFT JOIN clients c ON c.id = e.client_id
                LEFT JOIN partners p ON p.id = e.partner_id
                {where_sql}
                ORDER BY
                    CASE e.status WHEN 'Open' THEN 1 WHEN 'In Review' THEN 2 ELSE 3 END,
                    CASE e.severity WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END,
                    e.created_at DESC
                """,
                params,
            ).fetchall()
            counts = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN status IN ('Open', 'In Review') THEN 1 ELSE 0 END) AS open_count,
                    SUM(CASE WHEN status = 'Resolved' THEN 1 ELSE 0 END) AS resolved_count,
                    SUM(CASE WHEN severity = 'High' AND status IN ('Open', 'In Review') THEN 1 ELSE 0 END) AS high_open
                FROM exceptions
                """
            ).fetchone()
        return {
            "items": [dict(r) for r in rows],
            "summary": {
                "open_count": int(counts["open_count"] or 0),
                "resolved_count": int(counts["resolved_count"] or 0),
                "high_open": int(counts["high_open"] or 0),
            },
        }

    @app.post("/api/exceptions/{exception_id}/resolve")
    def api_resolve_exception(
        exception_id: int,
        req: ExceptionResolveRequest,
        actor: Actor = Depends(get_actor),
    ) -> dict[str, Any]:
        require_roles(actor, {"OPERATIONS", "FINANCE", "ADMIN"}, "Resolve Exception")
        with db.session() as conn:
            exc = conn.execute("SELECT * FROM exceptions WHERE id = ?", (exception_id,)).fetchone()
            if not exc:
                raise HTTPException(status_code=404, detail="Exception not found.")

            # If Unknown Mapping and project_id provided, map & backfill atomically!
            backfill_info = None
            if exc["category"] == "Unknown Mapping" and req.map_to_project_id and exc["campaign_key"]:
                backfill_info = map_campaign_and_backfill(
                    conn,
                    CampaignMappingCreateRequest(
                        pulsifi_campaign_key=exc["campaign_key"],
                        project_id=req.map_to_project_id,
                        naming_convention_hint=f"Mapped via exception {exc['exception_code']}",
                    ),
                    actor,
                )

            now = utc_now_iso()
            before = {"status": exc["status"], "resolution_notes": exc["resolution_notes"]}
            conn.execute(
                """
                UPDATE exceptions
                SET status = ?,
                    resolution_notes = ?,
                    resolved_by = CASE WHEN ? IN ('Resolved', 'Dismissed') THEN ? ELSE resolved_by END,
                    resolved_at = CASE WHEN ? IN ('Resolved', 'Dismissed') THEN ? ELSE resolved_at END
                WHERE id = ?
                """,
                (
                    req.status,
                    req.resolution_notes.strip(),
                    req.status,
                    actor.name,
                    req.status,
                    now,
                    exception_id,
                ),
            )
            updated = dict(conn.execute("SELECT * FROM exceptions WHERE id = ?", (exception_id,)).fetchone())
            log_audit(
                conn,
                actor=actor,
                action=f"EXCEPTION_{req.status.upper().replace(' ', '_')}",
                entity_type="exception",
                entity_id=exc["exception_code"],
                before=before,
                after={"status": updated["status"], "resolution_notes": updated["resolution_notes"]},
                reason=req.resolution_notes.strip(),
                timestamp=now,
            )
        return {"exception": updated, "backfill": backfill_info}

    # -------------------------------------------------------------------------
    # Monthly Reconciliation Engine
    # -------------------------------------------------------------------------
    @app.get("/api/reconciliations")
    def api_list_reconciliations() -> dict[str, Any]:
        with db.session() as conn:
            runs = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM reconciliations ORDER BY period_month DESC, id DESC"
                ).fetchall()
            ]
            latest_detail = get_reconciliation_detail(conn, runs[0]["id"]) if runs else None
        return {"runs": runs, "latest": latest_detail}

    @app.get("/api/reconciliations/{recon_id}")
    def api_get_reconciliation(recon_id: int) -> dict[str, Any]:
        with db.session() as conn:
            return get_reconciliation_detail(conn, recon_id)

    @app.post("/api/reconciliations/run")
    async def api_run_reconciliation(
        period_month: str = Form(...),
        excel_parallel_balance: int | None = Form(default=None),
        file: UploadFile = File(...),
        actor: Actor = Depends(get_actor),
    ) -> dict[str, Any]:
        raw_bytes = await file.read()
        try:
            csv_text = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="Statement CSV must be UTF-8 encoded.") from exc
        with db.session() as conn:
            return run_reconciliation(
                conn,
                period_month=period_month.strip(),
                filename=file.filename or f"official_statement_{period_month}.csv",
                csv_text=csv_text,
                actor=actor,
                excel_parallel_balance=excel_parallel_balance,
            )

    @app.post("/api/reconciliations/{recon_id}/finalize")
    def api_finalize_reconciliation(
        recon_id: int,
        req: FinalizeReconciliationRequest,
        actor: Actor = Depends(get_actor),
    ) -> dict[str, Any]:
        with db.session() as conn:
            return finalize_reconciliation(
                conn,
                recon_id=recon_id,
                actor=actor,
                excel_parallel_balance=req.excel_parallel_balance,
                notes=req.notes,
            )

    # -------------------------------------------------------------------------
    # Governance: Effective-Dated Credit Rules, Credit Batches, Raw Events, Audit Trail
    # -------------------------------------------------------------------------
    @app.get("/api/governance")
    def api_get_governance() -> dict[str, Any]:
        with db.session() as conn:
            rules = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM credit_rules ORDER BY assessment_type ASC, effective_from DESC"
                ).fetchall()
            ]
            batches = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM credit_batches ORDER BY expires_at ASC"
                ).fetchall()
            ]
            raw_events = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT id, payload_hash, source_type, evidence_level, filename,
                           pii_redactions_count, processing_status, ingested_by, ingested_at,
                           SUBSTR(scrubbed_payload, 1, 220) AS payload_preview
                    FROM raw_ingested_events
                    ORDER BY ingested_at DESC, id DESC
                    LIMIT 30
                    """
                ).fetchall()
            ]
            audit_logs = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM audit_logs ORDER BY timestamp DESC, id DESC LIMIT 100"
                ).fetchall()
            ]
        return {
            "credit_rules": rules,
            "credit_batches": batches,
            "raw_events": raw_events,
            "audit_logs": audit_logs,
            "evidence_hierarchy": EVIDENCE_HIERARCHY,
        }

    @app.post("/api/governance/credit-rules")
    def api_create_credit_rule(
        req: CreditRuleCreateRequest,
        actor: Actor = Depends(get_actor),
    ) -> dict[str, Any]:
        require_roles(actor, {"ADMIN", "FINANCE"}, "Configure Effective-Dated Credit Rule")
        now = utc_now_iso()
        with db.session() as conn:
            cur = conn.execute(
                """
                INSERT INTO credit_rules (
                    assessment_type, trigger_event, credit_units, refund_on_cancel,
                    effective_from, effective_to, notes, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    req.assessment_type.strip(),
                    req.trigger_event,
                    req.credit_units,
                    1 if req.refund_on_cancel else 0,
                    req.effective_from,
                    req.effective_to,
                    req.notes,
                    actor.name,
                    now,
                ),
            )
            rule_id = int(cur.lastrowid)
            created = dict(conn.execute("SELECT * FROM credit_rules WHERE id = ?", (rule_id,)).fetchone())
            log_audit(
                conn,
                actor=actor,
                action="CREDIT_RULE_CREATED",
                entity_type="credit_rule",
                entity_id=rule_id,
                before=None,
                after=created,
                reason=req.notes or f"Configured {req.assessment_type} rule from {req.effective_from}",
                timestamp=now,
            )
        return created

    # -------------------------------------------------------------------------
    # Sample Data Downloads & Demo Reset
    # -------------------------------------------------------------------------
    @app.get("/api/samples/{sample_name}")
    def api_get_sample(sample_name: str):
        allowed = {
            "downloaded-report": ("pulsifi_downloaded_report_sample.csv", "text/csv"),
            "official-statement": ("pulsifi_official_statement_2026_09.csv", "text/csv"),
            "system-email": ("pulsifi_system_email_sample.txt", "text/plain"),
        }
        if sample_name not in allowed:
            raise HTTPException(status_code=404, detail="Unknown sample artifact.")
        fname, media_type = allowed[sample_name]
        fpath = SAMPLE_DATA_DIR / fname
        if not fpath.exists():
            raise HTTPException(status_code=404, detail="Sample file not found on disk.")
        return PlainTextResponse(
            content=fpath.read_text(encoding="utf-8"),
            media_type=media_type,
            headers={"Content-Disposition": f'inline; filename="{fname}"'},
        )

    @app.post("/api/demo/reset")
    def api_demo_reset(actor: Actor = Depends(get_actor)) -> dict[str, Any]:
        require_roles(actor, {"ADMIN", "FINANCE", "OPERATIONS"}, "Reset Demo Database")
        if db.db_path.exists():
            db.db_path.unlink()
        db.init_schema()
        with db.session() as conn:
            seed_database(conn, write_sample_csv=False)
        return {"status": "reset", "message": "Demo dataset cleanly re-seeded."}

    # -------------------------------------------------------------------------
    # Frontend Static Assets & SPA Shell
    # -------------------------------------------------------------------------
    if FRONTEND_DIR.exists():
        styles_dir = FRONTEND_DIR / "styles"
        js_dir = FRONTEND_DIR / "js"
        if styles_dir.exists():
            app.mount("/styles", StaticFiles(directory=str(styles_dir)), name="styles")
        if js_dir.exists():
            app.mount("/js", StaticFiles(directory=str(js_dir)), name="js")

        @app.get("/", include_in_schema=False)
        def serve_index():
            return FileResponse(str(FRONTEND_DIR / "index.html"))

    return app


app = create_app()
