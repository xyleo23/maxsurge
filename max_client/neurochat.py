"""Нейрочаттинг — AI-кампании партизанского маркетинга в чатах MAX.

Как работает:
- Кампания привязана к аккаунту-боту и списку чатов
- Бот слушает сообщения в указанных чатах
- По ключевым словам (mode=KEYWORDS) или на все (RESPOND_ALL) генерирует AI-ответ
- Каждое N-ое сообщение мягко упоминает product_description
- Поддерживает диалог, если собеседник отвечает
"""
import asyncio
import json
import random
from datetime import datetime, timedelta

from loguru import logger
from sqlalchemy import select, update

from db.models import (
    NeuroCampaign, NeuroCampaignStatus, NeuroMode, NeuroChatMessage,
    SiteUser, async_session_factory,
)
from max_client.account import account_manager
from max_client.ai_client import generate_ai_reply

# ── Состояние воркера ────────────────────────────────
_running_campaigns: dict[int, dict] = {}  # campaign_id -> runtime data
_dialog_memory: dict[tuple, list] = {}    # (campaign_id, chat_id, user_id) -> history


STYLE_PROMPTS = {
    "conversational": "Отвечай живо, разговорным языком, как обычный человек в чате. Без формальностей.",
    "business": "Отвечай деловым тоном, чётко и по сути. Без эмоций и смайлов.",
    "friendly": "Отвечай дружелюбно и тепло, можно с эмодзи, будто общаешься со старым знакомым.",
    "expert": "Отвечай как эксперт в теме: аргументированно, с конкретикой, но просто.",
}


async def _get_user_ai_keys(user_id: int) -> dict:
    async with async_session_factory() as s:
        user = await s.get(SiteUser, user_id)
        if user:
            return {
                "user_api_key": user.ai_api_key,
                "user_api_url": user.ai_api_url,
                "user_model": user.ai_model,
            }
    return {}


def _match_keywords(text: str, keywords_csv: str) -> bool:
    if not keywords_csv.strip():
        return False
    text_lc = text.lower()
    for kw in keywords_csv.split(","):
        kw = kw.strip().lower()
        if kw and kw in text_lc:
            return True
    return False


def _build_system_prompt(campaign: NeuroCampaign, should_mention: bool) -> str:
    base = campaign.system_prompt or ""
    style = STYLE_PROMPTS.get(campaign.style.value if hasattr(campaign.style, "value") else str(campaign.style), "")
    parts = [base, style]
    if should_mention and campaign.product_description:
        parts.append(
            f"\nВАЖНО: в этом ответе мягко, ненавязчиво упомяни: {campaign.product_description}. "
            "Не делай это рекламой — вплети в контекст, будто вспомнил случайно."
        )
    else:
        parts.append("\nНе упоминай никаких товаров или услуг в этом ответе. Просто поддержи разговор.")
    return "\n\n".join(p for p in parts if p)


async def _reset_daily_if_needed(campaign_id: int):
    async with async_session_factory() as s:
        camp = await s.get(NeuroCampaign, campaign_id)
        if not camp:
            return
        now = datetime.utcnow()
        if camp.last_reset_date.date() < now.date():
            camp.messages_today = 0
            camp.last_reset_date = now
            await s.commit()


async def _handle_message(campaign_id: int, packet: dict):
    """Обработка входящего сообщения."""
    if packet.get("cmd") != 1:
        return

    payload = packet.get("payload", {})
    msg = payload.get("message", {})
    chat_id = msg.get("chatId")
    sender_id = msg.get("senderId") or msg.get("userId")
    text = (msg.get("text") or "").strip()

    if not chat_id or not sender_id or not text:
        return

    runtime = _running_campaigns.get(campaign_id)
    if not runtime:
        return

    # Не отвечаем сами себе
    if sender_id == runtime.get("bot_user_id"):
        return

    async with async_session_factory() as s:
        camp = await s.get(NeuroCampaign, campaign_id)
        if not camp or camp.status != NeuroCampaignStatus.RUNNING:
            return

        # Фильтр чатов
        try:
            allowed_chats = json.loads(camp.chat_ids or "[]")
        except Exception:
            allowed_chats = []
        if allowed_chats and chat_id not in allowed_chats:
            return

        # Дневной лимит
        await _reset_daily_if_needed(campaign_id)
        await s.refresh(camp)
        if camp.messages_today >= camp.daily_limit:
            return

        # Режим
        is_reply_to_bot = False
        history_key = (campaign_id, chat_id, sender_id)
        if history_key in _dialog_memory and camp.support_replies:
            is_reply_to_bot = True

        should_respond = False
        if camp.mode == NeuroMode.RESPOND_ALL:
            should_respond = True
        elif camp.mode == NeuroMode.KEYWORDS:
            should_respond = _match_keywords(text, camp.keywords) or is_reply_to_bot

        if not should_respond:
            return

        owner_id = camp.owner_id
        mention_every = max(1, camp.mention_frequency or 30)
        should_mention = (camp.messages_sent % mention_every) == 0 and bool(camp.product_description)
        sys_prompt = _build_system_prompt(camp, should_mention)

        delay = random.uniform(camp.delay_min_sec, camp.delay_max_sec)
        ai_model = camp.ai_model

    # Задержка перед ответом
    await asyncio.sleep(delay)

    # AI вызов
    user_keys = await _get_user_ai_keys(owner_id)
    history = _dialog_memory.get(history_key, [])

    reply = await generate_ai_reply(
        user_message=text,
        knowledge_base=sys_prompt,
        history=history,
        user_model=ai_model,
        **{k: v for k, v in user_keys.items() if k != "user_model"},
    )

    if not reply:
        logger.warning("[neurochat] AI вернул пусто для кампании {}", campaign_id)
        return

    # Отправка
    client = runtime.get("client")
    try:
        from vkmax.functions.messages import send_message
        await send_message(client, chat_id, reply)
    except Exception as e:
        logger.error("[neurochat] send_message error: {}", e)
        return

    # Обновление истории/счётчиков
    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": reply})
    _dialog_memory[history_key] = history[-20:]

    async with async_session_factory() as s:
        camp = await s.get(NeuroCampaign, campaign_id)
        if camp:
            camp.messages_sent += 1
            camp.messages_today += 1
            s.add(NeuroChatMessage(
                campaign_id=campaign_id,
                chat_id=chat_id,
                trigger_message=text[:500],
                reply_sent=reply[:2000],
                mentioned_product=should_mention,
            ))
            await s.commit()

    logger.info("[neurochat] campaign={} chat={} sent reply", campaign_id, chat_id)


async def start_campaign(campaign_id: int) -> tuple[bool, str]:
    """Запустить кампанию."""
    async with async_session_factory() as s:
        camp = await s.get(NeuroCampaign, campaign_id)
        if not camp:
            return False, "Кампания не найдена"

        from db.models import MaxAccount
        acc = await s.get(MaxAccount, camp.account_id)
        if not acc:
            return False, "Аккаунт не найден"

    client = await account_manager.get_client(acc.phone)
    if not client:
        return False, f"Не удалось подключить аккаунт {acc.phone}"

    async def cb(pkt):
        try:
            await _handle_message(campaign_id, pkt)
        except Exception as e:
            logger.exception("[neurochat] handler error: {}", e)

    _running_campaigns[campaign_id] = {
        "client": client,
        "callback": cb,
        "bot_user_id": getattr(client, "user_id", None),
    }
    await client.set_callback(cb)

    async with async_session_factory() as s:
        camp = await s.get(NeuroCampaign, campaign_id)
        camp.status = NeuroCampaignStatus.RUNNING
        await s.commit()

    logger.info("[neurochat] campaign {} started", campaign_id)
    return True, "Кампания запущена"


async def stop_campaign(campaign_id: int) -> tuple[bool, str]:
    _running_campaigns.pop(campaign_id, None)
    async with async_session_factory() as s:
        camp = await s.get(NeuroCampaign, campaign_id)
        if camp:
            camp.status = NeuroCampaignStatus.STOPPED
            await s.commit()
    # Очистим память диалогов по этой кампании
    keys = [k for k in _dialog_memory if k[0] == campaign_id]
    for k in keys:
        _dialog_memory.pop(k, None)
    return True, "Кампания остановлена"


async def pause_campaign(campaign_id: int) -> tuple[bool, str]:
    async with async_session_factory() as s:
        camp = await s.get(NeuroCampaign, campaign_id)
        if camp:
            camp.status = NeuroCampaignStatus.PAUSED
            await s.commit()
    return True, "Кампания на паузе"


def get_running_ids() -> list[int]:
    return list(_running_campaigns.keys())


async def restore_running():
    """При старте приложения — перезапустить кампании со статусом RUNNING."""
    async with async_session_factory() as s:
        result = await s.execute(
            select(NeuroCampaign).where(NeuroCampaign.status == NeuroCampaignStatus.RUNNING)
        )
        camps = result.scalars().all()

    for c in camps:
        ok, msg = await start_campaign(c.id)
        logger.info("[neurochat] restore campaign {}: {} — {}", c.id, ok, msg)
