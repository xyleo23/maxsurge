"""Админ-панель: управление пользователями, аккаунтами, статистика, настройки."""
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from passlib.hash import bcrypt
from sqlalchemy import select, func, delete, update
from max_client.audit import log_audit

from db.models import (
    AuditLog, ErrorLog,
    SiteUser, UserPlan, Lead, MaxAccount, AccountStatus, SendLog,
    ParsedUser, ChatCatalog, Task, TaskStatus, UserFile, WarmingLog,
    Payment, PaymentStatus, async_session_factory,
)
from web.routes.auth_r import get_current_user

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


async def _require_admin(request: Request):
    user = await get_current_user(request)
    if not user or not user.is_superadmin:
        return None
    return user


# ── Dashboard ────────────────────────────────────────
@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    user = await _require_admin(request)
    if not user:
        return RedirectResponse("/app/", status_code=303)

    today = datetime.utcnow().replace(hour=0, minute=0, second=0)
    week_ago = today - timedelta(days=7)

    async with async_session_factory() as s:
        users_total = (await s.execute(select(func.count(SiteUser.id)))).scalar() or 0
        users_today = (await s.execute(select(func.count(SiteUser.id)).where(SiteUser.created_at >= today))).scalar() or 0
        users_active = (await s.execute(select(func.count(SiteUser.id)).where(SiteUser.is_active == True))).scalar() or 0

        leads_total = (await s.execute(select(func.count(Lead.id)))).scalar() or 0
        accounts_total = (await s.execute(select(func.count(MaxAccount.id)))).scalar() or 0
        accounts_active = (await s.execute(select(func.count(MaxAccount.id)).where(MaxAccount.status == AccountStatus.ACTIVE))).scalar() or 0

        sent_total = (await s.execute(select(func.count(SendLog.id)).where(SendLog.status == "sent"))).scalar() or 0
        sent_today = (await s.execute(select(func.count(SendLog.id)).where(SendLog.status == "sent", SendLog.sent_at >= today))).scalar() or 0

        tasks_total = (await s.execute(select(func.count(Task.id)))).scalar() or 0
        tasks_running = (await s.execute(select(func.count(Task.id)).where(Task.status == TaskStatus.RUNNING))).scalar() or 0

        parsed_total = (await s.execute(select(func.count(ParsedUser.id)))).scalar() or 0
        files_total = (await s.execute(select(func.count(UserFile.id)))).scalar() or 0
        chats_total = (await s.execute(select(func.count(ChatCatalog.id)))).scalar() or 0

        # Последние 10 пользователей
        recent_users = (await s.execute(select(SiteUser).order_by(SiteUser.created_at.desc()).limit(10))).scalars().all()

        # Charts: последние 30 дней
        month_ago = today - timedelta(days=30)

        signups_raw = (await s.execute(
            select(func.date(SiteUser.created_at), func.count(SiteUser.id))
            .where(SiteUser.created_at >= month_ago)
            .group_by(func.date(SiteUser.created_at))
            .order_by(func.date(SiteUser.created_at))
        )).all()
        signups_by_day = {str(r[0]): r[1] for r in signups_raw}

        payments_raw = (await s.execute(
            select(func.date(Payment.paid_at), func.count(Payment.id), func.sum(Payment.amount))
            .where(Payment.status == PaymentStatus.SUCCEEDED, Payment.paid_at >= month_ago)
            .group_by(func.date(Payment.paid_at))
            .order_by(func.date(Payment.paid_at))
        )).all()
        payments_by_day = {str(r[0]): {"count": r[1], "sum": float(r[2] or 0)} for r in payments_raw}

        # Суммарный доход
        total_revenue = (await s.execute(
            select(func.sum(Payment.amount)).where(Payment.status == PaymentStatus.SUCCEEDED)
        )).scalar() or 0
        month_revenue = (await s.execute(
            select(func.sum(Payment.amount)).where(
                Payment.status == PaymentStatus.SUCCEEDED,
                Payment.paid_at >= month_ago,
            )
        )).scalar() or 0

        # Распределение по планам
        plans_raw = (await s.execute(
            select(SiteUser.plan, func.count(SiteUser.id)).group_by(SiteUser.plan)
        )).all()
        plans_distribution = {r[0].value: r[1] for r in plans_raw}

        # Собрать даты за 30 дней
        chart_dates = []
        chart_signups = []
        chart_payments_count = []
        chart_payments_sum = []
        for i in range(30, -1, -1):
            d = (today - timedelta(days=i)).date()
            key = str(d)
            chart_dates.append(d.strftime("%d.%m"))
            chart_signups.append(signups_by_day.get(key, 0))
            chart_payments_count.append(payments_by_day.get(key, {"count": 0})["count"])
            chart_payments_sum.append(payments_by_day.get(key, {"sum": 0})["sum"])

    return templates.TemplateResponse(request=request, name="admin.html", context={
        "chart_dates": chart_dates,
        "chart_signups": chart_signups,
        "chart_payments_count": chart_payments_count,
        "chart_payments_sum": chart_payments_sum,
        "total_revenue": total_revenue,
        "month_revenue": month_revenue,
        "plans_distribution": plans_distribution,
        "user": user,
        "users_total": users_total, "users_today": users_today, "users_active": users_active,
        "leads_total": leads_total,
        "accounts_total": accounts_total, "accounts_active": accounts_active,
        "sent_total": sent_total, "sent_today": sent_today,
        "tasks_total": tasks_total, "tasks_running": tasks_running,
        "parsed_total": parsed_total, "files_total": files_total, "chats_total": chats_total,
        "recent_users": recent_users,
    })


# ── Users CRUD ────────────────────────────────────────
@router.get("/users", response_class=HTMLResponse)
async def admin_users(request: Request, msg: str = ""):
    user = await _require_admin(request)
    if not user:
        return RedirectResponse("/app/", status_code=303)

    async with async_session_factory() as s:
        users = (await s.execute(select(SiteUser).order_by(SiteUser.created_at.desc()))).scalars().all()

    return templates.TemplateResponse(request=request, name="admin_users.html", context={
        "user": user, "users": users, "msg": msg,
        "plans": [p.value for p in UserPlan],
    })


@router.post("/users/{user_id}/plan")
async def change_plan(user_id: int, plan: str = Form(...), request: Request = None):
    async with async_session_factory() as s:
        u = await s.get(SiteUser, user_id)
        if u:
            u.plan = UserPlan(plan)
            await s.commit()
    return RedirectResponse("/app/admin/users?msg=План+изменён", status_code=303)


@router.post("/users/{user_id}/toggle-active")
async def toggle_active(user_id: int):
    async with async_session_factory() as s:
        u = await s.get(SiteUser, user_id)
        if u and not u.is_superadmin:
            u.is_active = not u.is_active
            await s.commit()
    return RedirectResponse("/app/admin/users", status_code=303)


@router.post("/users/{user_id}/toggle-admin")
async def toggle_admin(user_id: int):
    async with async_session_factory() as s:
        u = await s.get(SiteUser, user_id)
        if u:
            u.is_superadmin = not u.is_superadmin
            await s.commit()
    return RedirectResponse("/app/admin/users", status_code=303)


@router.post("/users/{user_id}/delete")
async def delete_user(user_id: int):
    async with async_session_factory() as s:
        u = await s.get(SiteUser, user_id)
        if u and not u.is_superadmin:
            await s.delete(u)
            await s.commit()
    return RedirectResponse("/app/admin/users", status_code=303)


@router.post("/users/{user_id}/reset-password")
async def reset_password(user_id: int, new_password: str = Form(...)):
    async with async_session_factory() as s:
        u = await s.get(SiteUser, user_id)
        if u and len(new_password) >= 6:
            u.password_hash = bcrypt.using(rounds=12).hash(new_password)
            await s.commit()
    return RedirectResponse("/app/admin/users?msg=Пароль+сброшен", status_code=303)


# ── System ────────────────────────────────────────────
@router.post("/reset-counters")
async def reset_counters():
    async with async_session_factory() as s:
        await s.execute(update(MaxAccount).values(sent_today=0))
        await s.commit()
    return RedirectResponse("/app/admin/?msg=Счётчики+сброшены", status_code=303)


@router.post("/cleanup-logs")
async def cleanup_logs():
    cutoff = datetime.utcnow() - timedelta(days=30)
    async with async_session_factory() as s:
        await s.execute(delete(SendLog).where(SendLog.sent_at < cutoff))
        await s.execute(delete(WarmingLog).where(WarmingLog.created_at < cutoff))
        await s.commit()
    return RedirectResponse("/app/admin/?msg=Логи+очищены", status_code=303)


@router.get("/audit", response_class=HTMLResponse)
async def audit_page(
    request: Request,
    actor: str = "",
    action: str = "",
    days: int = 7,
    page: int = 1,
):
    user = await _require_admin(request)
    if not user or not user.is_superadmin:
        return RedirectResponse("/app/", status_code=303)

    from datetime import datetime as _dt, timedelta as _td
    per_page = 100
    page = max(1, page)
    since = _dt.utcnow() - _td(days=max(1, min(days, 90)))

    async with async_session_factory() as s:
        q = select(AuditLog).where(AuditLog.created_at >= since)
        if actor:
            q = q.where(AuditLog.actor_email.ilike(f"%{actor}%"))
        if action:
            q = q.where(AuditLog.action.ilike(f"%{action}%"))

        total = (await s.execute(
            select(func.count()).select_from(q.subquery())
        )).scalar() or 0

        entries = (await s.execute(
            q.order_by(AuditLog.created_at.desc())
             .offset((page - 1) * per_page)
             .limit(per_page)
        )).scalars().all()

        # Distinct actions for dropdown
        distinct_actions = (await s.execute(
            select(AuditLog.action).where(AuditLog.created_at >= since).distinct().limit(50)
        )).scalars().all()

    has_next = total > page * per_page
    return templates.TemplateResponse(
        request=request,
        name="admin_audit.html",
        context={
            "entries": entries,
            "total": total,
            "page": page,
            "per_page": per_page,
            "has_next": has_next,
            "filter_actor": actor,
            "filter_action": action,
            "filter_days": days,
            "distinct_actions": distinct_actions,
        },
    )


@router.get("/errors", response_class=HTMLResponse)
async def errors_page(request: Request):
    user = await _require_admin(request)
    if not user:
        return RedirectResponse("/app/", status_code=303)
    from datetime import datetime, timedelta
    since_24h = datetime.utcnow() - timedelta(hours=24)
    async with async_session_factory() as s:
        total = (await s.execute(select(func.count(ErrorLog.id)))).scalar() or 0
        last_24h = (await s.execute(select(func.count(ErrorLog.id)).where(ErrorLog.created_at >= since_24h))).scalar() or 0
        entries = (await s.execute(
            select(ErrorLog).order_by(ErrorLog.created_at.desc()).limit(500)
        )).scalars().all()
        top_types_rows = (await s.execute(
            select(ErrorLog.ex_type, func.count(ErrorLog.id)).where(ErrorLog.created_at >= since_24h).group_by(ErrorLog.ex_type).order_by(func.count(ErrorLog.id).desc()).limit(10)
        )).all()
    top_types = [(r[0], r[1]) for r in top_types_rows]
    return templates.TemplateResponse(
        request=request,
        name="admin_errors.html",
        context={"entries": entries, "total": total, "last_24h": last_24h, "top_types": top_types},
    )


@router.post("/users/bulk-plan")
async def bulk_plan(request: Request, user_ids: str = Form(""), plan: str = Form("trial")):
    """Mass change plan for selected users."""
    user = await _require_admin(request)
    if not user:
        return RedirectResponse("/app/admin/users", status_code=303)
    ids = [int(x.strip()) for x in user_ids.split(",") if x.strip().isdigit()]
    count = 0
    async with async_session_factory() as s:
        for uid in ids:
            u = await s.get(SiteUser, uid)
            if u:
                u.plan = UserPlan(plan)
                count += 1
        await s.commit()
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    await log_audit(user, "bulk_plan_change", "users", None, f"{count} users -> {plan}, ids={user_ids[:200]}", ip)
    return RedirectResponse(f"/app/admin/users?msg=Изменено+{count}+юзеров+на+{plan}", status_code=303)


@router.get("/users/export-csv")
async def export_users_csv(request: Request):
    """Export all users as CSV."""
    user = await _require_admin(request)
    if not user:
        return RedirectResponse("/app/admin/users", status_code=303)
    import csv, io
    from fastapi.responses import StreamingResponse
    async with async_session_factory() as s:
        users = (await s.execute(select(SiteUser).order_by(SiteUser.created_at.desc()))).scalars().all()
    def gen():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id","email","name","plan","is_active","is_superadmin","email_verified","created_at","last_login","plan_expires_at","ref_code","ref_balance"])
        yield buf.getvalue()
        for u in users:
            buf.seek(0); buf.truncate()
            w.writerow([u.id,u.email,u.name or "",u.plan.value,u.is_active,u.is_superadmin,u.email_verified,
                        u.created_at.strftime("%Y-%m-%d %H:%M") if u.created_at else "",
                        u.last_login.strftime("%Y-%m-%d %H:%M") if u.last_login else "",
                        str(u.plan_expires_at) if u.plan_expires_at else "",
                        u.ref_code or "",u.ref_balance])
            yield buf.getvalue()
    return StreamingResponse(gen(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=users_export.csv"})


@router.post("/users/bulk-toggle-active")
async def bulk_toggle(request: Request, user_ids: str = Form(""), active: bool = Form(True)):
    user = await _require_admin(request)
    if not user:
        return RedirectResponse("/app/admin/users", status_code=303)
    ids = [int(x.strip()) for x in user_ids.split(",") if x.strip().isdigit()]
    count = 0
    async with async_session_factory() as s:
        for uid in ids:
            u = await s.get(SiteUser, uid)
            if u:
                u.is_active = active
                count += 1
        await s.commit()
    action = "активированы" if active else "заблокированы"
    return RedirectResponse(f"/app/admin/users?msg={count}+юзеров+{action}", status_code=303)
