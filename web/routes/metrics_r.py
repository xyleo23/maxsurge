"""Prometheus-совместимый /metrics endpoint.

Экспортирует ключевые метрики в текстовом формате (не требует prometheus_client).
Защищён Basic-auth через ADMIN_EMAIL/ADMIN_PASSWORD из settings.

Пример скрейпа (prometheus.yml):
  - job_name: 'maxsurge'
    scrape_interval: 60s
    basic_auth:
      username: admin@maxsurge.ru
      password: <ADMIN_PASSWORD>
    static_configs:
      - targets: ['maxsurge.ru']
    scheme: https
    metrics_path: /metrics
"""
import base64
import time

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import func, select

from config import get_settings
from db.models import (
    async_session_factory,
    SiteUser, UserPlan,
    MaxAccount, AccountStatus,
    Lead, SendLog, Task, TaskStatus,
    Payment, PaymentStatus,
)

router = APIRouter()
settings = get_settings()


def _check_auth(request: Request) -> bool:
    """Simple Basic auth against ADMIN_EMAIL/ADMIN_PASSWORD."""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("basic "):
        return False
    try:
        decoded = base64.b64decode(auth[6:]).decode("utf-8")
        u, p = decoded.split(":", 1)
    except Exception:
        return False
    return u == settings.ADMIN_EMAIL and p == settings.ADMIN_PASSWORD


def _fmt(name: str, value, help_text: str, labels: dict | None = None, mtype: str = "gauge") -> str:
    label_str = ""
    if labels:
        label_str = "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}"
    return f"# HELP {name} {help_text}\n# TYPE {name} {mtype}\n{name}{label_str} {value}\n"


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(request: Request):
    if not _check_auth(request):
        return Response(
            "unauthorized",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="metrics"'},
        )

    lines = []
    async with async_session_factory() as s:
        # Users
        users_total = (await s.execute(select(func.count(SiteUser.id)))).scalar() or 0
        users_active = (await s.execute(select(func.count(SiteUser.id)).where(SiteUser.is_active == True))).scalar() or 0
        lines.append(_fmt("maxsurge_users_total", users_total, "Total registered users"))
        lines.append(_fmt("maxsurge_users_active", users_active, "Users with is_active=True"))

        # Users by plan
        plans = (await s.execute(select(SiteUser.plan, func.count(SiteUser.id)).group_by(SiteUser.plan))).all()
        for plan, n in plans:
            lines.append(_fmt("maxsurge_users_by_plan", n, "Users grouped by plan", {"plan": plan.value}))

        # MAX accounts
        accs_total = (await s.execute(select(func.count(MaxAccount.id)))).scalar() or 0
        accs_active = (await s.execute(select(func.count(MaxAccount.id)).where(MaxAccount.status == AccountStatus.ACTIVE))).scalar() or 0
        accs_blocked = (await s.execute(select(func.count(MaxAccount.id)).where(MaxAccount.status == AccountStatus.BLOCKED))).scalar() or 0
        lines.append(_fmt("maxsurge_accounts_total", accs_total, "Total MAX accounts"))
        lines.append(_fmt("maxsurge_accounts_active", accs_active, "MAX accounts in ACTIVE status"))
        lines.append(_fmt("maxsurge_accounts_blocked", accs_blocked, "MAX accounts in BLOCKED status"))

        # Leads
        leads_total = (await s.execute(select(func.count(Lead.id)))).scalar() or 0
        lines.append(_fmt("maxsurge_leads_total", leads_total, "Total leads across all users"))

        # Messages sent
        sent_total = (await s.execute(select(func.count(SendLog.id)).where(SendLog.status == "sent"))).scalar() or 0
        lines.append(_fmt("maxsurge_messages_sent_total", sent_total, "Total messages successfully sent", mtype="counter"))

        # Tasks
        tasks_running = (await s.execute(select(func.count(Task.id)).where(Task.status == TaskStatus.RUNNING))).scalar() or 0
        lines.append(_fmt("maxsurge_tasks_running", tasks_running, "Currently running tasks"))

        # Payments (revenue)
        rev_total = (await s.execute(select(func.sum(Payment.amount)).where(Payment.status == PaymentStatus.SUCCEEDED))).scalar() or 0
        payments_pending = (await s.execute(select(func.count(Payment.id)).where(Payment.status == PaymentStatus.PENDING))).scalar() or 0
        lines.append(_fmt("maxsurge_revenue_rub_total", float(rev_total), "Lifetime revenue in RUB", mtype="counter"))
        lines.append(_fmt("maxsurge_payments_pending", payments_pending, "Payments stuck in PENDING state"))

    # Process / uptime
    try:
        import os, resource
        rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024  # Linux reports in KB
        lines.append(_fmt("maxsurge_process_rss_bytes", rss_bytes, "Process RSS memory in bytes"))
    except Exception:
        pass

    lines.append(_fmt("maxsurge_scrape_timestamp_seconds", int(time.time()), "Unix time of this scrape"))

    return PlainTextResponse("".join(lines), media_type="text/plain; version=0.0.4")
