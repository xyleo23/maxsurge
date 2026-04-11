"""Управление шаблонами сообщений (с изоляцией и лимитами)."""
from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from db.models import MessageTemplate, async_session_factory
from db.plan_limits import check_limit
from web.routes._scope import get_request_user, scope_query

router = APIRouter(prefix="/templates")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def templates_list(request: Request, msg: str = ""):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        q = scope_query(select(MessageTemplate), MessageTemplate, user).order_by(MessageTemplate.created_at.desc())
        tmpls = (await s.execute(q)).scalars().all()
    return templates.TemplateResponse(request=request, name="templates.html", context={
        "templates": tmpls,
        "msg": msg,
    })


@router.post("/create")
async def create_template(
    request: Request,
    name: str = Form(...),
    body: str = Form(...),
    attachment_url: str = Form(""),
):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        can_add, current, limit = await check_limit(s, user, MessageTemplate, "max_templates")
        if not can_add:
            return RedirectResponse(
                f"/app/templates/?msg=Лимит+шаблонов+({current}/{limit})",
                status_code=303,
            )
        tmpl = MessageTemplate(
            name=name,
            body=body,
            attachment_url=attachment_url.strip() or None,
            owner_id=user.id if user else None,
        )
        s.add(tmpl)
        await s.commit()
    return RedirectResponse("/app/templates/?msg=Шаблон+создан", status_code=303)


async def _get_tmpl_if_owned(session, tmpl_id: int, user):
    tmpl = await session.get(MessageTemplate, tmpl_id)
    if not tmpl:
        return None
    if user and getattr(user, "is_superadmin", False):
        return tmpl
    if tmpl.owner_id == (user.id if user else None):
        return tmpl
    return None


@router.post("/{tmpl_id}/update")
async def update_template(
    request: Request,
    tmpl_id: int,
    name: str = Form(...),
    body: str = Form(...),
    attachment_url: str = Form(""),
):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        tmpl = await _get_tmpl_if_owned(s, tmpl_id, user)
        if tmpl:
            tmpl.name = name
            tmpl.body = body
            tmpl.attachment_url = attachment_url.strip() or None
            await s.commit()
    return RedirectResponse("/app/templates/?msg=Шаблон+обновлён", status_code=303)


@router.post("/{tmpl_id}/delete")
async def delete_template(request: Request, tmpl_id: int):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        tmpl = await _get_tmpl_if_owned(s, tmpl_id, user)
        if tmpl:
            await s.delete(tmpl)
            await s.commit()
    return RedirectResponse("/app/templates/", status_code=303)
