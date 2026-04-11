"""CSV импорт/экспорт — лиды, собранные пользователи, логи."""
import csv
import io
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse, RedirectResponse
from sqlalchemy import select

from db.models import (
    Lead, LeadStatus, ParsedUser, SendLog, async_session_factory,
)
from db.plan_limits import check_limit
from web.routes._scope import scope_query
from web.routes.auth_r import get_current_user

router = APIRouter(prefix="/csv")


def _csv_stream(rows: list[list], headers: list[str]) -> StreamingResponse:
    def gen():
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=",", quoting=csv.QUOTE_MINIMAL)
        w.writerow(headers)
        yield buf.getvalue()
        for r in rows:
            buf.seek(0); buf.truncate()
            w.writerow(r)
            yield buf.getvalue()
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M")
    return StreamingResponse(
        gen(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="export-{stamp}.csv"'},
    )


@router.get("/export/leads")
async def export_leads(request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    async with async_session_factory() as s:
        q = scope_query(select(Lead), Lead, user).order_by(Lead.created_at.desc())
        leads = (await s.execute(q)).scalars().all()
    rows = [
        [l.id, l.name, l.phone or "", l.city or "", l.address or "",
         l.website or "", l.categories or "", (l.status.value if l.status else ""),
         l.created_at.strftime("%Y-%m-%d %H:%M") if l.created_at else ""]
        for l in leads
    ]
    return _csv_stream(rows, ["id","name","phone","city","address","website","categories","status","created_at"])


@router.get("/export/parsed")
async def export_parsed(request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    async with async_session_factory() as s:
        q = scope_query(select(ParsedUser), ParsedUser, user).order_by(ParsedUser.parsed_at.desc())
        users = (await s.execute(q)).scalars().all()
    rows = [
        [u.id, u.max_user_id, u.first_name or "", u.last_name or "", u.username or "",
         u.phone or "", u.source_chat_id or "", u.source_chat_name or "",
         u.parsed_at.strftime("%Y-%m-%d %H:%M") if u.parsed_at else ""]
        for u in users
    ]
    return _csv_stream(rows, ["id","max_user_id","first_name","last_name","username","phone","source_chat_id","source_chat_name","parsed_at"])


@router.get("/export/sendlog")
async def export_sendlog(request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    async with async_session_factory() as s:
        q = scope_query(select(SendLog), SendLog, user).order_by(SendLog.sent_at.desc())
        logs = (await s.execute(q)).scalars().all()
    rows = [
        [l.id, l.account_id, l.lead_id or "", l.template_id or "", l.target_type,
         l.target_id or "", l.status, (l.outgoing_text or "")[:300], l.error or "",
         l.sent_at.strftime("%Y-%m-%d %H:%M") if l.sent_at else ""]
        for l in logs
    ]
    return _csv_stream(rows, ["id","account_id","lead_id","template_id","target_type","target_id","status","text","error","sent_at"])


@router.post("/import/leads")
async def import_leads(request: Request, file: UploadFile = File(...)):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    content = (await file.read()).decode("utf-8-sig", errors="ignore")
    reader = csv.DictReader(io.StringIO(content))
    # Поддерживаем разные форматы заголовков
    added = 0
    skipped = 0
    async with async_session_factory() as s:
        can, cur, lim = await check_limit(s, user, Lead, "max_leads")
        if not can:
            return RedirectResponse(f"/app/leads/?msg=Лимит+лидов+{cur}/{lim}", status_code=303)

        for row in reader:
            # Нормализуем ключи
            r = {k.strip().lower(): (v or "").strip() for k, v in row.items()}
            name = r.get("name") or r.get("название") or r.get("company") or r.get("компания")
            if not name:
                skipped += 1
                continue
            phone = r.get("phone") or r.get("телефон") or ""
            dgis_id = r.get("dgis_id") or r.get("id")
            if dgis_id:
                exists = (await s.execute(select(Lead).where(Lead.dgis_id == dgis_id))).scalar_one_or_none()
                if exists:
                    skipped += 1
                    continue
            s.add(Lead(
                name=name[:500],
                phone=phone[:64] or None,
                city=(r.get("city") or r.get("город") or "")[:256] or None,
                address=(r.get("address") or r.get("адрес") or "")[:500] or None,
                website=(r.get("website") or r.get("сайт") or "")[:500] or None,
                categories=(r.get("categories") or r.get("категории") or "")[:500] or None,
                dgis_id=(dgis_id or f"csv_{user.id}_{datetime.utcnow().timestamp()}")[:64],
                status=LeadStatus.NEW,
                owner_id=user.id,
            ))
            added += 1
        await s.commit()

    return RedirectResponse(f"/app/leads/?msg=CSV+импорт:+добавлено+{added},+пропущено+{skipped}", status_code=303)
