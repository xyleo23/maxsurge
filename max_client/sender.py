"""Рассылка v2: спинтакс, эмуляция набора, рассылка в чаты и по ID."""
import asyncio
import random
from datetime import datetime

from loguru import logger
from sqlalchemy import select, update

from db.models import Lead, LeadStatus, MaxAccount, MessageTemplate, SendLog, ChatCatalog, async_session_factory, AccountStatus
from max_client.account import account_manager
from max_client.spintax import render_template_with_spintax
from vkmax.functions.messages import send_message
from config import get_settings

settings = get_settings()

_broadcast_task: asyncio.Task | None = None
_broadcast_status: dict = {"running": False, "sent": 0, "failed": 0, "total": 0, "paused": False, "log": []}


def get_broadcast_status() -> dict:
    return dict(_broadcast_status)


async def _typing_emulation(client, chat_id: int, duration: float = 2.0):
    """Отправить статус 'печатает...' перед сообщением."""
    try:
        await client.invoke_method(opcode=63, payload={"chatId": chat_id, "action": "TYPING"})
        await asyncio.sleep(duration)
    except Exception:
        pass


async def _pick_account(active_pairs: list) -> tuple | None:
    for acc, client in active_pairs:
        if acc.sent_today < settings.SEND_MAX_PER_ACCOUNT_DAY:
            return acc, client
    return None


async def run_broadcast(
    template_id: int,
    limit: int = 50,
    dry_run: bool = False,
    account_ids: list[int] | None = None,
    target_type: str = "users",  # "users" или "chats"
    typing_emulation: bool = True,
):
    """Рассылка по лидам (users) или в чаты (chats)."""
    global _broadcast_status
    _broadcast_status = {"running": True, "sent": 0, "failed": 0, "total": 0, "paused": False, "log": []}

    try:
        async with async_session_factory() as session:
            tmpl = await session.get(MessageTemplate, template_id)
        if not tmpl:
            _broadcast_status["log"].append(f"Шаблон {template_id} не найден")
            return

        # Загружаем цели
        targets = []
        if target_type == "chats":
            async with async_session_factory() as session:
                chats = (await session.execute(
                    select(ChatCatalog).where(ChatCatalog.chat_id.isnot(None)).limit(limit)
                )).scalars().all()
            for ch in chats:
                targets.append({"id": ch.chat_id, "name": ch.name, "type": "chat"})
        else:
            async with async_session_factory() as session:
                leads = (await session.execute(
                    select(Lead).where(Lead.status == LeadStatus.NEW, Lead.max_user_id.isnot(None)).limit(limit)
                )).scalars().all()
            for lead in leads:
                targets.append({"id": lead.max_user_id, "name": lead.name, "type": "user", "lead": lead, "lead_id": lead.id})

        _broadcast_status["total"] = len(targets)
        if not targets:
            _broadcast_status["log"].append("Нет целей для рассылки")
            return

        active_pairs = await account_manager.get_all_active_clients()
        if account_ids:
            active_pairs = [(a, c) for a, c in active_pairs if a.id in account_ids]
        if not active_pairs and not dry_run:
            _broadcast_status["log"].append("Нет активных MAX аккаунтов")
            return

        for target in targets:
            if not _broadcast_status["running"]:
                break
            while _broadcast_status.get("paused"):
                await asyncio.sleep(1)
                if not _broadcast_status["running"]:
                    return

            lead_obj = target.get("lead")
            text = render_template_with_spintax(tmpl.body, lead_obj)
            if tmpl.attachment_url:
                text = text + chr(10) + chr(10) + tmpl.attachment_url

            if dry_run:
                _broadcast_status["log"].append(f"[DRY] {target['name']}: {text[:50]}...")
                _broadcast_status["sent"] += 1
                async with async_session_factory() as session:
                    session.add(SendLog(lead_id=target.get("lead_id"), account_id=0,
                        template_id=template_id, target_type=target["type"],
                        target_id=str(target["id"]), outgoing_text=text, status="dry_run"))
                    await session.commit()
                await asyncio.sleep(0.1)
                continue

            pair = await _pick_account(active_pairs)
            if not pair:
                _broadcast_status["log"].append("Все аккаунты исчерпали лимит")
                break

            acc, client = pair
            try:
                if typing_emulation:
                    await _typing_emulation(client, target["id"], random.uniform(1.5, 3.5))

                await send_message(client, target["id"], text)
                _broadcast_status["sent"] += 1
                _broadcast_status["log"].append(f"[OK] {target['name']} ({target['type']}:{target['id']})")

                async with async_session_factory() as session:
                    if target.get("lead_id"):
                        db_lead = await session.get(Lead, target["lead_id"])
                        if db_lead:
                            db_lead.status = LeadStatus.CONTACTED
                    db_acc = await session.get(MaxAccount, acc.id)
                    if db_acc:
                        db_acc.sent_today += 1
                        db_acc.sent_total += 1
                        db_acc.last_used_at = datetime.utcnow()
                    session.add(SendLog(lead_id=target.get("lead_id"), account_id=acc.id,
                        template_id=template_id, target_type=target["type"],
                        target_id=str(target["id"]), outgoing_text=text, status="sent"))
                    await session.commit()

            except Exception as e:
                err = str(e)
                _broadcast_status["failed"] += 1
                _broadcast_status["log"].append(f"[FAIL] {target['name']}: {err[:60]}")
                async with async_session_factory() as session:
                    session.add(SendLog(lead_id=target.get("lead_id"), account_id=acc.id,
                        template_id=template_id, outgoing_text=text, status="failed", error=err))
                    await session.commit()
                if "block" in err.lower() or "spam" in err.lower():
                    await account_manager.mark_blocked(acc.phone)

            delay = random.uniform(settings.SEND_DELAY_SEC * 0.8, settings.SEND_DELAY_SEC * 1.2)
            await asyncio.sleep(delay)

    except Exception as e:
        _broadcast_status["log"].append(f"КРИТИЧЕСКАЯ ОШИБКА: {e}")
    finally:
        _broadcast_status["running"] = False


def start_broadcast_background(template_id: int, limit: int, dry_run: bool,
                                account_ids: list[int] | None = None,
                                target_type: str = "users", typing_emulation: bool = True):
    global _broadcast_task
    if _broadcast_status.get("running"):
        raise RuntimeError("Рассылка уже запущена")
    _broadcast_task = asyncio.create_task(
        run_broadcast(template_id, limit, dry_run, account_ids, target_type, typing_emulation)
    )
    return _broadcast_task


def pause_broadcast():
    _broadcast_status["paused"] = not _broadcast_status.get("paused", False)
    return _broadcast_status["paused"]


def stop_broadcast():
    global _broadcast_status
    _broadcast_status["running"] = False
    _broadcast_status["paused"] = False
