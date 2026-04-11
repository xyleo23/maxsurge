"""Инвайтинг — приглашение пользователей в чаты по ID списку."""
import asyncio
from datetime import datetime

from loguru import logger
from sqlalchemy import select

from db.models import async_session_factory
from max_client.account import account_manager
from vkmax.functions.groups import invite_users

_invite_status: dict = {"running": False, "invited": 0, "failed": 0, "total": 0, "paused": False, "log": []}


def get_invite_status() -> dict:
    return dict(_invite_status)


async def run_inviting(
    chat_link: str,
    user_ids: list[int],
    account_ids: list[int] | None = None,
    batch_size: int = 50,
    delay_sec: float = 15,
):
    """Инвайтинг пользователей в чат по ID. Поддержка пачек и паузы."""
    global _invite_status
    _invite_status = {"running": True, "invited": 0, "failed": 0, "total": len(user_ids), "paused": False, "log": []}

    try:
        pairs = await account_manager.get_all_active_clients()
        if account_ids:
            pairs = [(a, c) for a, c in pairs if a.id in account_ids]
        if not pairs:
            _invite_status["log"].append("Нет активных аккаунтов")
            return

        # Резолв чата
        from max_client.parser import join_chat_by_link
        acc, client = pairs[0]
        join_resp = await join_chat_by_link(client, chat_link)
        chat_id = None
        if join_resp:
            chat_id = join_resp.get("payload", {}).get("chat", {}).get("id")
        if not chat_id:
            _invite_status["log"].append(f"Не удалось вступить в чат: {chat_link}")
            return

        _invite_status["log"].append(f"Чат: {chat_link} (id={chat_id})")

        # Разбиваем на пачки
        batches = [user_ids[i:i+batch_size] for i in range(0, len(user_ids), batch_size)]
        acc_idx = 0

        for batch_num, batch in enumerate(batches):
            if not _invite_status["running"]:
                break

            # Пауза
            while _invite_status.get("paused"):
                await asyncio.sleep(1)
                if not _invite_status["running"]:
                    return

            acc, client = pairs[acc_idx % len(pairs)]
            try:
                await invite_users(client, chat_id, batch)
                _invite_status["invited"] += len(batch)
                _invite_status["log"].append(
                    f"[OK] Пачка {batch_num+1}/{len(batches)}: {len(batch)} чел. (акк: {acc.phone})"
                )
            except Exception as e:
                err = str(e)[:60]
                _invite_status["failed"] += len(batch)
                _invite_status["log"].append(f"[FAIL] Пачка {batch_num+1}: {err}")
                # Если лимит — меняем аккаунт
                if "limit" in err.lower() or "block" in err.lower():
                    acc_idx += 1
                    _invite_status["log"].append(f"Смена аккаунта → #{acc_idx % len(pairs) + 1}")

            await asyncio.sleep(delay_sec)

    except Exception as e:
        _invite_status["log"].append(f"ОШИБКА: {e}")
    finally:
        _invite_status["running"] = False


def pause_inviting():
    _invite_status["paused"] = not _invite_status.get("paused", False)
    return _invite_status["paused"]


def stop_inviting():
    global _invite_status
    _invite_status["running"] = False
    _invite_status["paused"] = False
