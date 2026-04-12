"""Настройки пользователя: AI ключ, смена пароля, профиль."""
from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from passlib.hash import bcrypt

from sqlalchemy import func, select
from db.models import SiteUser, MaxAccount, Lead, Task, MessageTemplate, UserFile, async_session_factory
from db.plan_limits import get_limits, is_superadmin
from web.routes.auth_r import get_current_user

router = APIRouter(prefix="/settings")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def settings_page(request: Request, msg: str = ""):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    # Посчитать использование по тарифу
    usage = {}
    limits = {}
    if not is_superadmin(user):
        limits = get_limits(user.plan)
        async with async_session_factory() as s:
            usage = {
                "accounts": (await s.execute(select(func.count(MaxAccount.id)).where(MaxAccount.owner_id == user.id))).scalar() or 0,
                "leads": (await s.execute(select(func.count(Lead.id)).where(Lead.owner_id == user.id))).scalar() or 0,
                "tasks": (await s.execute(select(func.count(Task.id)).where(Task.owner_id == user.id))).scalar() or 0,
                "templates": (await s.execute(select(func.count(MessageTemplate.id)).where(MessageTemplate.owner_id == user.id))).scalar() or 0,
                "files": (await s.execute(select(func.count(UserFile.id)).where(UserFile.owner_id == user.id))).scalar() or 0,
            }

    return templates.TemplateResponse(request=request, name="settings.html", context={
        "user": user,
        "msg": msg,
        "usage": usage,
        "limits": limits,
        "is_admin": is_superadmin(user),
    })


@router.post("/ai")
async def save_ai_settings(
    request: Request,
    ai_api_url: str = Form(""),
    ai_api_key: str = Form(""),
    ai_model: str = Form(""),
    webhook_url: str = Form(""),
):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    async with async_session_factory() as s:
        db_user = await s.get(SiteUser, user.id)
        if db_user:
            db_user.ai_api_url = ai_api_url.strip() or None
            # Не затираем ключ если передана маска ****
            if ai_api_key and not ai_api_key.startswith("***"):
                db_user.ai_api_key = ai_api_key.strip() or None
            db_user.ai_model = ai_model.strip() or None
            db_user.webhook_url = webhook_url.strip() or None
            await s.commit()

    return RedirectResponse("/app/settings/?msg=Настройки+AI+сохранены", status_code=303)


@router.post("/profile")
async def save_profile(
    request: Request,
    name: str = Form(""),
):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    async with async_session_factory() as s:
        db_user = await s.get(SiteUser, user.id)
        if db_user:
            db_user.name = name.strip() or None
            await s.commit()

    return RedirectResponse("/app/settings/?msg=Профиль+обновлён", status_code=303)


@router.post("/password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    if not bcrypt.verify(current_password, user.password_hash):
        return RedirectResponse("/app/settings/?msg=Неверный+текущий+пароль", status_code=303)

    if len(new_password) < 6:
        return RedirectResponse("/app/settings/?msg=Пароль+минимум+6+символов", status_code=303)

    async with async_session_factory() as s:
        db_user = await s.get(SiteUser, user.id)
        if db_user:
            db_user.password_hash = bcrypt.using(rounds=12).hash(new_password)
            await s.commit()

    return RedirectResponse("/app/settings/?msg=Пароль+изменён", status_code=303)
