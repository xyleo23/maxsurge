"""Lead capture API — сбор email из exit-intent попапа и других лид-магнитов.

POST /api/lead — принимает {email, source}, сохраняет в таблицу captured_leads.
"""
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel, EmailStr
from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from db.models import Base, async_session_factory as asf

router = APIRouter()


# ── Модель (регистрируется в Base.metadata автоматически) ────
class CapturedLead(Base):
    __tablename__ = "captured_leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    source: Mapped[str] = mapped_column(String(64), default="unknown")
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class LeadIn(BaseModel):
    email: str
    source: str = "unknown"


@router.post("/api/lead")
async def capture_lead(data: LeadIn, request: Request):
    email = data.email.strip().lower()
    if not email or "@" not in email or "." not in email:
        return JSONResponse({"ok": False, "error": "invalid email"}, status_code=400)

    ip = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", "").split(",")[0].strip() or request.client.host

    try:
        async with asf() as s:
            s.add(CapturedLead(email=email, source=data.source, ip=ip))
            await s.commit()
        logger.info("[lead-capture] email={} source={} ip={}", email, data.source, ip)
    except Exception as e:
        logger.warning("[lead-capture] failed: {}", e)
        return JSONResponse({"ok": False}, status_code=500)

    return JSONResponse({"ok": True})
