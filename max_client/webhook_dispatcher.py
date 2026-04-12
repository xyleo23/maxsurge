"""Webhook dispatcher — отправка POST-запросов при событиях MaxSurge.

Использование из любого модуля (sender.py, parser.py, etc.):

    from max_client.webhook_dispatcher import dispatch_webhook

    await dispatch_webhook(
        user_id=user.id,
        event="message_sent",
        payload={"contact_id": 123, "status": "delivered", "timestamp": "..."}
    )

Dispatcher сам найдёт все активные webhook-эндпоинты пользователя,
подпишет payload HMAC-SHA256 и отправит с retry (3 попытки: 5/30/300 сек).
"""
import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime

import httpx
from loguru import logger
from sqlalchemy import and_, select

from db.models import async_session_factory as asf
from db.models_webhook import WebhookEndpoint, WebhookLog


# Retry delays (seconds)
RETRY_DELAYS = [5, 30, 300]


def _sign_payload(payload_bytes: bytes, secret: str) -> str:
    """HMAC-SHA256 подпись payload."""
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


async def _send_one(
    client: httpx.AsyncClient,
    endpoint: WebhookEndpoint,
    event: str,
    payload: dict,
) -> tuple[bool, int | None, float | None, str | None]:
    """Одна попытка отправки. Возвращает (success, status_code, response_ms, error)."""
    body = json.dumps({
        "event": event,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "data": payload,
    }, ensure_ascii=False, default=str)
    body_bytes = body.encode("utf-8")
    signature = _sign_payload(body_bytes, endpoint.secret)

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "X-MaxSurge-Event": event,
        "X-MaxSurge-Signature": f"sha256={signature}",
        "User-Agent": "MaxSurge-Webhook/1.0",
    }

    t0 = time.monotonic()
    try:
        resp = await client.post(endpoint.url, content=body_bytes, headers=headers, timeout=15.0)
        ms = round((time.monotonic() - t0) * 1000, 1)
        ok = 200 <= resp.status_code < 300
        return ok, resp.status_code, ms, None if ok else f"HTTP {resp.status_code}"
    except Exception as e:
        ms = round((time.monotonic() - t0) * 1000, 1)
        return False, None, ms, str(e)[:500]


async def _deliver(endpoint: WebhookEndpoint, event: str, payload: dict) -> None:
    """Доставка с retry логикой для одного endpoint."""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for attempt, delay in enumerate(RETRY_DELAYS, start=1):
            ok, code, ms, error = await _send_one(client, endpoint, event, payload)

            # Log attempt
            try:
                async with asf() as s:
                    s.add(WebhookLog(
                        endpoint_id=endpoint.id,
                        event_type=event,
                        payload_preview=json.dumps(payload, ensure_ascii=False, default=str)[:500],
                        status_code=code,
                        response_ms=ms,
                        success=ok,
                        error=error,
                        attempt=attempt,
                    ))
                    if ok:
                        ep = await s.get(WebhookEndpoint, endpoint.id)
                        if ep:
                            ep.last_triggered_at = datetime.utcnow()
                            ep.fail_count = 0
                    else:
                        ep = await s.get(WebhookEndpoint, endpoint.id)
                        if ep:
                            ep.fail_count = (ep.fail_count or 0) + 1
                    await s.commit()
            except Exception as le:
                logger.warning("webhook log write failed: {}", le)

            if ok:
                logger.debug("[webhook] delivered event={} to endpoint_id={} in {}ms", event, endpoint.id, ms)
                return

            # Не последняя попытка — ждём перед retry
            if attempt < len(RETRY_DELAYS):
                logger.warning("[webhook] attempt {}/{} failed for endpoint_id={}: {} — retry in {}s",
                               attempt, len(RETRY_DELAYS), endpoint.id, error, delay)
                await asyncio.sleep(delay)

        logger.error("[webhook] all {} attempts failed for endpoint_id={} event={}", len(RETRY_DELAYS), endpoint.id, event)


async def dispatch_webhook(user_id: int, event: str, payload: dict) -> int:
    """Найти все активные webhook-эндпоинты пользователя и доставить событие.

    Args:
        user_id: ID пользователя (SiteUser.id)
        event: тип события ("message_sent", "lead_collected", etc.)
        payload: произвольный dict с данными события

    Returns:
        Количество эндпоинтов, в которые отправлена доставка (не гарантирует успех — retry в фоне).
    """
    try:
        async with asf() as s:
            result = await s.execute(
                select(WebhookEndpoint).where(
                    and_(
                        WebhookEndpoint.owner_id == user_id,
                        WebhookEndpoint.active == True,  # noqa: E712
                    )
                )
            )
            endpoints = result.scalars().all()
    except Exception as e:
        logger.warning("dispatch_webhook: failed to fetch endpoints for user_id={}: {}", user_id, e)
        return 0

    if not endpoints:
        return 0

    # Фильтруем по событиям (если endpoint.events != "*")
    matched = []
    for ep in endpoints:
        if ep.events == "*":
            matched.append(ep)
        else:
            try:
                allowed = json.loads(ep.events)
                if event in allowed:
                    matched.append(ep)
            except (json.JSONDecodeError, TypeError):
                matched.append(ep)  # fallback: если events битый — шлём всё

    # Запускаем доставку параллельно в фоне
    for ep in matched:
        asyncio.create_task(_deliver(ep, event, payload))

    return len(matched)


# ── Список поддерживаемых событий (для документации / UI) ─────
WEBHOOK_EVENTS = {
    "message_sent":       "Сообщение отправлено",
    "message_delivered":  "Сообщение доставлено",
    "reply_received":     "Получен ответ на рассылку",
    "lead_collected":     "Новый лид собран (2GIS/чаты)",
    "campaign_completed": "Кампания рассылки завершена",
    "account_blocked":    "MAX-аккаунт заблокирован",
    "payment_success":    "Успешный платёж",
    "trial_expiring":     "Триал заканчивается (за 1 день)",
}
