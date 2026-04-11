"""Роуты MAX-ботов: Лид-боты / Бонус-боты / Саппорт-боты."""
import json
from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc

from db.models import (
    MaxBot, MaxBotType, MaxBotLead, MaxBotBonusClaim, async_session_factory,
)
from db.plan_limits import check_limit
from web.routes._scope import scope_query
from web.routes.auth_r import get_current_user
from max_client import bot_runner
from max_client.botapi import MaxBotAPI

router = APIRouter(prefix="/bots")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def page(request: Request, msg: str = "", err: str = ""):
    user = await get_current_user(request)
    async with async_session_factory() as s:
        q = scope_query(select(MaxBot), MaxBot, user).order_by(desc(MaxBot.created_at))
        bots = (await s.execute(q)).scalars().all()
    running = bot_runner.get_running_ids()
    return templates.TemplateResponse(
        request=request,
        name="bots.html",
        context={
            "bots": bots,
            "running": running,
            "msg": msg,
            "err": err,
            "types": [("lead", "Лид-бот"), ("bonus", "Бонус-бот"), ("support", "Саппорт-бот")],
        },
    )


@router.post("/create")
async def create(
    request: Request,
    name: str = Form(...),
    bot_type: str = Form("lead"),
    token: str = Form(...),
    welcome_text: str = Form(""),
    finish_text: str = Form(""),
    steps_json: str = Form("[]"),
    bonus_code: str = Form(""),
    bonus_description: str = Form(""),
    bonus_limit: int = Form(0),
    ai_enabled: bool = Form(False),
    knowledge_base: str = Form(""),
    notify_owner_tg: bool = Form(True),
):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    # Валидация токена — пытаемся /me
    api = MaxBotAPI(token.strip())
    me = await api.get_me()
    await api.close()
    if "error" in me or not me:
        return RedirectResponse(f"/app/bots/?err=Токен не принял MAX Bot API", status_code=303)

    bot_username = me.get("username") or me.get("name")
    bot_user_id = me.get("user_id") or me.get("id")

    async with async_session_factory() as s:
        can, cur, lim = await check_limit(s, user, MaxBot, "max_tasks")
        if not can:
            return RedirectResponse(f"/app/bots/?err=Лимит ботов {cur}/{lim}", status_code=303)

        try:
            json.loads(steps_json)
        except Exception:
            return RedirectResponse("/app/bots/?err=Невалидный JSON шагов", status_code=303)

        b = MaxBot(
            name=name,
            bot_type=MaxBotType(bot_type),
            token=token.strip(),
            bot_username=bot_username,
            bot_user_id=bot_user_id,
            welcome_text=welcome_text or "Здравствуйте!",
            finish_text=finish_text or "Спасибо!",
            steps=steps_json,
            bonus_code=bonus_code or None,
            bonus_description=bonus_description or None,
            bonus_limit=max(0, bonus_limit),
            ai_enabled=ai_enabled,
            knowledge_base=knowledge_base or None,
            notify_owner_tg=notify_owner_tg,
            owner_id=user.id,
        )
        s.add(b)
        await s.commit()

    return RedirectResponse("/app/bots/?msg=Бот создан", status_code=303)


async def _check_owner(bot_id: int, user) -> MaxBot | None:
    async with async_session_factory() as s:
        b = await s.get(MaxBot, bot_id)
    if not b:
        return None
    if not user.is_superadmin and b.owner_id != user.id:
        return None
    return b


@router.post("/{bot_id}/start")
async def start(bot_id: int, request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not await _check_owner(bot_id, user):
        return RedirectResponse("/app/bots/?err=Нет доступа", status_code=303)
    ok, msg = await bot_runner.start_bot(bot_id)
    return RedirectResponse(f"/app/bots/?{'msg' if ok else 'err'}={msg}", status_code=303)


@router.post("/{bot_id}/stop")
async def stop(bot_id: int, request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not await _check_owner(bot_id, user):
        return RedirectResponse("/app/bots/?err=Нет доступа", status_code=303)
    ok, msg = await bot_runner.stop_bot(bot_id)
    return RedirectResponse(f"/app/bots/?{'msg' if ok else 'err'}={msg}", status_code=303)


@router.post("/{bot_id}/delete")
async def delete(bot_id: int, request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not await _check_owner(bot_id, user):
        return RedirectResponse("/app/bots/?err=Нет доступа", status_code=303)
    await bot_runner.stop_bot(bot_id)
    async with async_session_factory() as s:
        b = await s.get(MaxBot, bot_id)
        if b:
            await s.delete(b)
            await s.commit()
    return RedirectResponse("/app/bots/?msg=Удалён", status_code=303)


@router.get("/{bot_id}/leads", response_class=HTMLResponse)
async def view_leads(bot_id: int, request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    b = await _check_owner(bot_id, user)
    if not b:
        return RedirectResponse("/app/bots/?err=Нет доступа", status_code=303)
    async with async_session_factory() as s:
        if b.bot_type == MaxBotType.BONUS:
            q = select(MaxBotBonusClaim).where(MaxBotBonusClaim.bot_id == bot_id).order_by(desc(MaxBotBonusClaim.created_at)).limit(500)
            items = (await s.execute(q)).scalars().all()
        else:
            q = select(MaxBotLead).where(MaxBotLead.bot_id == bot_id).order_by(desc(MaxBotLead.created_at)).limit(500)
            items = (await s.execute(q)).scalars().all()
    return templates.TemplateResponse(
        request=request,
        name="bots_leads.html",
        context={"bot": b, "items": items, "is_bonus": b.bot_type == MaxBotType.BONUS},
    )
