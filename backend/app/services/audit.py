"""Immutable audit trail service."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from ..security import Actor


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def log_audit(
    conn: sqlite3.Connection,
    actor: Actor,
    action: str,
    entity_type: str,
    entity_id: str | int,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
    timestamp: str | None = None,
) -> int:
    """Append an immutable entry to audit_logs."""
    cur = conn.execute(
        """
        INSERT INTO audit_logs (
            timestamp, actor_name, actor_role, action,
            entity_type, entity_id, before_json, after_json, reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            timestamp or utc_now_iso(),
            actor.name,
            actor.role,
            action,
            entity_type,
            str(entity_id),
            json.dumps(before, sort_keys=True, default=str) if before is not None else None,
            json.dumps(after, sort_keys=True, default=str) if after is not None else None,
            reason,
        ),
    )
    return int(cur.lastrowid)
