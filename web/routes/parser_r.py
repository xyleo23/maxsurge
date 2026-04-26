"""Роуты парсинга чатов MAX."""
import asyncio
from pathlib import Path
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from web.routes._scope import get_request_user, scope_query
from db.models import ParsedUser, ChatCatalog, MaxAccount, AccountStatus, UserPlan, async_session_factory
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
    try:
        count = await parse_chat(chat_id, chat_name, phone or None)
        return RedirectResponse(f"/app/parser/?msg=Спарсено+{count}+пользователей", status_code=303)
    except Exception as e:
        err = str(e)[:200]
        # Friendly messages for common MAX errors
        if "chat.not.found" in err or "not found" in err.lower():
            msg = "Чат+не+найден.+Проверьте+ID+или+сначала+вступите+в+чат"
        elif "access" in err.lower() or "forbidden" in err.lower() or "permission" in err.lower():
            msg = "Нет+доступа+к+чату.+Вступите+в+него+через+инвайт+или+вкладку+Join"
        elif "rate" in err.lower() or "flood" in err.lower():
            msg = "Слишком+быстро.+Подождите+минуту+и+попробуйте+снова"
        elif "not_connected" in err.lower() or "WebSocket" in err:
            msg = "MAX+аккаунт+не+подключён.+Переподключите+через+/app/accounts/"
        else:
            msg = f"Ошибка:+{err[:100]}"
        import logging
        logging.getLogger("parser_r").warning("parse_one_chat err: %s", err)
        return RedirectResponse(f"/app/parser/?msg={msg}", status_code=303)

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


@router.get("/chat-pick")
async def chat_pick(
    request: Request,
    source: str = "mine",      # mine | maxsurge | mixed
    search: str = "",
    category: str = "",
    page: int = 1,
):
    """Возвращает список чатов для UI-выбора при парсинге.

    source=mine        — только сохранённые юзером (owner_id=user.id)
    source=maxsurge    — общая база MaxSurge (owner_id IS NULL, members_open=True).
                         Доступно с тарифа Basic+. Trial/Start получают locked-сигнал.
    source=mixed       — оба источника (только для админов)
    """
    user = await get_request_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, 401)

    per_page = 50
    page = max(1, page)

    BASIC_PLUS = (UserPlan.BASIC, UserPlan.PRO, UserPlan.LIFETIME)
    has_basic = user.plan in BASIC_PLUS or getattr(user, "is_superadmin", False)

    if source == "maxsurge" and not has_basic:
        # Не отказ — показываем locked-сигнал и ничего не возвращаем
        return JSONResponse({
            "locked": True,
            "reason": "База MaxSurge доступна с тарифа Basic",
            "upgrade_url": "/app/billing/",
            "items": [],
            "total": 0,
        })

    async with async_session_factory() as s:
        if source == "mine":
            q = select(ChatCatalog).where(ChatCatalog.owner_id == user.id)
        elif source == "maxsurge":
            # Только проверенные открытые чаты (не каналы)
            q = select(ChatCatalog).where(
                ChatCatalog.owner_id.is_(None),
                ChatCatalog.is_channel == False,
                ChatCatalog.members_open == True,
            )
        else:  # mixed (admin)
            if not getattr(user, "is_superadmin", False):
                return JSONResponse({"error": "forbidden"}, 403)
            q = select(ChatCatalog)

        if search:
            q = q.where(or_(
                ChatCatalog.name.ilike(f"%{search}%"),
                ChatCatalog.description.ilike(f"%{search}%"),
            ))
        if category:
            q = q.where(ChatCatalog.category == category)

        total = (await s.execute(
            select(func.count()).select_from(q.subquery())
        )).scalar() or 0

        rows = (await s.execute(
            q.order_by(ChatCatalog.members_count.desc().nullslast())
             .offset((page - 1) * per_page)
             .limit(per_page)
        )).scalars().all()

        # Distinct categories для фильтра
        cat_q = select(ChatCatalog.category).distinct().where(ChatCatalog.category.isnot(None))
        if source == "mine":
            cat_q = cat_q.where(ChatCatalog.owner_id == user.id)
        elif source == "maxsurge":
            cat_q = cat_q.where(ChatCatalog.owner_id.is_(None), ChatCatalog.members_open == True)
        categories = [c for c in (await s.execute(cat_q)).scalars().all() if c]

    return JSONResponse({
        "locked": False,
        "items": [{
            "id": r.id,
            "chat_id": r.chat_id,
            "name": r.name,
            "members_count": r.members_count,
            "category": r.category,
            "is_channel": r.is_channel,
            "members_open": r.members_open,
            "invite_link": r.invite_link,
            "parsed_count": r.parsed_count,
        } for r in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "has_next": total > page * per_page,
        "categories": sorted(categories),
        "user_plan": user.plan.value,
        "has_basic_plus": has_basic,
    })


@router.get("/export-ids")
async def export_ids(request: Request, chat_id: int = 0):
    """Экспорт max_user_id для вставки в инвайтинг."""
    from fastapi.responses import PlainTextResponse
    user = await get_request_user(request)
    async with async_session_factory() as s:
        q = scope_query(select(ParsedUser.max_user_id), ParsedUser, user).where(ParsedUser.max_user_id.isnot(None))
        if chat_id:
            q = q.where(ParsedUser.source_chat_id == chat_id)
        q = q.distinct()
        ids = (await s.execute(q)).scalars().all()
    text = chr(10).join(str(uid) for uid in ids)
    return PlainTextResponse(text, headers={"Content-Disposition": f"attachment; filename=user_ids_{len(ids)}.txt"})
