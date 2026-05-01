from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditEvent


async def log_audit(
    session: AsyncSession,
    *,
    user_id: str | None,
    document_set_id: str | None,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    payload_before: dict[str, Any] | None = None,
    payload_after: dict[str, Any] | None = None,
    meta_json: dict[str, Any] | None = None,
) -> None:
    ev = AuditEvent(
        user_id=user_id,
        document_set_id=document_set_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        payload_before=payload_before,
        payload_after=payload_after,
        meta_json=meta_json,
    )
    session.add(ev)
