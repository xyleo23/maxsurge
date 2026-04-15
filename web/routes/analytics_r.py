"""Аналитика и статистика."""
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, cast, Date
from web.routes._scope import get_request_user, scope_query
from db.models import Lead, LeadStatus, SendLog, MaxAccount, ParsedUser, ChatCatalog, WarmingLog, async_session_factory

router = APIRouter(prefix="/analytics")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

@router.get("/", response_class=HTMLResponse)
async def analytics_page(request: Request):
    user = await get_request_user(request)
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    async with async_session_factory() as s:
        # Общая статистика
        leads_total = (await s.execute(select(func.count(Lead.id)))).scalar() or 0
        leads_with_max = (await s.execute(scope_query(select(func.count(Lead.id)), Lead, user).where(Lead.max_user_id.isnot(None)))).scalar() or 0
        parsed_users = (await s.execute(select(func.count(ParsedUser.id)))).scalar() or 0
        chats_catalog = (await s.execute(select(func.count(ChatCatalog.id)))).scalar() or 0

        # Отправки
        sent_total = (await s.execute(scope_query(select(func.count(SendLog.id)), SendLog, user).where(SendLog.status == "sent"))).scalar() or 0
        sent_today = (await s.execute(scope_query(select(func.count(SendLog.id)), SendLog, user).where(SendLog.status == "sent", SendLog.sent_at >= today))).scalar() or 0
        sent_week = (await s.execute(scope_query(select(func.count(SendLog.id)), SendLog, user).where(SendLog.status == "sent", SendLog.sent_at >= week_ago))).scalar() or 0
        failed_total = (await s.execute(scope_query(select(func.count(SendLog.id)), SendLog, user).where(SendLog.status == "failed"))).scalar() or 0

        # Отправки по дням за месяц
        daily_sends = (await s.execute(
            scope_query(select(func.date(SendLog.sent_at), func.count(SendLog.id)), SendLog, user)
            .where(SendLog.sent_at >= month_ago)
            .group_by(func.date(SendLog.sent_at))
            .order_by(func.date(SendLog.sent_at))
        )).all()

        # Конверсия по статусам лидов
        status_stats = (await s.execute(
            scope_query(select(Lead.status, func.count(Lead.id)), Lead, user).group_by(Lead.status)
        )).all()

        # Топ шаблонов
        template_stats = (await s.execute(
            scope_query(select(SendLog.template_id, func.count(SendLog.id).label("cnt")), SendLog, user)
            .where(SendLog.status == "sent")
            .group_by(SendLog.template_id)
            .order_by(func.count(SendLog.id).desc())
            .limit(5)
        )).all()

        # Прогрев
        warming_total = (await s.execute(select(func.count(WarmingLog.id)))).scalar() or 0

    conversion_rate = round(leads_with_max / leads_total * 100, 1) if leads_total > 0 else 0
    success_rate = round(sent_total / (sent_total + failed_total) * 100, 1) if (sent_total + failed_total) > 0 else 0

    return templates.TemplateResponse(request=request, name="analytics.html", context={
        "leads_total": leads_total, "leads_with_max": leads_with_max,
        "parsed_users": parsed_users, "chats_catalog": chats_catalog,
        "sent_total": sent_total, "sent_today": sent_today, "sent_week": sent_week,
        "failed_total": failed_total, "conversion_rate": conversion_rate,
        "success_rate": success_rate, "warming_total": warming_total,
        "daily_sends": [(str(d[0]), d[1]) for d in daily_sends],
        "status_stats": {str(r[0].value if hasattr(r[0], "value") else r[0]): r[1] for r in status_stats},
        "template_stats": template_stats,
    })

@router.get("/data")
async def analytics_data(request: Request):
    """JSON API для графиков."""
    user = await get_request_user(request)
    month_ago = datetime.utcnow() - timedelta(days=30)
    async with async_session_factory() as s:
        daily = (await s.execute(
            scope_query(select(func.date(SendLog.sent_at), func.count(SendLog.id)), SendLog, user)
            .where(SendLog.sent_at >= month_ago)
            .group_by(func.date(SendLog.sent_at))
            .order_by(func.date(SendLog.sent_at))
        )).all()
    return JSONResponse({"daily_sends": [[str(d[0]), d[1]] for d in daily]})
