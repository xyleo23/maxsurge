"""Post scheduler — публикует запланированные посты в каналы/группы MAX."""
import asyncio
from datetime import datetime

from loguru import logger
from sqlalchemy import select

from db.models import ScheduledPost, PostStatus, async_session_factory
from max_client.account import account_manager


async def check_and_post_due() -> int:
    """Взять все ScheduledPost со scheduled_at <= now и status=pending, опубликовать."""
    from max_client.ops import send_message
    now = datetime.utcnow()
    async with async_session_factory() as s:
        q = select(ScheduledPost).where(
            ScheduledPost.status == PostStatus.PENDING.value,
            ScheduledPost.scheduled_at <= now,
        ).order_by(ScheduledPost.scheduled_at)
        due = (await s.execute(q)).scalars().all()

    posted = 0
    for post in due:
        try:
            # Pick client: prefer the account linked to the post, fallback to any active
            if post.account_id:
                async with async_session_factory() as s:
                    from db.models import MaxAccount
                    acc = await s.get(MaxAccount, post.account_id)
                client = await account_manager.get_client(acc.phone) if acc else None
            else:
                pairs = await account_manager.get_all_active_clients()
                client = pairs[0][1] if pairs else None

            if not client:
                raise RuntimeError("no active client available")

            await send_message(client, chat_id=post.chat_id, text=post.body)

            async with async_session_factory() as s:
                p = await s.get(ScheduledPost, post.id)
                if p:
                    p.status = PostStatus.POSTED.value
                    p.posted_at = datetime.utcnow()
                    await s.commit()
            posted += 1
            logger.info("[post-sched] posted {} to chat {}", post.id, post.chat_id)
        except Exception as e:
            async with async_session_factory() as s:
                p = await s.get(ScheduledPost, post.id)
                if p:
                    p.status = PostStatus.FAILED.value
                    p.error = str(e)[:500]
                    await s.commit()
            logger.warning("[post-sched] failed {} chat={}: {}", post.id, post.chat_id, e)

    return posted


async def run_post_scheduler_loop(interval_sec: int = 60):
    logger.info("Post scheduler started (interval={} sec)", interval_sec)
    await asyncio.sleep(30)  # let app finish warming up
    while True:
        try:
            n = await check_and_post_due()
            if n > 0:
                logger.info("[post-sched] posted {} posts", n)
        except Exception as e:
            logger.error("[post-sched] loop error: {}", e)
        await asyncio.sleep(interval_sec)
