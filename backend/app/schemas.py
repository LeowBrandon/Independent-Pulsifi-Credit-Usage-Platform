"""Pydantic v2 schemas for API requests and responses."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ControlledInputRequest(BaseModel):
    pulsifi_assessment_id: str = Field(..., min_length=2, max_length=64)
    candidate_identifier: str = Field(
        ...,
        min_length=2,
        max_length=160,
        description="Raw candidate email or reference; HMAC-SHA256 hashed before persistence.",
    )
    project_id: int
    assessment_type: str = Field(..., min_length=2, max_length=80)
    event_status: Literal[
        "Created", "Sent", "Started", "Completed", "Cancelled", "Failed", "Expired"
    ] = "Sent"
    event_date: str | None = Field(default=None, description="YYYY-MM-DD (defaults to today)")
    notes: str | None = None


class SystemEmailIngestRequest(BaseModel):
    raw_email_text: str = Field(..., min_length=10)
    subject: str | None = Field(default="Pulsifi Assessment Notification")


class AdjustmentRequest(BaseModel):
    tx_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    units: int = Field(..., description="Signed integer: positive credit, negative debit")
    project_id: int | None = None
    reference_code: str = Field(..., min_length=2, max_length=64)
    reason: str = Field(..., min_length=5, max_length=500)


class ApprovalDecisionRequest(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    reason: str = Field(..., min_length=3, max_length=500)


class ReversalRequest(BaseModel):
    reason: str = Field(..., min_length=5, max_length=500)


class TopUpRequest(BaseModel):
    tx_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    batch_ref: str = Field(..., min_length=2, max_length=64)
    invoice_ref: str = Field(..., min_length=2, max_length=64)
    units: int = Field(..., gt=0)
    unit_cost: float = Field(..., ge=0.0)
    currency: str = Field(default="USD", max_length=8)
    expires_at: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    notes: str | None = None


class CampaignMappingCreateRequest(BaseModel):
    pulsifi_campaign_key: str = Field(..., min_length=2, max_length=160)
    project_id: int
    naming_convention_hint: str | None = None


class ExceptionResolveRequest(BaseModel):
    status: Literal["Resolved", "Dismissed", "In Review"] = "Resolved"
    resolution_notes: str = Field(..., min_length=3, max_length=500)
    map_to_project_id: int | None = None


class CreditRuleCreateRequest(BaseModel):
    assessment_type: str = Field(..., min_length=2, max_length=80)
    trigger_event: Literal["Sent", "Started", "Completed"] = "Completed"
    credit_units: int = Field(..., ge=0)
    refund_on_cancel: bool = True
    effective_from: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    effective_to: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    notes: str | None = None


class FinalizeReconciliationRequest(BaseModel):
    excel_parallel_balance: int | None = None
    notes: str | None = None
