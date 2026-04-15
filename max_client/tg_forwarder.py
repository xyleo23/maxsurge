"""TG -> MAX Responder: пересылка сообщений из Telegram каналов в MAX каналы/чаты."""
import asyncio
import re
import json
from datetime import datetime

from loguru import logger
from sqlalchemy import select

from db.models import async_session_factory
from max_client.account import account_manager
from max_client.spintax import process_spintax
from max_client.ops import send_message

_responder_status: dict = {
    "running": False,
    "forwarded": 0,
    "errors": 0,
    "log": [],
}

# Правила пересылки: [{tg_channel_id, max_chat_ids, strip_links, strip_mentions, stop_words}]
_forward_rules: list[dict] = []
_telethon_client = None


def get_forward_status() -> dict:
    return dict(_responder_status)


def get_forward_rules() -> list[dict]:
    return list(_forward_rules)


def _clean_forwarded_text(text: str, rule: dict) -> str:
    """Очистка текста: удаление ссылок, упоминаний, стоп-слов."""
    if rule.get("strip_links"):
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"t\.me/\S+", "", text)

    if rule.get("strip_mentions"):
        text = re.sub(r"@\w+", "", text)

    for word in rule.get("stop_words", []):
        text = text.replace(word, "")

    # Убрать лишние пустые строки
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


async def _forward_to_max(text: str, max_chat_ids: list[int], phone: str | None = None):
    """Отправить текст в несколько MAX чатов."""
    if phone:
        client = await account_manager.get_client(phone)
    else:
        pairs = await account_manager.get_all_active_clients()
        if not pairs:
            return 0
        _, client = pairs[0]

    if not client:
        return 0

    sent = 0
    for chat_id in max_chat_ids:
        try:
            await send_message(client, chat_id, text)
            sent += 1
            await asyncio.sleep(2)
        except Exception as e:
            _responder_status["errors"] += 1
            _responder_status["log"].append(f"[ERR] MAX chat {chat_id}: {str(e)[:50]}")
    return sent


def add_forward_rule(
    tg_channel_id: int,
    max_chat_ids: list[int],
    strip_links: bool = True,
    strip_mentions: bool = True,
    stop_words: list[str] | None = None,
    phone: str | None = None,
):
    """Добавить правило пересылки."""
    _forward_rules.append({
        "tg_channel_id": tg_channel_id,
        "max_chat_ids": max_chat_ids,
        "strip_links": strip_links,
        "strip_mentions": strip_mentions,
        "stop_words": stop_words or [],
        "phone": phone,
    })
    _responder_status["log"].append(f"[RULE] TG:{tg_channel_id} -> MAX:{max_chat_ids}")


def remove_forward_rule(index: int):
    if 0 <= index < len(_forward_rules):
        rule = _forward_rules.pop(index)
        _responder_status["log"].append(f"[DEL] Правило удалено: TG:{rule['tg_channel_id']}")


async def start_tg_listener(api_id: int, api_hash: str, session_path: str = "sessions/tg_responder"):
    """Запустить Telethon клиент для прослушивания TG каналов."""
    global _telethon_client, _responder_status

    try:
        from telethon import TelegramClient, events
    except ImportError:
        _responder_status["log"].append("[ERR] telethon не установлен: pip install telethon")
        return

    _responder_status["running"] = True
    _responder_status["log"].append("[START] Подключение к Telegram...")

    client = TelegramClient(session_path, api_id, api_hash)
    await client.start()
    _telethon_client = client
    _responder_status["log"].append("[OK] Telegram подключён")

    # Собираем ID каналов из правил
    tg_channels = [r["tg_channel_id"] for r in _forward_rules]

    @client.on(events.NewMessage(chats=tg_channels))
    async def handler(event):
        if not _responder_status["running"]:
            return

        text = event.message.text or ""
        if not text:
            return

        # Находим правило
        chat_id = event.chat_id
        for rule in _forward_rules:
            if rule["tg_channel_id"] == chat_id or rule["tg_channel_id"] == -chat_id:
                cleaned = _clean_forwarded_text(text, rule)
                if cleaned:
                    sent = await _forward_to_max(cleaned, rule["max_chat_ids"], rule.get("phone"))
                    _responder_status["forwarded"] += sent
                    _responder_status["log"].append(
                        f"[FWD] TG:{chat_id} -> {sent} MAX чатов: {cleaned[:40]}..."
                    )
                break

    _responder_status["log"].append(f"[LISTEN] Слушаю {len(tg_channels)} TG каналов...")
    await client.run_until_disconnected()


def stop_tg_listener():
    global _responder_status, _telethon_client
    _responder_status["running"] = False
    if _telethon_client:
        _telethon_client.disconnect()
        _telethon_client = None
    _responder_status["log"].append("[STOP] Telegram отключён")
