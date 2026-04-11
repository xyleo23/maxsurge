"""Страж чата — автоматический модератор чатов MAX.

Работает от имени аккаунта-админа чата. Слушает сообщения, проверяет
правила, удаляет/банит нарушителей, приветствует новичков.

Требует чтобы аккаунт уже был админом в целевом чате (добавить вручную).
"""
import asyncio
import json
import re
import time
from collections import deque
from datetime import datetime

from loguru import logger
from sqlalchemy import select

from db.models import (
    ChatGuard, GuardEvent, GuardAction, MaxAccount, async_session_factory,
)
from max_client.account import account_manager
from max_client.ai_client import generate_ai_reply


_running: dict[int, dict] = {}  # guard_id -> runtime
# flood tracker: (guard_id, user_id) -> deque of timestamps
_flood_buckets: dict[tuple, deque] = {}


URL_RE = re.compile(r"(https?://|www\.|t\.me/|\b[\w-]+\.(?:com|ru|net|org|io|app|me|su|рф)\b)", re.I)
MENTION_RE = re.compile(r"@[\w]{3,}")


def _parse_csv_ids(s: str) -> set[int]:
    out = set()
    for part in (s or "").split(","):
        part = part.strip()
        if part.isdigit() or (part.startswith("-") and part[1:].isdigit()):
            out.add(int(part))
    return out


def _match_stop_words(text: str, csv: str) -> str | None:
    if not csv.strip():
        return None
    tl = text.lower()
    for w in csv.split(","):
        w = w.strip().lower()
        if w and w in tl:
            return w
    return None


def _is_flood(guard_id: int, user_id: int, limit: int, interval_sec: int) -> bool:
    if limit <= 0:
        return False
    key = (guard_id, user_id)
    bucket = _flood_buckets.setdefault(key, deque(maxlen=limit * 3))
    now = time.monotonic()
    bucket.append(now)
    # Удаляем старые
    while bucket and (now - bucket[0]) > interval_sec:
        bucket.popleft()
    return len(bucket) > limit


async def _log_action(guard_id: int, user_id: int, username: str | None, action: GuardAction, reason: str, preview: str):
    async with async_session_factory() as s:
        s.add(GuardEvent(
            guard_id=guard_id,
            max_user_id=user_id,
            username=username,
            action=action,
            reason=reason,
            message_preview=preview[:500] if preview else None,
        ))
        g = await s.get(ChatGuard, guard_id)
        if g:
            if action == GuardAction.DELETE or action == GuardAction.WARN:
                g.deleted_count += 1
            elif action == GuardAction.BAN:
                g.banned_count += 1
        await s.commit()


async def _ai_check_toxicity(text: str, threshold: float) -> bool:
    """Возвращает True если сообщение токсично по мнению AI."""
    prompt = (
        "Оцени уровень токсичности этого сообщения от 0.0 до 1.0. "
        "Токсичность = оскорбления, мат, угрозы, разжигание ненависти, "
        "спам, мошенничество. Ответь ТОЛЬКО числом без пояснений."
    )
    resp = await generate_ai_reply(
        user_message=text,
        knowledge_base=prompt,
        max_tokens=10,
    )
    if not resp:
        return False
    try:
        score = float(re.search(r"(\d\.?\d*)", resp).group(1))
        return score >= threshold
    except Exception:
        return False


async def _apply_action(client, guard: ChatGuard, message_id: int, user_id: int, action: GuardAction, reason: str):
    """Выполняет действие модератора."""
    chat_id = guard.chat_id
    try:
        if action == GuardAction.DELETE:
            from vkmax.functions.messages import delete_message
            await delete_message(client, chat_id, [str(message_id)])
        elif action == GuardAction.WARN:
            from vkmax.functions.messages import send_message
            await send_message(client, chat_id, f"⚠️ Предупреждение: {reason}")
        elif action == GuardAction.BAN:
            from vkmax.functions.messages import delete_message
            from vkmax.functions.groups import remove_users
            await delete_message(client, chat_id, [str(message_id)])
            await remove_users(client, chat_id, [user_id], delete_messages=True)
    except Exception as e:
        logger.warning("[guard] apply {} failed: {}", action, e)


async def _handle_message(guard_id: int, packet: dict):
    if packet.get("cmd") != 1:
        return
    payload = packet.get("payload", {})
    msg = payload.get("message", {})
    chat_id = msg.get("chatId")
    sender_id = msg.get("senderId") or msg.get("userId")
    msg_id = msg.get("id") or msg.get("messageId")
    text = (msg.get("text") or "")
    is_forward = bool(msg.get("forwardedFrom") or msg.get("forward"))

    if not chat_id or not sender_id:
        return

    runtime = _running.get(guard_id)
    if not runtime:
        return
    if sender_id == runtime.get("bot_user_id"):
        return

    async with async_session_factory() as s:
        guard = await s.get(ChatGuard, guard_id)
        if not guard or not guard.enabled or guard.chat_id != chat_id:
            return
        whitelist = _parse_csv_ids(guard.whitelist_ids)

    if sender_id in whitelist:
        return

    # Новый участник?
    if msg.get("type") == "service" and guard.welcome_enabled and guard.welcome_text:
        try:
            from vkmax.functions.messages import send_message
            await send_message(runtime["client"], chat_id, guard.welcome_text)
        except Exception:
            pass
        return

    client = runtime.get("client")

    # 1. Forwards
    if guard.delete_forwards and is_forward:
        await _apply_action(client, guard, msg_id, sender_id, GuardAction.DELETE, "forward запрещён")
        await _log_action(guard_id, sender_id, msg.get("username"), GuardAction.DELETE, "forward", text)
        return

    # 2. Ссылки
    if guard.delete_links and text and URL_RE.search(text):
        await _apply_action(client, guard, msg_id, sender_id, GuardAction.DELETE, "ссылки запрещены")
        await _log_action(guard_id, sender_id, msg.get("username"), GuardAction.DELETE, "link", text)
        return

    # 3. @mentions
    if guard.delete_mentions and text and MENTION_RE.search(text):
        await _apply_action(client, guard, msg_id, sender_id, GuardAction.DELETE, "упоминания запрещены")
        await _log_action(guard_id, sender_id, msg.get("username"), GuardAction.DELETE, "mention", text)
        return

    # 4. Стоп-слова
    if text:
        sw = _match_stop_words(text, guard.stop_words)
        if sw:
            await _apply_action(client, guard, msg_id, sender_id, guard.stop_words_action, f"стоп-слово '{sw}'")
            await _log_action(guard_id, sender_id, msg.get("username"), guard.stop_words_action, f"stop-word: {sw}", text)
            return

    # 5. Флуд
    if _is_flood(guard_id, sender_id, guard.flood_limit, guard.flood_interval_sec):
        await _apply_action(client, guard, msg_id, sender_id, guard.flood_action, "флуд")
        await _log_action(guard_id, sender_id, msg.get("username"), guard.flood_action, "flood", text)
        return

    # 6. AI токсичность
    if guard.ai_moderation and text and len(text) > 10:
        if await _ai_check_toxicity(text, guard.ai_toxicity_threshold):
            await _apply_action(client, guard, msg_id, sender_id, GuardAction.DELETE, "AI: токсично")
            await _log_action(guard_id, sender_id, msg.get("username"), GuardAction.DELETE, "ai_toxic", text)
            return


async def start_guard(guard_id: int) -> tuple[bool, str]:
    async with async_session_factory() as s:
        guard = await s.get(ChatGuard, guard_id)
        if not guard:
            return False, "Не найден"
        acc = await s.get(MaxAccount, guard.account_id)
        if not acc:
            return False, "Аккаунт не найден"

    client = await account_manager.get_client(acc.phone)
    if not client:
        return False, f"Не удалось подключить {acc.phone}"

    async def cb(pkt):
        try:
            await _handle_message(guard_id, pkt)
        except Exception as e:
            logger.exception("[guard] handler: {}", e)

    _running[guard_id] = {
        "client": client,
        "callback": cb,
        "bot_user_id": getattr(client, "user_id", None),
    }
    await client.set_callback(cb)

    async with async_session_factory() as s:
        g = await s.get(ChatGuard, guard_id)
        g.enabled = True
        await s.commit()

    logger.info("[guard] Страж {} запущен", guard_id)
    return True, "Запущен"


async def stop_guard(guard_id: int) -> tuple[bool, str]:
    _running.pop(guard_id, None)
    # Очистить флуд-бакеты
    keys = [k for k in _flood_buckets if k[0] == guard_id]
    for k in keys:
        _flood_buckets.pop(k, None)

    async with async_session_factory() as s:
        g = await s.get(ChatGuard, guard_id)
        if g:
            g.enabled = False
            await s.commit()
    return True, "Остановлен"


def get_running_ids() -> list[int]:
    return list(_running.keys())


async def restore_running():
    async with async_session_factory() as s:
        res = await s.execute(select(ChatGuard).where(ChatGuard.enabled == True))  # noqa
        guards = res.scalars().all()
    for g in guards:
        ok, msg = await start_guard(g.id)
        logger.info("[guard] restore {}: {} — {}", g.id, ok, msg)
