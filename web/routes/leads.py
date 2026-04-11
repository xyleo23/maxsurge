"""Управление лидами (с изоляцией по owner_id)."""
import csv
import io
from pathlib import Path

from fastapi import APIRouter, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, or_

from db.models import Lead, LeadStatus, async_session_factory
from web.routes._scope import get_request_user, scope_query

router = APIRouter(prefix="/leads")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

PAGE_SIZE = 30


@router.get("/", response_class=HTMLResponse)
async def leads_list(
    request: Request,
    page: int = Query(1, ge=1),
    status: str = Query(""),
    city: str = Query(""),
    search: str = Query(""),
):
    user = await get_request_user(request)
    offset = (page - 1) * PAGE_SIZE

    async with async_session_factory() as s:
        q = scope_query(select(Lead), Lead, user)
        if status:
            q = q.where(Lead.status == LeadStatus(status))
        if city:
            q = q.where(Lead.city.ilike(f"%{city}%"))
        if search:
            q = q.where(or_(
                Lead.name.ilike(f"%{search}%"),
                Lead.phone.ilike(f"%{search}%"),
            ))

        total = (await s.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
        leads = (await s.execute(q.order_by(Lead.created_at.desc()).offset(offset).limit(PAGE_SIZE))).scalars().all()

        cities_q = scope_query(select(Lead.city), Lead, user).distinct().where(Lead.city.isnot(None))
        cities = (await s.execute(cities_q)).scalars().all()

    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    return templates.TemplateResponse(request=request, name="leads.html", context={
        "leads": leads,
        "page": page,
        "pages": pages,
        "total": total,
        "status_filter": status,
        "city_filter": city,
        "search": search,
        "cities": sorted(c for c in cities if c),
        "statuses": [s.value for s in LeadStatus],
    })


async def _get_lead_if_owned(session, lead_id: int, user):
    """Получить лид, только если принадлежит user (или user — суперадмин)."""
    lead = await session.get(Lead, lead_id)
    if not lead:
        return None
    if user and getattr(user, "is_superadmin", False):
        return lead
    if lead.owner_id == (user.id if user else None):
        return lead
    return None


@router.post("/{lead_id}/status")
async def update_status(request: Request, lead_id: int, status: str = Form(...)):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        lead = await _get_lead_if_owned(s, lead_id, user)
        if lead:
            lead.status = LeadStatus(status)
            await s.commit()
    return RedirectResponse("/app/leads/", status_code=303)


@router.post("/{lead_id}/set-max-id")
async def set_max_id(request: Request, lead_id: int, max_user_id: int = Form(...)):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        lead = await _get_lead_if_owned(s, lead_id, user)
        if lead:
            lead.max_user_id = max_user_id
            await s.commit()
    return RedirectResponse("/app/leads/", status_code=303)


@router.post("/{lead_id}/delete")
async def delete_lead(request: Request, lead_id: int):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        lead = await _get_lead_if_owned(s, lead_id, user)
        if lead:
            await s.delete(lead)
            await s.commit()
    return RedirectResponse("/app/leads/", status_code=303)


@router.get("/export")
async def export_csv(request: Request):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        q = scope_query(select(Lead), Lead, user).order_by(Lead.created_at.desc())
        leads = (await s.execute(q)).scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "name", "city", "phone", "categories", "status", "max_user_id", "created_at"])
    for l in leads:
        writer.writerow([l.id, l.name, l.city, l.phone, l.categories, l.status.value, l.max_user_id, l.created_at])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )
