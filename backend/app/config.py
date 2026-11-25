"""Centralized configuration, constants, evidence hierarchy, and §16 alert thresholds."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
FRONTEND_DIR = BASE_DIR / "frontend"
SAMPLE_DATA_DIR = BASE_DIR / "sample_data"

DEFAULT_DB_PATH = Path(
    os.environ.get("PULSIFI_DB_PATH", str(DATA_DIR / "pulsifi_credit_mvp.db"))
)

# Salted HMAC key for deterministic, PII-free CandidateReference hashing (PDPA/GDPR).
# In production, load from Azure Key Vault / environment secret manager.
PII_HMAC_SECRET = os.environ.get(
    "PULSIFI_PII_HMAC_SECRET",
    "pulsifi-mvp-dev-salt-change-in-production-v1",
).encode("utf-8")

# Re-ranked Evidence Hierarchy (Recommendation 5 / §4.A.3):
# Official Downloaded Report (Level 2) is ranked ABOVE Pulsifi System Email (Level 3)
# because structured CSV/Excel exports are authoritative and less brittle than HTML email scraping,
# while system emails serve as the near-real-time timeliness layer.
EVIDENCE_HIERARCHY: dict[str, dict[str, object]] = {
    "OFFICIAL_STATEMENT": {
        "level": 1,
        "label": "Official Monthly Statement",
        "reliability": "Authoritative",
        "auto_confirm": True,
    },
    "OFFICIAL_INVOICE": {
        "level": 1,
        "label": "Official Invoice",
        "reliability": "Authoritative",
        "auto_confirm": True,
    },
    "OPENING_BALANCE": {
        "level": 1,
        "label": "Verified Opening Balance",
        "reliability": "Authoritative",
        "auto_confirm": True,
    },
    "DOWNLOADED_REPORT": {
        "level": 2,
        "label": "Official Downloaded Report",
        "reliability": "High (Structured)",
        "auto_confirm": True,
    },
    "SYSTEM_EMAIL": {
        "level": 3,
        "label": "Pulsifi System Email",
        "reliability": "High (Timeliness)",
        "auto_confirm": True,
    },
    "CONTROLLED_INPUT": {
        "level": 4,
        "label": "Controlled Internal Input",
        "reliability": "Medium (Pending)",
        "auto_confirm": False,
    },
    "MANUAL_ADJUSTMENT": {
        "level": 5,
        "label": "Manual Adjustment (Maker-Checker)",
        "reliability": "Controlled (Finance Approved)",
        "auto_confirm": False,
    },
}

VALID_LIFECYCLE_STATUSES = (
    "Created",
    "Sent",
    "Started",
    "Completed",
    "Cancelled",
    "Failed",
    "Expired",
)

# §16 Unified Low-Balance Health Thresholds (strictly enforced across all views)
def evaluate_health_tier(remaining_pct: float) -> dict[str, str]:
    """Return consistent §16 health tier: Green >30%, Yellow 20-30%, Orange 10-20%, Red <10%."""
    if remaining_pct > 30.0:
        return {"tier": "GREEN", "label": "Healthy", "badge": "green"}
    if remaining_pct >= 20.0:
        return {"tier": "YELLOW", "label": "Watch (20–30%)", "badge": "yellow"}
    if remaining_pct >= 10.0:
        return {"tier": "ORANGE", "label": "Low Balance (10–20%)", "badge": "orange"}
    return {"tier": "RED", "label": "Critical (<10%)", "badge": "red"}
