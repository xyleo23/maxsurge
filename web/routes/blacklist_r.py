"""Блэклист — исключение юзеров/номеров из рассылки и инвайтинга."""
from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc

from db.models import Blacklist, async_session_factory
from web.routes._scope import scope_query
from web.routes.auth_r import get_current_user

router = APIRouter(prefix="/blacklist")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def page(request: Request, msg: str = ""):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    async with async_session_factory() as s:
        q = scope_query(select(Blacklist), Blacklist, user).order_by(desc(Blacklist.created_at))
        items = (await s.execute(q)).scalars().all()
    return templates.TemplateResponse(
        request=request,
        name="blacklist.html",
        context={"items": items, "msg": msg, "total": len(items)},
    )


@router.post("/add")
async def add(
    request: Request,
    values: str = Form(""),
    type: str = Form("phone"),
    reason: str = Form(""),
):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    added = 0
    async with async_session_factory() as s:
        for line in values.replace(",", "\n").splitlines():
            v = line.strip()
            if not v:
                continue
            exists = (await s.execute(
                select(Blacklist).where(Blacklist.owner_id == user.id, Blacklist.value == v)
            )).scalar_one_or_none()
            if exists:
                continue
            s.add(Blacklist(owner_id=user.id, value=v, type=type, reason=reason[:256] or None))
            added += 1
        await s.commit()
    return RedirectResponse(f"/app/blacklist/?msg=Добавлено+{added}", status_code=303)


@router.post("/{item_id}/delete")
async def delete(item_id: int, request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    async with async_session_factory() as s:
        item = await s.get(Blacklist, item_id)
        if item and (item.owner_id == user.id or getattr(user, "is_superadmin", False)):
            await s.delete(item)
            await s.commit()
    return RedirectResponse("/app/blacklist/?msg=Удалено", status_code=303)


async def is_blacklisted(owner_id: int, value: str) -> bool:
    """Check if value is blacklisted for this owner (called from sender/inviter)."""
    async with async_session_factory() as s:
        res = await s.execute(
            select(Blacklist.id).where(Blacklist.owner_id == owner_id, Blacklist.value == value).limit(1)
        )
        return res.scalar_one_or_none() is not None
