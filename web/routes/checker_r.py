"""Роуты чекера номеров."""
import asyncio
from pathlib import Path
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from web.routes._scope import get_request_user, scope_query
from db.models import Lead, MaxAccount, AccountStatus, async_session_factory
from max_client.checker import run_phone_checker, get_check_status, stop_checker

router = APIRouter(prefix="/checker")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

_task: asyncio.Task | None = None

@router.get("/", response_class=HTMLResponse)
async def checker_page(request: Request, msg: str = ""):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        lwp_q = scope_query(select(func.count(Lead.id)), Lead, user).where(Lead.phone.isnot(None), Lead.phone != "", Lead.max_user_id.is_(None))
        leads_with_phone = (await s.execute(lwp_q)).scalar() or 0
        ll_q = scope_query(select(func.count(Lead.id)), Lead, user).where(Lead.max_user_id.isnot(None))
        leads_linked = (await s.execute(ll_q)).scalar() or 0
        acc_q = scope_query(select(MaxAccount), MaxAccount, user).where(MaxAccount.status == AccountStatus.ACTIVE)
        accounts = (await s.execute(acc_q)).scalars().all()
    return templates.TemplateResponse(request=request, name="checker.html", context={
        "leads_with_phone": leads_with_phone, "leads_linked": leads_linked,
        "accounts": accounts, "status": get_check_status(), "msg": msg,
    })

@router.post("/start")
async def start_check(limit: int = Form(20), phone: str = Form("")):
    global _task
    _task = asyncio.create_task(run_phone_checker(limit, phone or None))
    return RedirectResponse("/app/checker/?msg=Чекер+запущен", status_code=303)

@router.post("/stop")
async def stop():
    stop_checker()
    return RedirectResponse("/app/checker/?msg=Остановлен", status_code=303)

@router.get("/status")
async def status():
    return JSONResponse(get_check_status())
