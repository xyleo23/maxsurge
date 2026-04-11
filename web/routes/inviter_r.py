"""Роуты инвайтинга."""
import asyncio
from pathlib import Path
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from web.routes._scope import get_request_user, scope_query
from db.models import MaxAccount, AccountStatus, ParsedUser, async_session_factory
from max_client.inviter import run_inviting, get_invite_status, stop_inviting, pause_inviting

router = APIRouter(prefix="/inviter")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

@router.get("/", response_class=HTMLResponse)
async def page(request: Request, msg: str = ""):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        acc_q = scope_query(select(MaxAccount), MaxAccount, user).where(MaxAccount.status == AccountStatus.ACTIVE)
        accounts = (await s.execute(acc_q)).scalars().all()
        pu_q = scope_query(select(func.count(ParsedUser.id)), ParsedUser, user)
        parsed_total = (await s.execute(pu_q)).scalar() or 0
    return templates.TemplateResponse(request=request, name="inviter.html", context={
        "accounts": accounts, "parsed_total": parsed_total,
        "status": get_invite_status(), "msg": msg,
    })

@router.post("/start")
async def start(chat_link: str = Form(...), user_ids_text: str = Form(""),
                batch_size: int = Form(50), delay_sec: float = Form(15),
                delay_jitter: float = Form(5.0),
                micropause_every: int = Form(0),
                micropause_sec: float = Form(120.0),
                max_per_account_per_hour: int = Form(0),
                account_ids: list[int] = Form([])):
    ids = []
    for line in user_ids_text.strip().splitlines():
        line = line.strip()
        if line.isdigit():
            ids.append(int(line))
    if not ids:
        return RedirectResponse("/app/inviter/?msg=Введите+ID+пользователей", status_code=303)
    asyncio.create_task(run_inviting(
        chat_link, ids, account_ids or None, batch_size, delay_sec,
        delay_jitter=delay_jitter,
        micropause_every=micropause_every,
        micropause_sec=micropause_sec,
        max_per_account_per_hour=max_per_account_per_hour,
    ))
    return RedirectResponse(f"/app/inviter/?msg=Инвайтинг+запущен+({len(ids)}+чел.)", status_code=303)

@router.post("/pause")
async def pause():
    paused = pause_inviting()
    msg = "Пауза" if paused else "Продолжение"
    return RedirectResponse(f"/app/inviter/?msg={msg}", status_code=303)

@router.post("/stop")
async def stop():
    stop_inviting()
    return RedirectResponse("/app/inviter/?msg=Остановлен", status_code=303)

@router.get("/status")
async def status():
    return JSONResponse(get_invite_status())
