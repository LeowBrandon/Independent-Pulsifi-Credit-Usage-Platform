"""Security, PII anonymization (PDPA/GDPR), RBAC, and Maker-Checker helpers."""
from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Iterable

from fastapi import Header, HTTPException

from .config import PII_HMAC_SECRET

ANONYMIZED_REF_RE = re.compile(r"^CAND-[0-9A-F]{10}$")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

VALID_ROLES = {"OPERATIONS", "FINANCE", "EXECUTIVE", "ADMIN"}

DEFAULT_ACTORS = {
    "OPERATIONS": "ops.lead@consultingfirm.com",
    "FINANCE": "finance.controller@consultingfirm.com",
    "EXECUTIVE": "managing.partner@consultingfirm.com",
    "ADMIN": "platform.admin@consultingfirm.com",
}


@dataclass(frozen=True)
class Actor:
    name: str
    role: str


def anonymize_candidate(raw_identifier: str) -> str:
    """Deterministically hash a candidate email or name to CAND-<10-hex> using HMAC-SHA256.

    Preserves cross-source matching (Email vs Downloaded Report vs Official Statement)
    while ensuring zero raw candidate PII is persisted in ledger/assessment tables.
    """
    cleaned = (raw_identifier or "").strip()
    if not cleaned:
        return "CAND-0000000000"
    upper = cleaned.upper()
    if ANONYMIZED_REF_RE.match(upper):
        return upper
    digest = hmac.new(
        PII_HMAC_SECRET,
        cleaned.lower().encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:10].upper()
    return f"CAND-{digest}"


def scrub_pii_from_text(raw_text: str) -> tuple[str, int]:
    """Replace raw email addresses inside raw payloads with their deterministic CAND hash."""
    redactions = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal redactions
        redactions += 1
        return anonymize_candidate(match.group(0))

    scrubbed = EMAIL_RE.sub(_replace, raw_text or "")
    return scrubbed, redactions


def compute_payload_hash(source_type: str, raw_content: str) -> str:
    """Compute SHA-256 idempotency hash for an ingested payload."""
    normalized = f"{source_type}::{(raw_content or '').strip()}".encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def get_actor(
    x_actor_role: str | None = Header(default="OPERATIONS", alias="X-Actor-Role"),
    x_actor_name: str | None = Header(default=None, alias="X-Actor-Name"),
) -> Actor:
    """Extract actor identity and role from request headers (Entra ID / SSO ready)."""
    role = (x_actor_role or "OPERATIONS").strip().upper()
    if role not in VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid X-Actor-Role '{role}'. Allowed: {sorted(VALID_ROLES)}",
        )
    name = (x_actor_name or "").strip() or DEFAULT_ACTORS[role]
    return Actor(name=name, role=role)


def require_roles(actor: Actor, allowed_roles: Iterable[str], action_label: str) -> None:
    """Enforce Role-Based Access Control on sensitive endpoints."""
    allowed = {r.upper() for r in allowed_roles}
    if actor.role not in allowed:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Access denied for role '{actor.role}'. "
                f"'{action_label}' requires one of: {', '.join(sorted(allowed))}."
            ),
        )


def enforce_maker_checker(maker_name: str, checker: Actor) -> None:
    """Enforce Segregation of Duties: Finance must approve, and Checker != Maker."""
    require_roles(checker, {"FINANCE"}, "Approve/Reject Credit Adjustment")
    if maker_name.strip().lower() == checker.name.strip().lower():
        raise HTTPException(
            status_code=403,
            detail=(
                "Maker-Checker violation: the user who submitted an adjustment "
                "cannot approve or reject their own request."
            ),
        )
