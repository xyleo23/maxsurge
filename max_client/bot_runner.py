"""Bot Runner — поллинг updates для активных MaxBot'ов и роутинг событий.

Каждый включённый бот получает свою фоновую задачу, которая опрашивает
/updates с long-polling. Новые сообщения роутятся в обработчики:
- LEAD: пошаговый диалог сбора данных
- BONUS: выдача промокода по /start или триггеру
- SUPPORT: AI-ответы на вопросы
"""
import asyncio
import json
import re
from datetime import datetime

from loguru import logger
from sqlalchemy import select

from db.models import (
    MaxBot, MaxBotType, MaxBotLead, MaxBotBonusClaim,
    SiteUser, Lead, LeadStatus, async_session_factory,
)
import httpx
from max_client.botapi import MaxBotAPI
from max_client.ai_client import generate_ai_reply
from config import get_settings

_settings = get_settings()


async def _tg_send_to_user(chat_id: int, text: str):
    """Отправка уведомления в TG владельцу (через общий OWNER_TG_BOT_TOKEN)."""
    token = getattr(_settings, "OWNER_TG_BOT_TOKEN", "")
    if not token or not chat_id:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            )
    except Exception as e:
        logger.warning("[bot_runner] TG send failed: {}", e)


_runners: dict[int, asyncio.Task] = {}


# ── Утилиты ──────────────────────────────
PHONE_RE = re.compile(r"(\+?\d[\d\s\-()]{7,}\d)")
EMAIL_RE = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")


def _extract_contact(text: str) -> dict:
    out = {}
    m = PHONE_RE.search(text)
    if m:
        out["phone"] = re.sub(r"[\s\-()]", "", m.group(1))
    m = EMAIL_RE.search(text)
    if m:
        out["email"] = m.group(0)
    return out


async def _notify_owner(bot: MaxBot, text: str):
    if not bot.notify_owner_tg:
        return
    async with async_session_factory() as s:
        user = await s.get(SiteUser, bot.owner_id)
        if not user:
            return
        tg_chat_id = getattr(user, "tg_chat_id", None)
    if tg_chat_id:
        await _tg_send_to_user(int(tg_chat_id), text)


# ── Обработчики типов ────────────────────
async def _handle_lead(api: MaxBotAPI, bot: MaxBot, msg: dict):
    sender = msg.get("sender") or {}
    recipient = msg.get("recipient") or {}
    user_id = sender.get("user_id")
    chat_id = recipient.get("chat_id") or sender.get("user_id")
    username = sender.get("username")
    body = msg.get("body") or {}
    text = (body.get("text") or "").strip()

    if not user_id:
        return

    async with async_session_factory() as s:
        # Ищем существующий диалог
        res = await s.execute(
            select(MaxBotLead).where(MaxBotLead.bot_id == bot.id, MaxBotLead.max_user_id == user_id)
        )
        lead = res.scalar_one_or_none()

        try:
            steps = json.loads(bot.steps or "[]")
        except Exception:
            steps = []

        is_start = text.lower() in ("/start", "start", "начать")

        if lead is None or is_start:
            if lead is None:
                lead = MaxBotLead(
                    bot_id=bot.id,
                    max_user_id=user_id,
                    max_chat_id=chat_id or 0,
                    username=username,
                    data="{}",
                    dialog_step=0,
                )
                s.add(lead)
            else:
                lead.dialog_step = 0
                lead.data = "{}"
                lead.completed = False
            await s.commit()
            await s.refresh(lead)

            await api.send_message(
                user_id=user_id,
                text=bot.welcome_text or "Здравствуйте!",
            )
            if steps:
                first_step = steps[0]
                await api.send_message(
                    user_id=user_id,
                    text=first_step.get("prompt", "Укажите данные:"),
                )
            return

        if lead.completed:
            return

        # Запись ответа на текущий шаг
        try:
            data = json.loads(lead.data or "{}")
        except Exception:
            data = {}

        if lead.dialog_step < len(steps):
            step = steps[lead.dialog_step]
            key = step.get("key", f"field_{lead.dialog_step}")
            data[key] = text
            # автодетект телефона/email в любом поле
            data.update(_extract_contact(text))
            lead.data = json.dumps(data, ensure_ascii=False)
            lead.dialog_step += 1

            # Следующий шаг или финал
            if lead.dialog_step < len(steps):
                next_step = steps[lead.dialog_step]
                await s.commit()
                await api.send_message(
                    user_id=user_id,
                    text=next_step.get("prompt", "Дальше?"),
                )
            else:
                lead.completed = True
                lead.completed_at = datetime.utcnow()

                # Создаём Lead в основной таблице лидов
                try:
                    s.add(Lead(
                        name=data.get("name", f"Bot Lead {user_id}"),
                        phone=data.get("phone"),
                        email=data.get("email"),
                        dgis_id=f"bot_{bot.id}_{user_id}",
                        comment=f"Из бота {bot.name}: {json.dumps(data, ensure_ascii=False)}",
                        owner_id=bot.owner_id,
                        status=LeadStatus.NEW,
                    ))
                except Exception as e:
                    logger.warning("[bot_runner] Lead create: {}", e)

                await s.commit()
                await api.send_message(
                    user_id=user_id,
                    text=bot.finish_text or "Спасибо!",
                )
                await _notify_owner(
                    bot,
                    f"🆕 <b>Новый лид</b> из бота <b>{bot.name}</b>\n\n"
                    + "\n".join(f"• {k}: {v}" for k, v in data.items()),
                )


async def _handle_bonus(api: MaxBotAPI, bot: MaxBot, msg: dict):
    sender = msg.get("sender") or {}
    user_id = sender.get("user_id")
    username = sender.get("username")
    body = msg.get("body") or {}
    text = (body.get("text") or "").strip()

    if not user_id:
        return

    is_start = text.lower() in ("/start", "start", "получить", "бонус", "промокод")
    if not is_start:
        return

    async with async_session_factory() as s:
        # Проверяем — уже получал?
        res = await s.execute(
            select(MaxBotBonusClaim).where(
                MaxBotBonusClaim.bot_id == bot.id,
                MaxBotBonusClaim.max_user_id == user_id,
            )
        )
        existing = res.scalar_one_or_none()

        if existing:
            await api.send_message(
                user_id=user_id,
                text=f"Вы уже получали бонус: <b>{existing.bonus_code_given}</b>\n\nОдин пользователь — один бонус.",
            )
            return

        # Проверка лимита
        if bot.bonus_limit > 0 and bot.bonus_issued >= bot.bonus_limit:
            await api.send_message(
                user_id=user_id,
                text="К сожалению, все бонусы уже разобраны. Следите за новыми акциями!",
            )
            return

        code = bot.bonus_code or "NOCODE"
        s.add(MaxBotBonusClaim(
            bot_id=bot.id,
            max_user_id=user_id,
            username=username,
            bonus_code_given=code,
        ))
        bot_obj = await s.get(MaxBot, bot.id)
        if bot_obj:
            bot_obj.bonus_issued += 1
        await s.commit()

    await api.send_message(
        user_id=user_id,
        text=(bot.welcome_text or "")
        + f"\n\n🎁 Ваш промокод: <b>{code}</b>\n\n"
        + (bot.bonus_description or ""),
    )


async def _handle_support(api: MaxBotAPI, bot: MaxBot, msg: dict):
    sender = msg.get("sender") or {}
    user_id = sender.get("user_id")
    body = msg.get("body") or {}
    text = (body.get("text") or "").strip()

    if not user_id or not text:
        return

    if text.lower() in ("/start", "start"):
        await api.send_message(user_id=user_id, text=bot.welcome_text or "Здравствуйте! Задайте ваш вопрос.")
        return

    if not bot.ai_enabled:
        await api.send_message(
            user_id=user_id,
            text="Ваш вопрос получен. Оператор скоро ответит.",
        )
        await _notify_owner(bot, f"❓ Вопрос в поддержку <b>{bot.name}</b>: {text}")
        return

    # AI ответ
    async with async_session_factory() as s:
        user = await s.get(SiteUser, bot.owner_id)
        user_keys = {
            "user_api_key": user.ai_api_key if user else None,
            "user_api_url": user.ai_api_url if user else None,
            "user_model": user.ai_model if user else None,
        }

    reply = await generate_ai_reply(
        user_message=text,
        knowledge_base=bot.knowledge_base or "",
        **user_keys,
    )
    if reply:
        await api.send_message(user_id=user_id, text=reply)
    else:
        await api.send_message(user_id=user_id, text="Минуту, уточняю информацию…")


# ── Основной цикл ────────────────────────
async def _run_bot(bot_id: int):
    """Фоновый long-polling для одного бота."""
    async with async_session_factory() as s:
        bot = await s.get(MaxBot, bot_id)
        if not bot:
            return

    api = MaxBotAPI(bot.token)
    logger.info("[bot_runner] Бот {} ({}) запущен", bot.name, bot.bot_type.value)

    try:
        while True:
            # Проверка что бот ещё включён
            async with async_session_factory() as s:
                bot = await s.get(MaxBot, bot_id)
                if not bot or not bot.enabled:
                    logger.info("[bot_runner] Бот {} остановлен", bot_id)
                    return

            res = await api.get_updates(marker=bot.last_update_id or 0, limit=50, timeout=30)
            updates = res.get("updates") or []

            for upd in updates:
                try:
                    async with async_session_factory() as s:
                        fresh = await s.get(MaxBot, bot_id)
                    if upd.get("update_type") == "message_created":
                        msg = upd.get("message", {})
                        if fresh.bot_type == MaxBotType.LEAD:
                            await _handle_lead(api, fresh, msg)
                        elif fresh.bot_type == MaxBotType.BONUS:
                            await _handle_bonus(api, fresh, msg)
                        elif fresh.bot_type == MaxBotType.SUPPORT:
                            await _handle_support(api, fresh, msg)
                except Exception as e:
                    logger.exception("[bot_runner] handler error: {}", e)

            if updates:
                marker = res.get("marker") or max((u.get("timestamp", 0) for u in updates), default=0)
                async with async_session_factory() as s:
                    fresh = await s.get(MaxBot, bot_id)
                    if fresh:
                        fresh.last_update_id = int(marker)
                        await s.commit()

            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        logger.info("[bot_runner] Бот {} отменён", bot_id)
        raise
    except Exception as e:
        logger.exception("[bot_runner] Бот {} крашнулся: {}", bot_id, e)
    finally:
        await api.close()


async def start_bot(bot_id: int) -> tuple[bool, str]:
    if bot_id in _runners and not _runners[bot_id].done():
        return False, "Уже запущен"

    async with async_session_factory() as s:
        bot = await s.get(MaxBot, bot_id)
        if not bot:
            return False, "Бот не найден"
        bot.enabled = True
        await s.commit()

    _runners[bot_id] = asyncio.create_task(_run_bot(bot_id))
    return True, "Запущен"


async def stop_bot(bot_id: int) -> tuple[bool, str]:
    async with async_session_factory() as s:
        bot = await s.get(MaxBot, bot_id)
        if bot:
            bot.enabled = False
            await s.commit()

    task = _runners.pop(bot_id, None)
    if task and not task.done():
        task.cancel()
    return True, "Остановлен"


def get_running_ids() -> list[int]:
    return [bid for bid, t in _runners.items() if not t.done()]


async def restore_running():
    """При старте приложения — поднять все включённые боты."""
    async with async_session_factory() as s:
        res = await s.execute(select(MaxBot).where(MaxBot.enabled == True))  # noqa
        bots = res.scalars().all()

    for b in bots:
        _runners[b.id] = asyncio.create_task(_run_bot(b.id))
        logger.info("[bot_runner] restore bot {}", b.id)
