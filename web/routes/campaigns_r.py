"""Кампании рассылки — сохранённые конфиги для повторного запуска."""
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc

from db.models import (
    BroadcastCampaign, MessageTemplate, TemplateStatus, async_session_factory,
)
from web.routes._scope import scope_query
from web.routes.auth_r import get_current_user

router = APIRouter(prefix="/campaigns")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def page(request: Request, msg: str = ""):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    async with async_session_factory() as s:
        camps = (await s.execute(
            scope_query(select(BroadcastCampaign), BroadcastCampaign, user).order_by(desc(BroadcastCampaign.created_at))
        )).scalars().all()
        tmpls = (await s.execute(
            scope_query(select(MessageTemplate), MessageTemplate, user)
        )).scalars().all()
    return templates.TemplateResponse(
        request=request,
        name="campaigns.html",
        context={"campaigns": camps, "templates": tmpls, "msg": msg},
    )


@router.post("/create")
async def create(
    request: Request,
    name: str = Form(...),
    template_id: int = Form(...),
    template_b_id: int = Form(0),
    target_type: str = Form("users"),
    limit: int = Form(50),
    typing_emulation: bool = Form(True),
):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    async with async_session_factory() as s:
        s.add(BroadcastCampaign(
            owner_id=user.id,
            name=name,
            template_id=template_id,
            template_b_id=template_b_id or None,
            target_type=target_type,
            limit=max(1, limit),
            typing_emulation=typing_emulation,
        ))
        await s.commit()
    return RedirectResponse("/app/campaigns/?msg=Кампания+создана", status_code=303)


@router.post("/{camp_id}/run")
async def run_campaign(camp_id: int, request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    async with async_session_factory() as s:
        c = await s.get(BroadcastCampaign, camp_id)
        if not c or (c.owner_id != user.id and not user.is_superadmin):
            return RedirectResponse("/app/campaigns/?msg=Нет+доступа", status_code=303)
        # Check template approved
        tmpl = await s.get(MessageTemplate, c.template_id)
        if not tmpl or (tmpl.status and tmpl.status != TemplateStatus.APPROVED):
            return RedirectResponse("/app/campaigns/?msg=Шаблон+не+одобрен", status_code=303)

    from max_client.sender import start_broadcast_background
    try:
        start_broadcast_background(
            c.template_id, c.limit, False, None, c.target_type, c.typing_emulation,
            template_b_id=c.template_b_id,
        )
    except RuntimeError as e:
        return RedirectResponse(f"/app/campaigns/?msg={e}", status_code=303)

    async with async_session_factory() as s:
        camp = await s.get(BroadcastCampaign, camp_id)
        camp.last_run_at = datetime.utcnow()
        camp.total_runs += 1
        await s.commit()

    return RedirectResponse("/app/campaigns/?msg=Кампания+запущена", status_code=303)


@router.post("/{camp_id}/delete")
async def delete_campaign(camp_id: int, request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    async with async_session_factory() as s:
        c = await s.get(BroadcastCampaign, camp_id)
        if c and (c.owner_id == user.id or user.is_superadmin):
            await s.delete(c)
            await s.commit()
    return RedirectResponse("/app/campaigns/?msg=Удалено", status_code=303)
