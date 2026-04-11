"""Роуты парсинга чатов MAX."""
import asyncio
from pathlib import Path
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from web.routes._scope import get_request_user, scope_query
from db.models import ParsedUser, ChatCatalog, MaxAccount, AccountStatus, async_session_factory
from max_client.parser import mass_join_chats, parse_chat, get_parse_status, stop_parsing, parse_by_messages_phones

router = APIRouter(prefix="/parser")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

_task: asyncio.Task | None = None

@router.get("/", response_class=HTMLResponse)
async def parser_page(request: Request, msg: str = ""):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        acc_q = scope_query(select(MaxAccount), MaxAccount, user).where(MaxAccount.status == AccountStatus.ACTIVE)
        accounts = (await s.execute(acc_q)).scalars().all()
        pu_q = scope_query(select(func.count(ParsedUser.id)), ParsedUser, user)
        parsed_total = (await s.execute(pu_q)).scalar() or 0
        cc_q = scope_query(select(func.count(ChatCatalog.id)), ChatCatalog, user)
        chats_in_catalog = (await s.execute(cc_q)).scalar() or 0
    return templates.TemplateResponse(request=request, name="parser.html", context={
        "accounts": accounts, "parsed_total": parsed_total,
        "chats_in_catalog": chats_in_catalog, "status": get_parse_status(), "msg": msg,
    })

@router.post("/join")
async def join_chats(links: str = Form(""), phone: str = Form("")):
    global _task
    link_list = [l.strip() for l in links.strip().splitlines() if l.strip()]
    if not link_list:
        return RedirectResponse("/app/parser/?msg=Введите+ссылки", status_code=303)
    _task = asyncio.create_task(mass_join_chats(link_list, phone or None))
    return RedirectResponse("/app/parser/?msg=Вступление+запущено", status_code=303)

@router.post("/parse")
async def parse_one_chat(chat_id: int = Form(...), chat_name: str = Form(""), phone: str = Form("")):
    count = await parse_chat(chat_id, chat_name, phone or None)
    return RedirectResponse(f"/app/parser/?msg=Спарсено+{count}+пользователей", status_code=303)

@router.post("/stop")
async def stop():
    stop_parsing()
    return RedirectResponse("/app/parser/?msg=Остановлено", status_code=303)

@router.get("/status")
async def status():
    return JSONResponse(get_parse_status())


@router.post('/parse-messages')
async def parse_messages_route(
    request: Request,
    chat_ids: str = Form(...),
    max_messages: int = Form(2000),
    phone: str = Form(''),
):
    global _task
    user = await get_request_user(request)
    ids = []
    for part in chat_ids.replace(chr(10), ',').split(','):
        part = part.strip()
        if part.lstrip('-').isdigit():
            ids.append(int(part))
    if not ids:
        return RedirectResponse('/app/parser/?msg=Нет+валидных+chat_id', status_code=303)

    async with async_session_factory() as s:
        acc_q = scope_query(select(MaxAccount), MaxAccount, user).where(MaxAccount.status == AccountStatus.ACTIVE)
        accounts = (await s.execute(acc_q)).scalars().all()
    phones = [phone] if phone else [a.phone for a in accounts]
    if not phones:
        return RedirectResponse('/app/parser/?msg=Нет+активных+аккаунтов', status_code=303)

    _task = asyncio.create_task(
        parse_by_messages_phones(phones, ids, owner_id=user.id if user else None, max_messages=max_messages)
    )
    return RedirectResponse('/app/parser/?msg=Парсинг+по+сообщениям+запущен', status_code=303)
