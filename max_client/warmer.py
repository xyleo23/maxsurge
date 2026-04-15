"""Прогрев аккаунтов — рандомные действия для разогрева новых аккаунтов."""
import asyncio
import random
from datetime import datetime

from loguru import logger
from sqlalchemy import select

from db.models import MaxAccount, AccountStatus, WarmingLog, async_session_factory
from max_client.account import account_manager
from max_client.ops import send_message
from max_client.ops import join_channel
from max_client.ops import change_profile

_warm_status: dict = {"running": False, "actions_done": 0, "total_actions": 0, "log": []}

# Список публичных каналов MAX для прогрева (вступление + просмотр)
WARMUP_CHANNELS = [
    "novostiru", "sportmax", "techmax", "kinomax",
    "muzmax", "automax", "gamemax",
]

WARMUP_MESSAGES = [
    "Привет!", "Добрый день!", "Как дела?", "Отличная погода!",
    "Что нового?", "Интересно!", "Круто!",
]

FIRST_NAMES = ["Алексей", "Дмитрий", "Сергей", "Андрей", "Михаил", "Иван", "Павел", "Артём"]
LAST_NAMES = ["Иванов", "Петров", "Смирнов", "Козлов", "Попов", "Кузнецов", "Морозов"]


def get_warm_status() -> dict:
    return dict(_warm_status)


async def _log_warming(account_id: int, action: str, target: str = "", status: str = "ok"):
    async with async_session_factory() as s:
        s.add(WarmingLog(account_id=account_id, action=action, target=target, status=status))
        await s.commit()


async def warm_account(acc: MaxAccount, client, actions_count: int = 10, custom_channels: list[str] | None = None):
    """Прогрев одного аккаунта: рандомные действия."""
    global _warm_status
    channels = custom_channels or WARMUP_CHANNELS

    available_actions = []

    # Вступление в каналы
    for ch in channels[:5]:
        available_actions.append(("join_channel", ch))

    # Отправка сообщения самому себе (если знаем user_id)
    if acc.max_user_id:
        for _ in range(3):
            available_actions.append(("self_message", str(acc.max_user_id)))

    # Смена профиля
    available_actions.append(("change_profile", ""))

    random.shuffle(available_actions)
    actions_to_do = available_actions[:actions_count]

    for action_type, target in actions_to_do:
        if not _warm_status["running"]:
            break

        try:
            if action_type == "join_channel":
                await join_channel(client, target)
                _warm_status["log"].append(f"[{acc.phone}] Вступил в канал {target}")
                await _log_warming(acc.id, "join_channel", target)

            elif action_type == "self_message":
                msg = random.choice(WARMUP_MESSAGES)
                await send_message(client, int(target), msg)
                _warm_status["log"].append(f"[{acc.phone}] Отправил себе: {msg}")
                await _log_warming(acc.id, "self_message", msg)

            elif action_type == "change_profile":
                fname = random.choice(FIRST_NAMES)
                lname = random.choice(LAST_NAMES)
                await change_profile(client, first_name=fname, last_name=lname)
                _warm_status["log"].append(f"[{acc.phone}] Сменил профиль: {fname} {lname}")
                await _log_warming(acc.id, "change_profile", f"{fname} {lname}")

            _warm_status["actions_done"] += 1
        except Exception as e:
            err = str(e)[:60]
            _warm_status["log"].append(f"[{acc.phone}] ОШИБКА {action_type}: {err}")
            await _log_warming(acc.id, action_type, target, status=f"error: {err}")

        delay = random.uniform(10, 30)
        await asyncio.sleep(delay)


async def run_warming(account_ids: list[int] | None = None, actions_per_account: int = 10, channels: list[str] | None = None):
    """Запуск прогрева для выбранных аккаунтов."""
    global _warm_status
    _warm_status = {"running": True, "actions_done": 0, "total_actions": 0, "log": []}

    try:
        pairs = await account_manager.get_all_active_clients()
        if account_ids:
            pairs = [(a, c) for a, c in pairs if a.id in account_ids]

        if not pairs:
            _warm_status["log"].append("Нет аккаунтов для прогрева")
            return

        _warm_status["total_actions"] = len(pairs) * actions_per_account
        _warm_status["log"].append(f"Прогрев {len(pairs)} аккаунтов по {actions_per_account} действий")

        for acc, client in pairs:
            if not _warm_status["running"]:
                break
            _warm_status["log"].append(f"--- Прогрев {acc.phone} ---")
            await warm_account(acc, client, actions_per_account, channels)
            await asyncio.sleep(5)

    except Exception as e:
        _warm_status["log"].append(f"ОШИБКА: {e}")
    finally:
        _warm_status["running"] = False


def stop_warming():
    global _warm_status
    _warm_status["running"] = False
