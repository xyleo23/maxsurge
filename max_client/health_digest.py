"""Daily digest и health-мониторинг.

Каждые 24ч собирает статистику по всем юзерам и шлёт владельцу сервиса в TG.
Раз в 5 минут проверяет disk space, memory, DB size — алерт если что-то не так.
"""
import asyncio
import os
import shutil
from datetime import datetime, timedelta

from loguru import logger
from sqlalchemy import select, func

from db.models import (
    SiteUser, Payment, PaymentStatus, Lead, SendLog, Task,
    async_session_factory,
)
from max_client.tg_notifier import notify_async


async def _safe_send(text: str):
    try:
        notify_async(text)
    except Exception as e:
        logger.warning("digest send failed: {}", e)


async def send_daily_digest():
    """Собрать и отправить суточную сводку владельцу сервиса."""
    try:
        since = datetime.utcnow() - timedelta(days=1)
        async with async_session_factory() as s:
            new_users = (await s.execute(
                select(func.count(SiteUser.id)).where(SiteUser.created_at >= since)
            )).scalar() or 0
            total_users = (await s.execute(select(func.count(SiteUser.id)))).scalar() or 0

            paid_payments = (await s.execute(
                select(Payment).where(
                    Payment.status == PaymentStatus.SUCCEEDED,
                    Payment.paid_at >= since,
                )
            )).scalars().all()
            revenue = sum(p.amount for p in paid_payments)
            payments_count = len(paid_payments)

            leads_added = (await s.execute(
                select(func.count(Lead.id)).where(Lead.created_at >= since)
            )).scalar() or 0

            messages_sent = (await s.execute(
                select(func.count(SendLog.id)).where(
                    SendLog.sent_at >= since, SendLog.status == "sent",
                )
            )).scalar() or 0

            tasks_done = (await s.execute(
                select(func.count(Task.id)).where(Task.finished_at >= since)
            )).scalar() or 0

        # Disk info
        try:
            du = shutil.disk_usage("/")
            disk_free_gb = du.free / 1024 / 1024 / 1024
            disk_pct = round(du.used / du.total * 100, 1)
        except Exception:
            disk_free_gb = 0.0
            disk_pct = 0.0

        try:
            db_size_mb = os.path.getsize("max_leadfinder.db") / 1024 / 1024
        except Exception:
            db_size_mb = 0.0

        text = (
            "📊 <b>Daily digest MaxSurge</b>\n\n"
            "<b>Пользователи:</b>\n"
            + f"• Новых за 24ч: <b>{new_users}</b>\n"
            + f"• Всего: <b>{total_users}</b>\n\n"
            "<b>Деньги:</b>\n"
            + f"• Платежей: <b>{payments_count}</b>\n"
            + f"• Выручка: <b>{revenue:.0f}₽</b>\n\n"
            "<b>Активность:</b>\n"
            + f"• Лидов: <b>{leads_added}</b>\n"
            + f"• Сообщений: <b>{messages_sent}</b>\n"
            + f"• Задач: <b>{tasks_done}</b>\n\n"
            "<b>Инфраструктура:</b>\n"
            + f"• Диск: <b>{disk_pct}%</b> ({disk_free_gb:.1f} GB свободно)\n"
            + f"• БД: <b>{db_size_mb:.1f} MB</b>\n"
        )
        await _safe_send(text)
        logger.info("[digest] sent daily digest")
    except Exception as e:
        logger.exception("[digest] failed: {}", e)


async def check_health():
    """Проверить disk/memory/DB каждые 5 минут, алертить при превышении порогов."""
    alerted = {}  # key -> last_alert_time
    while True:
        try:
            now = datetime.utcnow()

            # Disk
            du = shutil.disk_usage("/")
            pct = du.used / du.total * 100
            if pct > 90:
                last = alerted.get("disk")
                if not last or (now - last).total_seconds() > 3600:
                    await _safe_send(f"⚠️ <b>ALERT: диск забит</b>\n\nИспользовано: <b>{pct:.1f}%</b>\nСвободно: <b>{du.free / 1e9:.1f} GB</b>")
                    alerted["disk"] = now

            # DB size
            try:
                db_mb = os.path.getsize("max_leadfinder.db") / 1024 / 1024
                if db_mb > 1024:
                    last = alerted.get("db")
                    if not last or (now - last).total_seconds() > 86400:
                        await _safe_send(f"⚠️ <b>ALERT: БД растёт</b>\n\nРазмер: <b>{db_mb:.0f} MB</b>\nРекомендую бэкап и чистку старых send_logs")
                        alerted["db"] = now
            except Exception:
                pass

        except Exception as e:
            logger.warning("[health] check failed: {}", e)

        await asyncio.sleep(300)  # 5 мин


async def run_periodic_digest():
    """Каждые 24ч шлёт digest. Запускается из main startup."""
    while True:
        # Ждём до 09:00 МСК (06:00 UTC)
        now = datetime.utcnow()
        target = now.replace(hour=6, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        await send_daily_digest()



async def send_weekly_report():
    """Weekly admin report — запускается воскресеньями в 06:00 UTC."""
    try:
        since = datetime.utcnow() - timedelta(days=7)
        async with async_session_factory() as s:
            new_users = (await s.execute(
                select(func.count(SiteUser.id)).where(SiteUser.created_at >= since)
            )).scalar() or 0
            total_users = (await s.execute(select(func.count(SiteUser.id)))).scalar() or 0

            paid = (await s.execute(
                select(Payment).where(
                    Payment.status == PaymentStatus.SUCCEEDED,
                    Payment.paid_at >= since,
                )
            )).scalars().all()
            revenue = sum(p.amount for p in paid)
            top_plan = {}
            for p in paid:
                top_plan[p.plan.value] = top_plan.get(p.plan.value, 0) + 1

            leads_added = (await s.execute(
                select(func.count(Lead.id)).where(Lead.created_at >= since)
            )).scalar() or 0
            messages_sent = (await s.execute(
                select(func.count(SendLog.id)).where(
                    SendLog.sent_at >= since, SendLog.status == "sent",
                )
            )).scalar() or 0
            messages_failed = (await s.execute(
                select(func.count(SendLog.id)).where(
                    SendLog.sent_at >= since, SendLog.status == "failed",
                )
            )).scalar() or 0
            tasks_done = (await s.execute(
                select(func.count(Task.id)).where(Task.finished_at >= since)
            )).scalar() or 0

            # Error log summary
            from db.models import ErrorLog
            errors = (await s.execute(
                select(func.count(ErrorLog.id)).where(ErrorLog.created_at >= since)
            )).scalar() or 0

        import os as _os
        try:
            db_mb = _os.path.getsize("max_leadfinder.db") / 1024 / 1024
        except Exception:
            db_mb = 0

        success_rate = 0
        if messages_sent + messages_failed > 0:
            success_rate = round(messages_sent / (messages_sent + messages_failed) * 100, 1)

        lines = [
            "📊 <b>Weekly Report MaxSurge</b>",
            "",
            f"<b>Пользователи:</b> +{new_users} (всего {total_users})",
            f"<b>Выручка:</b> {revenue:.0f}₽ ({len(paid)} платежей)",
        ]
        if top_plan:
            lines.append("<b>Планы:</b> " + ", ".join(f"{k}×{v}" for k, v in top_plan.items()))
        lines += [
            "",
            "<b>Активность:</b>",
            f"• Лидов добавлено: {leads_added}",
            f"• Сообщений успешно: {messages_sent}",
            f"• Сообщений fail: {messages_failed} ({success_rate}% delivery)",
            f"• Задач завершено: {tasks_done}",
            "",
            "<b>Техника:</b>",
            f"• Ошибок 5xx: {errors}",
            f"• БД: {db_mb:.1f} MB",
        ]
        text = "\n".join(lines)
        await _safe_send(text)
        logger.info("[weekly] sent weekly report")
    except Exception as e:
        logger.exception("[weekly] failed: {}", e)


async def run_periodic_weekly():
    """Каждое воскресенье 07:00 UTC (10:00 МСК)."""
    while True:
        now = datetime.utcnow()
        # weekday: 0=Mon ... 6=Sun
        days_until_sunday = (6 - now.weekday()) % 7
        target = (now + timedelta(days=days_until_sunday)).replace(hour=7, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=7)
        await asyncio.sleep((target - now).total_seconds())
        await send_weekly_report()
