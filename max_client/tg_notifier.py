"""Telegram уведомления владельцу сервиса (новые регистрации, платежи, ошибки)."""
import asyncio

import httpx
from loguru import logger

from config import get_settings

settings = get_settings()


async def send_owner_notification(text: str, parse_mode: str = "HTML") -> bool:
    """Отправить уведомление владельцу в Telegram."""
    bot_token = getattr(settings, "OWNER_TG_BOT_TOKEN", "")
    chat_id = getattr(settings, "OWNER_TG_CHAT_ID", "")

    if not bot_token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            })
            if response.status_code == 200:
                return True
            logger.warning("TG notify failed: {} {}", response.status_code, response.text[:200])
    except Exception as e:
        logger.warning("TG notify error: {}", e)
    return False


def notify_async(text: str):
    """Не блокирующий вызов."""
    try:
        asyncio.create_task(send_owner_notification(text))
    except Exception:
        pass


# ── События ─────────────────────────────────────────
def on_signup(email: str, name: str | None = None, plan: str = "trial"):
    name_str = f" ({name})" if name else ""
    notify_async(
        f"🆕 <b>Новая регистрация</b>\n\n"
        f"📧 <code>{email}</code>{name_str}\n"
        f"📊 План: <b>{plan}</b>\n"
        f"🔗 <a href='https://maxsurge.ru/app/admin/users'>Админка</a>"
    )


def on_payment_success(email: str, plan: str, amount: float):
    notify_async(
        f"💰 <b>Новый платёж!</b>\n\n"
        f"📧 <code>{email}</code>\n"
        f"📦 Тариф: <b>{plan}</b>\n"
        f"💵 Сумма: <b>{amount:.0f} ₽</b>"
    )


def on_payment_created(email: str, plan: str, amount: float):
    notify_async(
        f"⏳ <b>Ожидание оплаты</b>\n\n"
        f"📧 <code>{email}</code>\n"
        f"📦 Тариф: <b>{plan}</b>\n"
        f"💵 <b>{amount:.0f} ₽</b>"
    )


def on_subscription_expired(email: str, plan: str):
    notify_async(
        f"⚠️ <b>Подписка истекла</b>\n\n"
        f"📧 <code>{email}</code>\n"
        f"📦 Был тариф: <b>{plan}</b> → откат на trial"
    )


def on_error(context: str, error: str):
    notify_async(
        f"🚨 <b>Ошибка в продакшне</b>\n\n"
        f"📍 <b>{context}</b>\n"
        f"<pre>{str(error)[:500]}</pre>"
    )
