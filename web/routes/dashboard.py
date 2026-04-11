"""Дашборд — статистика с изоляцией по пользователю."""
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func

from db.models import Lead, LeadStatus, MaxAccount, AccountStatus, SendLog, Task, TaskStatus, MessageTemplate, async_session_factory
from db.plan_limits import get_limits
from web.routes._scope import get_request_user, scope_query

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    user = await get_request_user(request)
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = today - timedelta(days=7)

    async with async_session_factory() as s:
        # Leads
        leads_total = (await s.execute(scope_query(select(func.count(Lead.id)), Lead, user))).scalar() or 0
        leads_new = (await s.execute(scope_query(select(func.count(Lead.id)), Lead, user).where(Lead.status == LeadStatus.NEW))).scalar() or 0
        leads_contacted = (await s.execute(scope_query(select(func.count(Lead.id)), Lead, user).where(Lead.status == LeadStatus.CONTACTED))).scalar() or 0

        # Send logs
        sent_today = (await s.execute(
            scope_query(select(func.count(SendLog.id)), SendLog, user).where(SendLog.sent_at >= today, SendLog.status == "sent")
        )).scalar() or 0
        sent_week = (await s.execute(
            scope_query(select(func.count(SendLog.id)), SendLog, user).where(SendLog.sent_at >= week_ago, SendLog.status == "sent")
        )).scalar() or 0

        # Accounts
        accounts_active = (await s.execute(
            scope_query(select(func.count(MaxAccount.id)), MaxAccount, user).where(MaxAccount.status == AccountStatus.ACTIVE)
        )).scalar() or 0
        accounts_blocked = (await s.execute(
            scope_query(select(func.count(MaxAccount.id)), MaxAccount, user).where(MaxAccount.status == AccountStatus.BLOCKED)
        )).scalar() or 0
        accounts_total = (await s.execute(scope_query(select(func.count(MaxAccount.id)), MaxAccount, user))).scalar() or 0

        # Tasks
        tasks_total = (await s.execute(scope_query(select(func.count(Task.id)), Task, user))).scalar() or 0

        # Templates (для онбординга)
        templates_total = (await s.execute(scope_query(select(func.count(MessageTemplate.id)), MessageTemplate, user))).scalar() or 0
        tasks_running = (await s.execute(
            scope_query(select(func.count(Task.id)), Task, user).where(Task.status == TaskStatus.RUNNING)
        )).scalar() or 0

        # Recent logs
        recent_logs = (await s.execute(
            scope_query(select(SendLog), SendLog, user).order_by(SendLog.sent_at.desc()).limit(10)
        )).scalars().all()

        # Status stats
        status_stats = (await s.execute(
            scope_query(select(Lead.status, func.count(Lead.id)), Lead, user).group_by(Lead.status)
        )).all()

    # Лимиты тарифа
    limits = get_limits(user.plan) if user and not getattr(user, "is_superadmin", False) else {}
    plan_usage = {
        "accounts": {"current": accounts_total, "limit": limits.get("max_accounts", 0)},
        "leads": {"current": leads_total, "limit": limits.get("max_leads", 0)},
        "tasks": {"current": tasks_total, "limit": limits.get("max_tasks", 0)},
    }

    # Onboarding шаги
    onboarding = [
        {"key": "account", "title": "Добавить MAX аккаунт", "done": accounts_total > 0, "url": "/app/accounts/"},
        {"key": "lead", "title": "Собрать лиды из 2GIS", "done": leads_total > 0, "url": "/app/scraper/"},
        {"key": "template", "title": "Создать шаблон сообщения", "done": templates_total > 0, "url": "/app/templates/"},
        {"key": "task", "title": "Запустить первую задачу", "done": tasks_total > 0, "url": "/app/tasks/"},
        {"key": "send", "title": "Отправить первое сообщение", "done": sent_week > 0, "url": "/app/sender/"},
    ]
    onboarding_done = sum(1 for o in onboarding if o["done"])
    show_onboarding = onboarding_done < len(onboarding) and not getattr(user, "is_superadmin", False)

    return templates.TemplateResponse(request=request, name="dashboard.html", context={
        "user": user,
        "onboarding": onboarding,
        "onboarding_done": onboarding_done,
        "onboarding_total": len(onboarding),
        "show_onboarding": show_onboarding,
        "leads_total": leads_total,
        "leads_new": leads_new,
        "leads_contacted": leads_contacted,
        "sent_today": sent_today,
        "sent_week": sent_week,
        "accounts_active": accounts_active,
        "accounts_blocked": accounts_blocked,
        "tasks_total": tasks_total,
        "tasks_running": tasks_running,
        "recent_logs": recent_logs,
        "status_stats": {str(r[0].value if hasattr(r[0], 'value') else r[0]): r[1] for r in status_stats},
        "plan_usage": plan_usage,
        "is_admin": user and getattr(user, "is_superadmin", False),
    })
