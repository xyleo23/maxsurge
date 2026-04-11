"""Роуты управления профилями."""
import asyncio
from pathlib import Path
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from web.routes._scope import get_request_user, scope_query
from db.models import MaxAccount, AccountStatus, async_session_factory
from max_client.profile_manager import mass_update_profiles, get_profile_status

router = APIRouter(prefix="/profiles")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

@router.get("/", response_class=HTMLResponse)
async def profiles_page(request: Request, msg: str = ""):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        acc_q = scope_query(select(MaxAccount), MaxAccount, user).where(MaxAccount.status == AccountStatus.ACTIVE)
        accounts = (await s.execute(acc_q)).scalars().all()
    return templates.TemplateResponse(request=request, name="profiles.html", context={
        "accounts": accounts, "status": get_profile_status(), "msg": msg,
    })

@router.post("/update")
async def update_profiles(
    first_names: str = Form(""), last_names: str = Form(""), bio: str = Form(""),
    hide_online: bool = Form(False), findable_by_phone: bool = Form(True),
    allow_invites: bool = Form(True), account_ids: list[int] = Form([]),
):
    fn = [n.strip() for n in first_names.strip().splitlines() if n.strip()] or None
    ln = [n.strip() for n in last_names.strip().splitlines() if n.strip()] or None
    asyncio.create_task(mass_update_profiles(
        account_ids or None, fn, ln, bio or None,
        hide_online, findable_by_phone, allow_invites,
    ))
    return RedirectResponse("/app/profiles/?msg=Обновление+запущено", status_code=303)

@router.get("/status")
async def status():
    return JSONResponse(get_profile_status())
