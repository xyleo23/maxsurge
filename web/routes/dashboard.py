"""Дашборд — статистика с изоляцией по пользователю."""
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, cast, Date

from db.models import NeuroCampaign, MaxBot, ChatGuard, Lead, LeadStatus, MaxAccount, AccountStatus, SendLog, Task, TaskStatus, MessageTemplate, async_session_factory
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


        # Chart data — last 14 days
        from datetime import date as _dt_date
        chart_days = 14
        chart_since = today - timedelta(days=chart_days)

        # Leads per day
        leads_per_day_q = (await s.execute(
            scope_query(
                select(func.date(Lead.created_at).label("d"), func.count(Lead.id)),
                Lead, user,
            ).where(Lead.created_at >= chart_since).group_by("d")
        )).all()
        leads_chart = {str(r[0]): r[1] for r in leads_per_day_q}

        # Messages per day
        msgs_per_day_q = (await s.execute(
            scope_query(
                select(func.date(SendLog.sent_at).label("d"), func.count(SendLog.id)),
                SendLog, user,
            ).where(SendLog.sent_at >= chart_since, SendLog.status == "sent").group_by("d")
        )).all()
        msgs_chart = {str(r[0]): r[1] for r in msgs_per_day_q}

        # Build labels array
        import json as _json
        chart_labels = []
        chart_leads_data = []
        chart_msgs_data = []
        for i in range(chart_days):
            d = (today + timedelta(days=i - chart_days + 1)).strftime("%Y-%m-%d")
            chart_labels.append(d[-5:])  # MM-DD
            chart_leads_data.append(leads_chart.get(d, 0))
            chart_msgs_data.append(msgs_chart.get(d, 0))

    # Лимиты тарифа
    limits = get_limits(user.plan) if user and not getattr(user, "is_superadmin", False) else {}
    plan_usage = {
        "accounts": {"current": accounts_total, "limit": limits.get("max_accounts", 0)},
        "leads": {"current": leads_total, "limit": limits.get("max_leads", 0)},
        "tasks": {"current": tasks_total, "limit": limits.get("max_tasks", 0)},
    }

    # P10: расширенный онбординг — 9 шагов
    async with async_session_factory() as s2:
        neuro_count = (await s2.execute(scope_query(select(func.count(NeuroCampaign.id)), NeuroCampaign, user))).scalar() or 0
        bots_count = (await s2.execute(scope_query(select(func.count(MaxBot.id)), MaxBot, user))).scalar() or 0
        guards_count = (await s2.execute(scope_query(select(func.count(ChatGuard.id)), ChatGuard, user))).scalar() or 0
    has_ai_key = bool(user and user.ai_api_key)
    has_paid_plan = user and user.plan.value in ("start", "basic", "pro", "lifetime")

    onboarding = [
        {"key": "account", "title": "Подключить MAX аккаунт", "done": accounts_total > 0, "url": "/app/accounts/"},
        {"key": "template", "title": "Создать шаблон сообщения", "done": templates_total > 0, "url": "/app/templates/"},
        {"key": "lead", "title": "Собрать лиды (парсер карт или импорт CSV)", "done": leads_total > 0, "url": "/app/extension/"},
        {"key": "send", "title": "Отправить первое сообщение", "done": sent_week > 0, "url": "/app/sender/"},
        {"key": "ai", "title": "Подключить AI ключ", "done": has_ai_key, "url": "/app/settings/"},
        {"key": "bot", "title": "Создать MAX бот (лид/бонус)", "done": bots_count > 0, "url": "/app/bots/"},
        {"key": "guard", "title": "Настроить стража чата", "done": guards_count > 0, "url": "/app/guard/"},
        {"key": "neurochat", "title": "Запустить нейрочаттинг", "done": neuro_count > 0, "url": "/app/neurochat/"},
        {"key": "pay", "title": "Оплатить тариф", "done": has_paid_plan, "url": "/app/billing/"},
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
        "chart_labels_json": _json.dumps(chart_labels),
        "chart_leads_json": _json.dumps(chart_leads_data),
        "chart_msgs_json": _json.dumps(chart_msgs_data),
        "is_admin": user and getattr(user, "is_superadmin", False),
    })
