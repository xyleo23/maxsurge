"""Универсальный запуск/пауза/стоп задач."""
import asyncio
import json
from datetime import datetime

from loguru import logger
from sqlalchemy import select

from db.models import Task, TaskStatus, TaskType, UserFile, async_session_factory

# Активные задачи: task_id -> asyncio.Task
_active_tasks: dict[int, asyncio.Task] = {}
_pause_flags: dict[int, bool] = {}


async def _update_task(task_id: int, **kwargs):
    """Обновить поля задачи в БД."""
    async with async_session_factory() as s:
        task = await s.get(Task, task_id)
        if task:
            for k, v in kwargs.items():
                setattr(task, k, v)
            await s.commit()


async def _append_log(task_id: int, line: str):
    """Добавить строку в лог задачи."""
    async with async_session_factory() as s:
        task = await s.get(Task, task_id)
        if task:
            log_list = json.loads(task.log or "[]")
            log_list.append(line)
            # Ограничиваем лог 500 строками
            if len(log_list) > 500:
                log_list = log_list[-500:]
            task.log = json.dumps(log_list, ensure_ascii=False)
            await s.commit()


def get_task_log(task: Task) -> list[str]:
    """Получить лог задачи как список строк."""
    return json.loads(task.log or "[]")


def get_task_config(task: Task) -> dict:
    """Получить конфиг задачи как словарь."""
    return json.loads(task.config or "{}")


async def get_file_lines(file_id: int) -> list[str]:
    """Получить строки из файла хранилища."""
    async with async_session_factory() as s:
        f = await s.get(UserFile, file_id)
        if not f:
            return []
        return [line.strip() for line in f.content.splitlines() if line.strip()]


async def run_task(task_id: int):
    """Запустить задачу по ID."""
    async with async_session_factory() as s:
        task = await s.get(Task, task_id)
    if not task:
        logger.error("Задача {} не найдена", task_id)
        return

    config = get_task_config(task)
    await _update_task(task_id, status=TaskStatus.RUNNING, started_at=datetime.utcnow())
    await _append_log(task_id, f"[START] Задача '{task.name}' запущена")
    _pause_flags[task_id] = False

    try:
        if task.task_type == TaskType.BROADCAST:
            await _run_broadcast_task(task_id, config)
        elif task.task_type == TaskType.INVITE:
            await _run_invite_task(task_id, config)
        elif task.task_type == TaskType.PARSE:
            await _run_parse_task(task_id, config)
        elif task.task_type == TaskType.WARM:
            await _run_warm_task(task_id, config)
        elif task.task_type == TaskType.CHECK:
            await _run_check_task(task_id, config)

        await _update_task(task_id, status=TaskStatus.COMPLETED, finished_at=datetime.utcnow())
        await _append_log(task_id, "[DONE] Задача завершена")
        # E3: TG уведомление владельцу
        try:
            from max_client.tg_notifier import notify_user_async
            async with async_session_factory() as _s:
                _t = await _s.get(Task, task_id)
                if _t and _t.owner_id:
                    notify_user_async(_t.owner_id, "✅ <b>" + _t.name + "</b> завершена (" + _t.task_type.value + ")", pref_field="notify_on_task_done")
        except Exception:
            pass
    except asyncio.CancelledError:
        await _update_task(task_id, status=TaskStatus.PAUSED)
        await _append_log(task_id, "[STOP] Задача остановлена")
    except Exception as e:
        await _update_task(task_id, status=TaskStatus.FAILED, finished_at=datetime.utcnow())
        await _append_log(task_id, f"[ERROR] {str(e)[:200]}")
        logger.error("Задача {} упала: {}", task_id, e)
    finally:
        _active_tasks.pop(task_id, None)
        _pause_flags.pop(task_id, None)


async def _check_pause(task_id: int):
    """Проверка паузы. Блокирует если задача на паузе."""
    while _pause_flags.get(task_id, False):
        await asyncio.sleep(1)


# ── Broadcast ──────────────────────────────────────────
async def _run_broadcast_task(task_id: int, config: dict):
    from max_client.sender import run_broadcast
    template_id = config.get("template_id", 1)
    limit = config.get("limit", 50)
    dry_run = config.get("dry_run", False)
    account_ids = config.get("account_ids")
    target_type = config.get("target_type", "users")
    typing = config.get("typing_emulation", True)

    # Переиспользуем существующий sender, но обновляем task progress
    from max_client.sender import _broadcast_status
    await run_broadcast(template_id, limit, dry_run, account_ids, target_type, typing)

    await _update_task(
        task_id,
        progress_today=_broadcast_status.get("sent", 0),
        progress_total=_broadcast_status.get("sent", 0),
        error_count=_broadcast_status.get("failed", 0),
        target_count=_broadcast_status.get("total", 0),
    )
    for line in _broadcast_status.get("log", []):
        await _append_log(task_id, line)


# ── Invite ──────────────────────────────────────────────
async def _run_invite_task(task_id: int, config: dict):
    from max_client.inviter import run_inviting
    chat_link = config.get("chat_link", "")
    file_id = config.get("file_id")
    user_ids_raw = config.get("user_ids", [])
    account_ids = config.get("account_ids")
    batch_size = config.get("batch_size", 50)
    delay_sec = config.get("delay_sec", 15)

    # Загрузить IDs из файла если указан
    if file_id:
        lines = await get_file_lines(file_id)
        user_ids = [int(x) for x in lines if x.isdigit()]
    else:
        user_ids = [int(x) for x in user_ids_raw if str(x).isdigit()]

    if not user_ids:
        await _append_log(task_id, "[WARN] Нет ID для инвайтинга")
        return

    await _update_task(task_id, target_count=len(user_ids))
    from max_client.inviter import _invite_status
    await run_inviting(chat_link, user_ids, account_ids, batch_size, delay_sec)

    await _update_task(
        task_id,
        progress_today=_invite_status.get("invited", 0),
        progress_total=_invite_status.get("invited", 0),
        error_count=_invite_status.get("failed", 0),
    )
    for line in _invite_status.get("log", []):
        await _append_log(task_id, line)


# ── Parse ──────────────────────────────────────────────
async def _run_parse_task(task_id: int, config: dict):
    from max_client.parser import mass_join_chats, parse_chat, _parse_status
    links = config.get("links", [])
    chat_ids = config.get("chat_ids", [])
    phone = config.get("phone")
    file_id = config.get("file_id")

    if file_id:
        lines = await get_file_lines(file_id)
        links = [l for l in lines if l]

    # Вступление
    if links:
        await mass_join_chats(links, phone)
        for line in _parse_status.get("log", []):
            await _append_log(task_id, line)

    # Парсинг по chat_id
    total_parsed = 0
    for cid in chat_ids:
        try:
            count = await parse_chat(int(cid), phone=phone)
            total_parsed += count
            await _append_log(task_id, f"[PARSE] chat {cid}: {count} юзеров")
        except Exception as e:
            await _append_log(task_id, f"[ERR] chat {cid}: {e}")
        await asyncio.sleep(2)

    await _update_task(task_id, progress_total=total_parsed)


# ── Warm ──────────────────────────────────────────────
async def _run_warm_task(task_id: int, config: dict):
    from max_client.warmer import run_warming, _warm_status
    account_ids = config.get("account_ids")
    actions = config.get("actions_per_account", 10)
    channels = config.get("channels")

    await run_warming(account_ids, actions, channels)
    await _update_task(
        task_id,
        progress_total=_warm_status.get("actions_done", 0),
        target_count=_warm_status.get("total_actions", 0),
    )
    for line in _warm_status.get("log", []):
        await _append_log(task_id, line)


# ── Check ──────────────────────────────────────────────
async def _run_check_task(task_id: int, config: dict):
    from max_client.checker import run_phone_checker, _check_status
    limit = config.get("limit", 20)
    phone = config.get("phone")

    await run_phone_checker(limit, phone)
    await _update_task(
        task_id,
        progress_total=_check_status.get("found", 0),
        error_count=_check_status.get("not_found", 0),
        target_count=_check_status.get("total", 0),
    )
    for line in _check_status.get("log", []):
        await _append_log(task_id, line)


# ── Управление ─────────────────────────────────────────
def start_task(task_id: int) -> asyncio.Task:
    """Запустить задачу в фоне."""
    if task_id in _active_tasks:
        raise RuntimeError(f"Задача {task_id} уже запущена")
    t = asyncio.create_task(run_task(task_id))
    _active_tasks[task_id] = t
    return t


def pause_task(task_id: int):
    _pause_flags[task_id] = not _pause_flags.get(task_id, False)
    return _pause_flags[task_id]


def stop_task(task_id: int):
    t = _active_tasks.get(task_id)
    if t:
        t.cancel()
    _pause_flags.pop(task_id, None)


def is_task_running(task_id: int) -> bool:
    return task_id in _active_tasks


def get_running_count() -> int:
    return len(_active_tasks)
