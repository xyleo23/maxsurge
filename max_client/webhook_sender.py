"""User webhook dispatcher — fire-and-forget POST to user.webhook_url on events."""
import asyncio
import json
from datetime import datetime

import httpx
from loguru import logger

from db.models import SiteUser, async_session_factory


async def send_webhook(user_id: int, event: str, data: dict):
    """POST {event, data, timestamp} to user's webhook_url if configured."""
    async with async_session_factory() as s:
        user = await s.get(SiteUser, user_id)
    if not user or not user.webhook_url:
        return
    payload = {
        "event": event,
        "data": data,
        "timestamp": datetime.utcnow().isoformat(),
        "user_id": user_id,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                user.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json", "User-Agent": "MaxSurge-Webhook/1.0"},
            )
            logger.debug("[webhook] {} → {} status={}", event, user.webhook_url, r.status_code)
    except Exception as e:
        logger.warning("[webhook] {} failed for user {}: {}", event, user_id, e)


def webhook_async(user_id: int, event: str, data: dict):
    """Fire-and-forget wrapper."""
    try:
        asyncio.create_task(send_webhook(user_id, event, data))
    except Exception:
        pass
