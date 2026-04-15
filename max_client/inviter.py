"""Инвайтинг — приглашение пользователей в чаты по ID списку."""
import asyncio
import random
import time
from datetime import datetime

from loguru import logger
from sqlalchemy import select

from db.models import async_session_factory
from max_client.account import account_manager
from max_client.ops import invite_users

_invite_status: dict = {"running": False, "invited": 0, "failed": 0, "total": 0, "paused": False, "log": []}


def get_invite_status() -> dict:
    return dict(_invite_status)


async def run_inviting(
    chat_link: str,
    user_ids: list[int],
    account_ids: list[int] | None = None,
    batch_size: int = 50,
    delay_sec: float = 15,
    delay_jitter: float = 5.0,
    micropause_every: int = 0,
    micropause_sec: float = 120.0,
    max_per_account_per_hour: int = 0,
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
        acc_history = {a.id: [] for a, _ in pairs}  # id -> [timestamps]

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

            # Account throttle: skip if max_per_account_per_hour reached
            if max_per_account_per_hour > 0:
                now = time.monotonic()
                acc_history[acc.id] = [t for t in acc_history[acc.id] if now - t < 3600]
                acc_history[acc.id].append(now)
                if len(acc_history[acc.id]) >= max_per_account_per_hour:
                    _invite_status["log"].append(f"[THROTTLE] {acc.phone}: лимит {max_per_account_per_hour}/ч")
                    acc_idx += 1

            # Основная пауза с jitter
            actual_delay = delay_sec + random.uniform(-delay_jitter, delay_jitter) if delay_jitter else delay_sec
            actual_delay = max(0.5, actual_delay)
            await asyncio.sleep(actual_delay)

            # Микропауза каждые N пачек
            if micropause_every > 0 and (batch_num + 1) % micropause_every == 0:
                pause_s = micropause_sec + random.uniform(0, micropause_sec * 0.2)
                _invite_status["log"].append(f"[PAUSE] Микропауза {int(pause_s)}с после {batch_num + 1} пачек")
                for _ in range(int(pause_s)):
                    if not _invite_status["running"]:
                        break
                    await asyncio.sleep(1)

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
