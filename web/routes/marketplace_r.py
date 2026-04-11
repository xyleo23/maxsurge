"""Маркетплейс шаблонов — публичная галерея, где юзеры делятся шаблонами."""
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc, func

from db.models import (
    MessageTemplate, TemplateStatus, SiteUser, async_session_factory,
)
from db.plan_limits import check_limit
from web.routes.auth_r import get_current_user

router = APIRouter(prefix="/marketplace")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

CATEGORIES = [
    ("sales", "Продажи"),
    ("services", "Услуги"),
    ("realestate", "Недвижимость"),
    ("ecommerce", "E-commerce"),
    ("info", "Инфобизнес"),
    ("b2b", "B2B"),
    ("other", "Другое"),
]


@router.get("/", response_class=HTMLResponse)
async def page(request: Request, category: str = "", search: str = "", msg: str = ""):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    async with async_session_factory() as s:
        q = select(MessageTemplate).where(
            MessageTemplate.is_public == True,  # noqa
            MessageTemplate.status == TemplateStatus.APPROVED,
        )
        if category:
            q = q.where(MessageTemplate.public_category == category)
        if search:
            q = q.where(MessageTemplate.name.contains(search) | MessageTemplate.body.contains(search))
        q = q.order_by(desc(MessageTemplate.copies_count), desc(MessageTemplate.created_at)).limit(100)
        items = (await s.execute(q)).scalars().all()

        # Автор-инфо
        author_ids = {t.owner_id for t in items if t.owner_id}
        authors = {}
        if author_ids:
            res = await s.execute(select(SiteUser).where(SiteUser.id.in_(author_ids)))
            authors = {u.id: u for u in res.scalars().all()}

    return templates.TemplateResponse(
        request=request,
        name="marketplace.html",
        context={
            "items": items,
            "authors": authors,
            "categories": CATEGORIES,
            "category": category,
            "search": search,
            "msg": msg,
        },
    )


@router.post("/{template_id}/copy")
async def copy_template(request: Request, template_id: int):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    async with async_session_factory() as s:
        src = await s.get(MessageTemplate, template_id)
        if not src or not src.is_public or src.status != TemplateStatus.APPROVED:
            return RedirectResponse("/app/marketplace/?msg=Шаблон+недоступен", status_code=303)

        can, cur, lim = await check_limit(s, user, MessageTemplate, "max_templates")
        if not can:
            return RedirectResponse(f"/app/marketplace/?msg=Лимит+шаблонов+{cur}/{lim}", status_code=303)

        copy = MessageTemplate(
            name=f"{src.name} (копия из маркетплейса)",
            body=src.body,
            attachment_url=src.attachment_url,
            owner_id=user.id,
            status=TemplateStatus.APPROVED,  # уже прошёл модерацию у автора
            is_public=False,
        )
        s.add(copy)
        src.copies_count += 1
        await s.commit()

    return RedirectResponse("/app/templates/?msg=Шаблон+скопирован+из+маркетплейса", status_code=303)


@router.post("/{template_id}/publish")
async def publish_template(
    request: Request,
    template_id: int,
    category: str = Form("other"),
):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    async with async_session_factory() as s:
        tmpl = await s.get(MessageTemplate, template_id)
        if not tmpl:
            return RedirectResponse("/app/templates/?msg=Не+найден", status_code=303)
        if tmpl.owner_id != user.id and not user.is_superadmin:
            return RedirectResponse("/app/templates/?msg=Нет+доступа", status_code=303)
        if tmpl.status != TemplateStatus.APPROVED:
            return RedirectResponse("/app/templates/?msg=Сначала+пройдите+модерацию", status_code=303)
        tmpl.is_public = True
        tmpl.public_category = category if category in [c[0] for c in CATEGORIES] else "other"
        await s.commit()
    return RedirectResponse("/app/templates/?msg=Опубликовано+в+маркетплейсе", status_code=303)


@router.post("/{template_id}/unpublish")
async def unpublish_template(request: Request, template_id: int):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    async with async_session_factory() as s:
        tmpl = await s.get(MessageTemplate, template_id)
        if not tmpl or (tmpl.owner_id != user.id and not user.is_superadmin):
            return RedirectResponse("/app/templates/?msg=Нет+доступа", status_code=303)
        tmpl.is_public = False
        await s.commit()
    return RedirectResponse("/app/templates/?msg=Снято+с+маркетплейса", status_code=303)
