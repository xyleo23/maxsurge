"""Роуты TG -> MAX Forwarder."""
import asyncio
from pathlib import Path
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from web.routes._scope import get_request_user, scope_query
from db.models import MaxAccount, AccountStatus, ChatCatalog, async_session_factory
from max_client.tg_forwarder import (
    add_forward_rule, remove_forward_rule, get_forward_status,
    get_forward_rules, start_tg_listener, stop_tg_listener,
)
from config import get_settings

router = APIRouter(prefix="/forwarder")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))
settings = get_settings()

_task: asyncio.Task | None = None


@router.get("/", response_class=HTMLResponse)
async def forwarder_page(request: Request, msg: str = ""):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        acc_q = scope_query(select(MaxAccount), MaxAccount, user).where(MaxAccount.status == AccountStatus.ACTIVE)
        accounts = (await s.execute(acc_q)).scalars().all()
        chat_q = scope_query(select(ChatCatalog), ChatCatalog, user).where(ChatCatalog.chat_id.isnot(None))
        chats = (await s.execute(chat_q)).scalars().all()
    return templates.TemplateResponse(request=request, name="forwarder.html", context={
        "accounts": accounts, "chats": chats, "status": get_forward_status(),
        "rules": get_forward_rules(), "msg": msg,
        "tg_api_id": getattr(settings, "TG_API_ID", ""),
        "tg_api_hash": getattr(settings, "TG_API_HASH", ""),
    })


@router.post("/add-rule")
async def add_rule(
    tg_channel_id: int = Form(...),
    max_chat_ids: str = Form(...),
    strip_links: bool = Form(True),
    strip_mentions: bool = Form(True),
    stop_words: str = Form(""),
    phone: str = Form(""),
):
    chat_ids = [int(x.strip()) for x in max_chat_ids.split(",") if x.strip().lstrip("-").isdigit()]
    sw = [w.strip() for w in stop_words.split(",") if w.strip()] if stop_words else []
    add_forward_rule(tg_channel_id, chat_ids, strip_links, strip_mentions, sw, phone or None)
    return RedirectResponse("/app/forwarder/?msg=Правило+добавлено", status_code=303)


@router.post("/remove-rule")
async def remove_rule(index: int = Form(...)):
    remove_forward_rule(index)
    return RedirectResponse("/app/forwarder/?msg=Правило+удалено", status_code=303)


@router.post("/start")
async def start(tg_api_id: int = Form(...), tg_api_hash: str = Form(...)):
    global _task
    _task = asyncio.create_task(start_tg_listener(tg_api_id, tg_api_hash))
    return RedirectResponse("/app/forwarder/?msg=Listener+запущен", status_code=303)


@router.post("/stop")
async def stop():
    stop_tg_listener()
    return RedirectResponse("/app/forwarder/?msg=Остановлен", status_code=303)


@router.get("/status")
async def status():
    return JSONResponse(get_forward_status())
