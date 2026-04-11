"""Единые системные логи для пользователя — срез активности по всем модулям."""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc

from db.models import (
    SendLog, Task, Lead, MaxAccount, ChatGuard, GuardEvent,
    NeuroCampaign, NeuroChatMessage, MaxBot, MaxBotLead,
    async_session_factory,
)
from web.routes._scope import scope_query
from web.routes.auth_r import get_current_user

router = APIRouter(prefix="/logs")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def page(request: Request, tab: str = "broadcast"):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    items = []
    async with async_session_factory() as s:
        if tab == "broadcast":
            q = scope_query(select(SendLog), SendLog, user).order_by(desc(SendLog.sent_at)).limit(500)
            items = (await s.execute(q)).scalars().all()
        elif tab == "tasks":
            q = scope_query(select(Task), Task, user).order_by(desc(Task.created_at)).limit(200)
            items = (await s.execute(q)).scalars().all()
        elif tab == "leads":
            q = scope_query(select(Lead), Lead, user).order_by(desc(Lead.created_at)).limit(500)
            items = (await s.execute(q)).scalars().all()
        elif tab == "guard":
            # Events принадлежат ChatGuard, который owner_id=user
            g_ids_q = scope_query(select(ChatGuard.id), ChatGuard, user)
            g_ids = [r for r in (await s.execute(g_ids_q)).scalars().all()]
            if g_ids:
                q = select(GuardEvent).where(GuardEvent.guard_id.in_(g_ids)).order_by(desc(GuardEvent.created_at)).limit(500)
                items = (await s.execute(q)).scalars().all()
        elif tab == "neurochat":
            c_ids_q = scope_query(select(NeuroCampaign.id), NeuroCampaign, user)
            c_ids = [r for r in (await s.execute(c_ids_q)).scalars().all()]
            if c_ids:
                q = select(NeuroChatMessage).where(NeuroChatMessage.campaign_id.in_(c_ids)).order_by(desc(NeuroChatMessage.created_at)).limit(500)
                items = (await s.execute(q)).scalars().all()
        elif tab == "bots":
            b_ids_q = scope_query(select(MaxBot.id), MaxBot, user)
            b_ids = [r for r in (await s.execute(b_ids_q)).scalars().all()]
            if b_ids:
                q = select(MaxBotLead).where(MaxBotLead.bot_id.in_(b_ids)).order_by(desc(MaxBotLead.created_at)).limit(500)
                items = (await s.execute(q)).scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="logs.html",
        context={"items": items, "tab": tab},
    )
