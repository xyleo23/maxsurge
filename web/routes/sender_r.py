"""Управление рассылкой v2: пауза, чаты, эмуляция набора."""
from pathlib import Path
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from web.routes._scope import get_request_user, scope_query
from db.models import MessageTemplate, MaxAccount, AccountStatus, Lead, LeadStatus, ChatCatalog, async_session_factory
from max_client.sender import start_broadcast_background, stop_broadcast, pause_broadcast, get_broadcast_status

router = APIRouter(prefix="/sender")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

@router.get("/", response_class=HTMLResponse)
async def sender_page(request: Request, msg: str = ""):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        tmpl_q = scope_query(select(MessageTemplate), MessageTemplate, user).where(MessageTemplate.is_active == True)
        tmpls = (await s.execute(tmpl_q)).scalars().all()
        acc_q = scope_query(select(MaxAccount), MaxAccount, user).where(MaxAccount.status == AccountStatus.ACTIVE)
        accounts = (await s.execute(acc_q)).scalars().all()
        leads_q = scope_query(select(func.count(Lead.id)), Lead, user).where(Lead.status == LeadStatus.NEW, Lead.max_user_id.isnot(None))
        leads_new = (await s.execute(leads_q)).scalar() or 0
        chats_q = scope_query(select(func.count(ChatCatalog.id)), ChatCatalog, user).where(ChatCatalog.chat_id.isnot(None))
        chats_count = (await s.execute(chats_q)).scalar() or 0
    return templates.TemplateResponse(request=request, name="sender.html", context={
        "templates": tmpls, "accounts": accounts, "leads_new_count": leads_new,
        "chats_count": chats_count, "status": get_broadcast_status(), "msg": msg,
    })

@router.post("/start")
async def start_broadcast(template_id: int = Form(...), limit: int = Form(50),
                           dry_run: bool = Form(False), account_ids: list[int] = Form([]),
                           target_type: str = Form("users"), typing_emulation: bool = Form(True),
                           template_b_id: int = Form(0)):
    # Scheduled?
    if schedule and scheduled_at:
        from datetime import datetime as _dt
        import json as _json
        try:
            sched_time = _dt.fromisoformat(scheduled_at)
        except Exception:
            return RedirectResponse("/app/sender/?msg=Неверный+формат+даты", status_code=303)
        from db.models import Task, TaskType, TaskStatus, async_session_factory as _asf
        user = await get_request_user(request) if hasattr(request, "state") else None
        async with _asf() as _s:
            _s.add(Task(
                name=f"Рассылка (запланировано на {scheduled_at})",
                task_type=TaskType.BROADCAST,
                status=TaskStatus.PENDING,
                owner_id=user.id if user else None,
                scheduled_at=sched_time,
                broadcast_config=_json.dumps({
                    "template_id": template_id,
                    "limit": limit,
                    "dry_run": dry_run,
                    "target_type": target_type,
                    "typing_emulation": typing_emulation,
                    "template_b_id": template_b_id or None,
                    "account_ids": account_ids or None,
                }),
            ))
            await _s.commit()
        return RedirectResponse(f"/app/sender/?msg=Рассылка+запланирована+на+{scheduled_at}", status_code=303)

    try:
        start_broadcast_background(template_id, limit, dry_run, account_ids or None, target_type, typing_emulation,
                                    template_b_id=(template_b_id or None))
        return RedirectResponse("/app/sender/?msg=Рассылка+запущена", status_code=303)
    except RuntimeError as e:
        return RedirectResponse(f"/app/sender/?msg={str(e)}", status_code=303)

@router.post("/pause")
async def pause():
    paused = pause_broadcast()
    msg = "Пауза" if paused else "Продолжение"
    return RedirectResponse(f"/app/sender/?msg={msg}", status_code=303)

@router.post("/stop")
async def stop():
    stop_broadcast()
    return RedirectResponse("/app/sender/?msg=Остановлена", status_code=303)

@router.get("/status")
async def broadcast_status():
    return JSONResponse(get_broadcast_status())
