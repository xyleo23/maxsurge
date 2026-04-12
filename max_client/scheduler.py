"""Scheduler — проверяет Task.scheduled_at и запускает в нужное время.

Задачи со scheduled_at в будущем ждут. Когда время подошло,
broadcast_config (JSON) разворачивается в вызов sender.start_broadcast_background.
"""
import asyncio
import json
from datetime import datetime

from loguru import logger
from sqlalchemy import select

from db.models import Task, TaskStatus, async_session_factory


async def check_scheduled_tasks():
    """Проверить и запустить просроченные scheduled_at задачи."""
    async with async_session_factory() as s:
        now = datetime.utcnow()
        q = select(Task).where(
            Task.scheduled_at.isnot(None),
            Task.scheduled_at <= now,
            Task.status == TaskStatus.PENDING,
        )
        tasks = (await s.execute(q)).scalars().all()

    for task in tasks:
        try:
            config = json.loads(task.broadcast_config or "{}")
            template_id = config.get("template_id")
            if not template_id:
                logger.warning("[scheduler] task {} has no template_id", task.id)
                continue

            from max_client.sender import start_broadcast_background
            start_broadcast_background(
                template_id=template_id,
                limit=config.get("limit", 50),
                dry_run=config.get("dry_run", False),
                account_ids=config.get("account_ids"),
                target_type=config.get("target_type", "users"),
                typing_emulation=config.get("typing_emulation", True),
                template_b_id=config.get("template_b_id"),
            )

            async with async_session_factory() as s:
                t = await s.get(Task, task.id)
                if t:
                    t.status = TaskStatus.RUNNING
                    t.started_at = datetime.utcnow()
                    await s.commit()

            logger.info("[scheduler] fired task {} (scheduled_at={})", task.id, task.scheduled_at)

            # Notify user
            try:
                from max_client.tg_notifier import notify_user_async
                notify_user_async(
                    task.owner_id,
                    "⏰ <b>Запланированная рассылка запущена</b>\n\n" + task.name,
                    pref_field="notify_on_task_done",
                )
            except Exception:
                pass

        except Exception as e:
            logger.exception("[scheduler] error firing task {}: {}", task.id, e)


async def run_scheduler_loop():
    """Каждые 60с проверяет scheduled tasks."""
    logger.info("[scheduler] started (interval=60s)")
    while True:
        try:
            await check_scheduled_tasks()
        except Exception as e:
            logger.warning("[scheduler] loop error: {}", e)
        await asyncio.sleep(60)
