"""Фоновый проверщик истекших подписок."""
import asyncio
from datetime import datetime

from loguru import logger
from sqlalchemy import select, and_

from max_client.tg_notifier import on_subscription_expired
from db.models import SiteUser, UserPlan, async_session_factory


async def check_expired_subscriptions():
    """Проверяет всех юзеров и откатывает истекшие подписки на trial."""
    now = datetime.utcnow()
    async with async_session_factory() as s:
        # Находим всех у кого закончилась подписка (не trial и не lifetime)
        users = (await s.execute(
            select(SiteUser).where(
                and_(
                    SiteUser.plan_expires_at.isnot(None),
                    SiteUser.plan_expires_at < now,
                    SiteUser.plan.notin_([UserPlan.TRIAL, UserPlan.LIFETIME]),
                )
            )
        )).scalars().all()

        for user in users:
            old_plan = user.plan.value
            logger.info(
                "Подписка {} истекла ({} -> TRIAL)",
                user.email, old_plan
            )
            on_subscription_expired(user.email, old_plan)
            user.plan = UserPlan.TRIAL
            user.plan_expires_at = None

        if users:
            await s.commit()
            logger.info("Откатили {} истекших подписок на TRIAL", len(users))
        return len(users)


async def run_periodic_check(interval_sec: int = 3600):
    """Запускает проверку каждый час."""
    logger.info("Subscription checker запущен (интервал: {} сек)", interval_sec)
    while True:
        try:
            await check_expired_subscriptions()
        except Exception as e:
            logger.error("Ошибка в subscription checker: {}", e)
        await asyncio.sleep(interval_sec)
