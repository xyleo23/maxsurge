"""Hourly MAX account health check.

Проходит по всем аккаунтам, пытается восстановить сессию.
Если не удалось — логирует и уведомляет владельца через tg_notifier.
"""
import asyncio
from datetime import datetime

from loguru import logger
from sqlalchemy import select

from db.models import MaxAccount, AccountStatus, SiteUser, async_session_factory


async def check_all_accounts() -> dict:
    """Прогнать healthcheck по всем аккаунтам (не PENDING_AUTH).

    Returns stats dict: {checked, alive, dead, notified}.
    """
    from max_client.account import account_manager

    stats = {"checked": 0, "alive": 0, "dead": 0, "notified": 0}

    async with async_session_factory() as s:
        accs = (await s.execute(
            select(MaxAccount).where(
                MaxAccount.status != AccountStatus.PENDING_AUTH,
                MaxAccount.owner_id.isnot(None),
            )
        )).scalars().all()

    for acc in accs:
        stats["checked"] += 1
        try:
            client = await account_manager.restore_session(acc.phone)
            if client:
                stats["alive"] += 1
                # Auto-heal: if was marked BLOCKED but now responds — restore ACTIVE
                if acc.status == AccountStatus.BLOCKED:
                    async with async_session_factory() as s:
                        a = await s.get(MaxAccount, acc.id)
                        if a:
                            a.status = AccountStatus.ACTIVE
                            await s.commit()
                    logger.info("[health] account {} healed (BLOCKED -> ACTIVE)", acc.phone)
                continue
            raise Exception("restore_failed")
        except Exception as e:
            stats["dead"] += 1
            err = str(e)[:200]
            logger.warning("[health] account {} dead: {}", acc.phone, err)

            # Mark BLOCKED if not already
            if acc.status != AccountStatus.BLOCKED:
                async with async_session_factory() as s:
                    a = await s.get(MaxAccount, acc.id)
                    if a:
                        a.status = AccountStatus.BLOCKED
                        await s.commit()

                # Notify owner once (on transition ACTIVE -> BLOCKED)
                try:
                    from max_client.tg_notifier import notify_user_async
                    notify_user_async(
                        acc.owner_id,
                        f"⚠️ Аккаунт <b>{acc.phone}</b> недоступен.\n\n"
                        f"Причина: <code>{err[:100]}</code>\n\n"
                        f"Переподключите аккаунт на /app/accounts/",
                        pref_field="notify_on_account_block",
                    )
                    stats["notified"] += 1
                except Exception:
                    pass

    logger.info("[health] accounts check done: {}", stats)
    return stats


async def run_periodic_account_health(interval_sec: int = 3600):
    """Запускает healthcheck каждый час."""
    logger.info("Account health check запущен (интервал: {} сек)", interval_sec)
    # small initial delay so we don't hit MAX immediately on startup
    await asyncio.sleep(120)
    while True:
        try:
            await check_all_accounts()
        except Exception as e:
            logger.error("Ошибка в account health check: {}", e)
        await asyncio.sleep(interval_sec)
