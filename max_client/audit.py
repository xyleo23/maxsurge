"""Audit log helper — call from admin endpoints to record actions."""
from db.models import AuditLog, async_session_factory


async def log_audit(actor, action: str, target_type: str | None = None,
                    target_id: int | None = None, details: str = "", ip: str = ""):
    try:
        async with async_session_factory() as s:
            s.add(AuditLog(
                actor_id=actor.id if actor else None,
                actor_email=actor.email if actor else None,
                action=action,
                target_type=target_type,
                target_id=target_id,
                details=details[:2000] if details else None,
                ip=ip,
            ))
            await s.commit()
    except Exception:
        pass
