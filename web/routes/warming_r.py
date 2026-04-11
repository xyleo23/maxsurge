"""Роуты прогрева аккаунтов."""
import asyncio
from pathlib import Path
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from web.routes._scope import get_request_user, scope_query
from db.models import MaxAccount, AccountStatus, WarmingLog, async_session_factory
from max_client.warmer import run_warming, get_warm_status, stop_warming

router = APIRouter(prefix="/warming")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

_task: asyncio.Task | None = None

@router.get("/", response_class=HTMLResponse)
async def warming_page(request: Request, msg: str = ""):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        acc_q = scope_query(select(MaxAccount), MaxAccount, user).where(MaxAccount.status == AccountStatus.ACTIVE)
        accounts = (await s.execute(acc_q)).scalars().all()
        wl_q = scope_query(select(func.count(WarmingLog.id)), WarmingLog, user)
        total_actions = (await s.execute(wl_q)).scalar() or 0
    return templates.TemplateResponse(request=request, name="warming.html", context={
        "accounts": accounts, "total_actions": total_actions,
        "status": get_warm_status(), "msg": msg,
    })

@router.post("/start")
async def start_warming(actions_per_account: int = Form(10), channels: str = Form(""), account_ids: list[int] = Form([])):
    global _task
    ch_list = [c.strip() for c in channels.split(",") if c.strip()] or None
    _task = asyncio.create_task(run_warming(account_ids or None, actions_per_account, ch_list))
    return RedirectResponse("/app/warming/?msg=Прогрев+запущен", status_code=303)

@router.post("/stop")
async def stop():
    stop_warming()
    return RedirectResponse("/app/warming/?msg=Остановлен", status_code=303)

@router.get("/status")
async def status():
    return JSONResponse(get_warm_status())
