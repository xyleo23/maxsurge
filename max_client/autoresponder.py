"""Автоответчик — слушает входящие сообщения и отвечает автоматически.
Поддерживает AI режим с per-user API ключами."""
import asyncio
import random
from datetime import datetime

from loguru import logger
from sqlalchemy import select

from db.models import SiteUser, async_session_factory
from max_client.account import account_manager
from max_client.spintax import process_spintax
from max_client.ai_client import generate_ai_reply

_responder_status: dict = {"running": False, "responded": 0, "log": []}
_responder_configs: dict[str, dict] = {}
_dialog_history: dict[tuple, list] = {}


def get_responder_status() -> dict:
    return dict(_responder_status)


def get_responder_configs() -> dict:
    return dict(_responder_configs)


async def _get_user_ai_keys(user_id: int | None) -> dict:
    """Получить AI ключи пользователя из БД."""
    if not user_id:
        return {}
    async with async_session_factory() as s:
        user = await s.get(SiteUser, user_id)
        if user:
            return {
                "user_api_key": user.ai_api_key,
                "user_api_url": user.ai_api_url,
                "user_model": user.ai_model,
            }
    return {}


async def _handle_incoming(client, packet: dict):
    """Callback для входящих сообщений."""
    global _responder_status

    if packet.get("cmd") != 1:
        return

    payload = packet.get("payload", {})
    msg = payload.get("message", {})
    sender_id = msg.get("senderId") or msg.get("userId")
    chat_id = msg.get("chatId")
    text = msg.get("text", "")

    if not sender_id or not text:
        return

    phone = None
    for p, (cl, _) in account_manager._clients.items():
        if cl is client:
            phone = p
            break
    if not phone or phone not in _responder_configs:
        return

    cfg = _responder_configs[phone]
    if cfg.get("responded_today", 0) >= cfg.get("limit_per_day", 50):
        return

    delay = random.uniform(cfg.get("delay_min", 3), cfg.get("delay_max", 10))
    await asyncio.sleep(delay)

    if cfg.get("typing_emulation"):
        try:
            await client.invoke_method(opcode=63, payload={"chatId": chat_id, "action": "TYPING"})
            await asyncio.sleep(random.uniform(1, 3))
        except Exception:
            pass

    reply_text = None
    if cfg.get("use_ai"):
        history_key = (phone, chat_id)
        history = _dialog_history.get(history_key, [])

        # Загружаем per-user ключи из БД
        user_keys = await _get_user_ai_keys(cfg.get("user_id"))

        reply_text = await generate_ai_reply(
            user_message=text,
            knowledge_base=cfg.get("knowledge_base", ""),
            history=history,
            **user_keys,
        )

        if reply_text:
            history.append({"role": "user", "content": text})
            history.append({"role": "assistant", "content": reply_text})
            _dialog_history[history_key] = history[-20:]
        else:
            reply_text = process_spintax(cfg.get("text", "Здравствуйте! Менеджер скоро ответит."))
            _responder_status["log"].append(f"[AI-FAIL] {phone} → fallback")

    if not reply_text:
        reply_text = process_spintax(cfg.get("text", "Здравствуйте!"))

    try:
        from vkmax.functions.messages import send_message
        await send_message(client, chat_id, reply_text)
        cfg["responded_today"] = cfg.get("responded_today", 0) + 1
        _responder_status["responded"] += 1
        mode = "AI" if cfg.get("use_ai") else "TXT"
        _responder_status["log"].append(
            f"[{mode}] {phone} → user {sender_id}: {reply_text[:50]}..."
        )
        logger.info("Автоответ [{}] {} → {}: {}", mode, phone, sender_id, reply_text[:50])
    except Exception as e:
        _responder_status["log"].append(f"[ERR] {phone}: {e}")


async def start_autoresponder(
    phone: str,
    text: str,
    delay_min: float = 3,
    delay_max: float = 10,
    limit_per_day: int = 50,
    typing_emulation: bool = True,
    use_ai: bool = False,
    knowledge_base: str = "",
    user_id: int | None = None,
):
    """Запустить автоответчик для аккаунта."""
    global _responder_status
    client = await account_manager.get_client(phone)
    if not client:
        _responder_status["log"].append(f"Аккаунт {phone} не найден")
        return

    _responder_configs[phone] = {
        "text": text,
        "delay_min": delay_min,
        "delay_max": delay_max,
        "limit_per_day": limit_per_day,
        "typing_emulation": typing_emulation,
        "use_ai": use_ai,
        "knowledge_base": knowledge_base,
        "user_id": user_id,
        "responded_today": 0,
    }

    await client.set_callback(_handle_incoming)
    _responder_status["running"] = True
    mode = "AI" if use_ai else "статичный текст"
    _responder_status["log"].append(f"[ON] Автоответчик для {phone} включён ({mode})")


def stop_autoresponder(phone: str):
    global _responder_status
    _responder_configs.pop(phone, None)
    keys_to_remove = [k for k in _dialog_history.keys() if k[0] == phone]
    for k in keys_to_remove:
        del _dialog_history[k]

    if not _responder_configs:
        _responder_status["running"] = False
    _responder_status["log"].append(f"[OFF] Автоответчик для {phone} выключен")
