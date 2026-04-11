"""Мастер настройки персональных TG уведомлений пользователя.

Юзер создаёт бота через @BotFather, сохраняет токен у нас, жмёт «Подключить»,
мы поллим getUpdates и ждём /start от юзера, сохраняем его chat_id.
Потом sends on_lead/on_payment/on_task_done в его бота.
"""
import asyncio
from pathlib import Path

import httpx
from loguru import logger
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from db.models import SiteUser, async_session_factory
from web.routes.auth_r import get_current_user

router = APIRouter(prefix="/notifications")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def page(request: Request, msg: str = ""):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    # Пробуем получить имя бота если токен есть
    bot_info = None
    if user.user_tg_bot_token:
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(f"https://api.telegram.org/bot{user.user_tg_bot_token}/getMe")
                data = r.json()
                if data.get("ok"):
                    bot_info = data["result"]
        except Exception:
            pass

    return templates.TemplateResponse(
        request=request,
        name="notifications.html",
        context={"user": user, "msg": msg, "bot_info": bot_info},
    )


@router.post("/save-token")
async def save_token(request: Request, token: str = Form(...)):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    token = token.strip()
    # Валидация
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"https://api.telegram.org/bot{token}/getMe")
            data = r.json()
            if not data.get("ok"):
                return RedirectResponse("/app/notifications/?msg=Токен+не+прошёл+проверку", status_code=303)
    except Exception:
        return RedirectResponse("/app/notifications/?msg=Ошибка+связи+с+TG", status_code=303)

    async with async_session_factory() as s:
        u = await s.get(SiteUser, user.id)
        u.user_tg_bot_token = token
        u.tg_chat_id = None  # reset привязку
        await s.commit()
    return RedirectResponse("/app/notifications/?msg=Токен+сохранён.+Теперь+напишите+/start+вашему+боту", status_code=303)


@router.post("/detect-chat")
async def detect_chat(request: Request):
    """Поллит getUpdates до 20с, ждёт первое сообщение от владельца бота."""
    user = await get_current_user(request)
    if not user or not user.user_tg_bot_token:
        return JSONResponse({"ok": False, "error": "Нет токена"})

    token = user.user_tg_bot_token
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    deadline = 20
    last_update_id = 0
    found_chat = None
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            for _ in range(deadline // 2):
                r = await c.get(url, params={"offset": last_update_id + 1, "timeout": 2})
                d = r.json()
                if d.get("ok") and d.get("result"):
                    for upd in d["result"]:
                        last_update_id = upd["update_id"]
                        msg = upd.get("message") or upd.get("channel_post")
                        if msg and "chat" in msg:
                            found_chat = msg["chat"]
                            break
                if found_chat:
                    break
                await asyncio.sleep(1)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]})

    if not found_chat:
        return JSONResponse({"ok": False, "error": "Пока не получено ни одного сообщения. Напишите боту /start и попробуйте ещё раз."})

    chat_id = str(found_chat.get("id"))
    async with async_session_factory() as s:
        u = await s.get(SiteUser, user.id)
        u.tg_chat_id = chat_id
        await s.commit()

    # Приветственное сообщение
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": "🎉 <b>Уведомления подключены!</b>\n\nТеперь вы будете получать в этот чат сообщения о новых лидах, платежах и завершённых задачах.",
                    "parse_mode": "HTML",
                },
            )
    except Exception:
        pass

    return JSONResponse({"ok": True, "chat_id": chat_id, "name": found_chat.get("first_name") or found_chat.get("title")})


@router.post("/test")
async def test_notification(request: Request):
    user = await get_current_user(request)
    if not user or not user.user_tg_bot_token or not user.tg_chat_id:
        return RedirectResponse("/app/notifications/?msg=Сначала+подключите+бота+и+чат", status_code=303)
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(
                f"https://api.telegram.org/bot{user.user_tg_bot_token}/sendMessage",
                json={
                    "chat_id": user.tg_chat_id,
                    "text": "🔔 <b>Тест уведомления</b>\n\nВсё работает! MaxSurge будет присылать сюда события.",
                    "parse_mode": "HTML",
                },
            )
    except Exception as e:
        return RedirectResponse(f"/app/notifications/?msg=Ошибка:+{str(e)[:100]}", status_code=303)
    return RedirectResponse("/app/notifications/?msg=Тестовое+сообщение+отправлено", status_code=303)


@router.post("/preferences")
async def save_prefs(
    request: Request,
    notify_on_lead: bool = Form(False),
    notify_on_payment: bool = Form(False),
    notify_on_task_done: bool = Form(False),
):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    async with async_session_factory() as s:
        u = await s.get(SiteUser, user.id)
        u.notify_on_lead = notify_on_lead
        u.notify_on_payment = notify_on_payment
        u.notify_on_task_done = notify_on_task_done
        await s.commit()
    return RedirectResponse("/app/notifications/?msg=Настройки+сохранены", status_code=303)


@router.post("/disconnect")
async def disconnect(request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    async with async_session_factory() as s:
        u = await s.get(SiteUser, user.id)
        u.user_tg_bot_token = None
        u.tg_chat_id = None
        await s.commit()
    return RedirectResponse("/app/notifications/?msg=Отключено", status_code=303)
