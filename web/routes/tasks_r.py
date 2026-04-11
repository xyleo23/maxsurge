"""Управление задачами — CRUD + запуск/пауза/стоп."""
import json
from pathlib import Path
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from db.models import (Task, TaskStatus, TaskType, MaxAccount, AccountStatus,
                       MessageTemplate, UserFile, ChatCatalog, async_session_factory)
from db.plan_limits import check_limit
from web.routes._scope import get_request_user, scope_query
from max_client.task_runner import start_task, pause_task, stop_task, is_task_running, get_task_log, get_running_count

router = APIRouter(prefix="/tasks")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def tasks_page(request: Request, status: str = "", task_type: str = "", msg: str = ""):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        q = scope_query(select(Task), Task, user)
        if status:
            q = q.where(Task.status == TaskStatus(status))
        if task_type:
            q = q.where(Task.task_type == TaskType(task_type))
        tasks = (await s.execute(q.order_by(Task.created_at.desc()))).scalars().all()

        total_q = scope_query(select(func.count(Task.id)), Task, user)
        total = (await s.execute(total_q)).scalar() or 0

        acc_q = scope_query(select(MaxAccount), MaxAccount, user).where(MaxAccount.status == AccountStatus.ACTIVE)
        accounts = (await s.execute(acc_q)).scalars().all()

        tmpl_q = scope_query(select(MessageTemplate), MessageTemplate, user).where(MessageTemplate.is_active == True)
        tmpls = (await s.execute(tmpl_q)).scalars().all()

        file_q = scope_query(select(UserFile), UserFile, user).order_by(UserFile.created_at.desc())
        files = (await s.execute(file_q)).scalars().all()

        chat_q = scope_query(select(ChatCatalog), ChatCatalog, user).where(ChatCatalog.chat_id.isnot(None))
        chats = (await s.execute(chat_q)).scalars().all()

        _, current_tasks, tasks_limit = await check_limit(s, user, Task, "max_tasks")

    running = get_running_count()
    return templates.TemplateResponse(request=request, name="tasks.html", context={
        "tasks": tasks, "total": total, "running": running,
        "accounts": accounts, "templates": tmpls, "files": files, "chats": chats,
        "status_filter": status, "type_filter": task_type, "msg": msg,
        "task_types": [t.value for t in TaskType],
        "task_statuses": [s.value for s in TaskStatus],
        "current_tasks": current_tasks,
        "tasks_limit": tasks_limit,
    })


@router.post("/create")
async def create_task(
    request: Request,
    name: str = Form(...),
    task_type: str = Form(...),
    # Broadcast
    template_id: int = Form(0),
    limit: int = Form(50),
    dry_run: bool = Form(False),
    target_type: str = Form("users"),
    typing_emulation: bool = Form(True),
    # Invite
    chat_link: str = Form(""),
    file_id: int = Form(0),
    batch_size: int = Form(50),
    delay_sec: float = Form(15),
    # Parse
    links: str = Form(""),
    chat_ids: str = Form(""),
    # Warm
    actions_per_account: int = Form(10),
    channels: str = Form(""),
    # Check
    check_limit: int = Form(20),
    # Common
    account_ids: str = Form(""),
    phone: str = Form(""),
    notes: str = Form(""),
):
    config = {}
    tt = TaskType(task_type)

    if tt == TaskType.BROADCAST:
        config = {"template_id": template_id, "limit": limit, "dry_run": dry_run,
                  "target_type": target_type, "typing_emulation": typing_emulation}
    elif tt == TaskType.INVITE:
        config = {"chat_link": chat_link, "file_id": file_id or None,
                  "batch_size": batch_size, "delay_sec": delay_sec}
    elif tt == TaskType.PARSE:
        link_list = [l.strip() for l in links.splitlines() if l.strip()]
        cid_list = [c.strip() for c in chat_ids.split(",") if c.strip()]
        config = {"links": link_list, "chat_ids": cid_list, "phone": phone or None,
                  "file_id": file_id or None}
    elif tt == TaskType.WARM:
        ch = [c.strip() for c in channels.split(",") if c.strip()] if channels else None
        config = {"actions_per_account": actions_per_account, "channels": ch}
    elif tt == TaskType.CHECK:
        config = {"limit": check_limit, "phone": phone or None}

    if account_ids:
        config["account_ids"] = [int(x) for x in account_ids.split(",") if x.strip().isdigit()]

    user = await get_request_user(request)
    async with async_session_factory() as s:
        can_add, current, limit = await check_limit(s, user, Task, "max_tasks")
        if not can_add:
            return RedirectResponse(
                f"/app/tasks/?msg=Лимит+задач+({current}/{limit}).+Обновите+тариф.",
                status_code=303,
            )
        task = Task(
            name=name, task_type=tt, status=TaskStatus.DRAFT,
            config=json.dumps(config, ensure_ascii=False),
            notes=notes or None, log="[]",
            owner_id=user.id if user else None,
        )
        s.add(task)
        await s.commit()

    return RedirectResponse(f"/app/tasks/?msg=Задача+'{name}'+создана", status_code=303)


async def _get_task_if_owned(session, task_id: int, user):
    task = await session.get(Task, task_id)
    if not task:
        return None
    if user and getattr(user, "is_superadmin", False):
        return task
    if task.owner_id == (user.id if user else None):
        return task
    return None


@router.post("/{task_id}/start")
async def start(request: Request, task_id: int):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        task = await _get_task_if_owned(s, task_id, user)
        if not task:
            return RedirectResponse("/app/tasks/?msg=Нет+доступа", status_code=303)
    try:
        start_task(task_id)
        return RedirectResponse(f"/app/tasks/?msg=Задача+{task_id}+запущена", status_code=303)
    except RuntimeError as e:
        return RedirectResponse(f"/app/tasks/?msg={str(e)}", status_code=303)


@router.post("/{task_id}/pause")
async def pause(request: Request, task_id: int):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        task = await _get_task_if_owned(s, task_id, user)
        if not task:
            return RedirectResponse("/app/tasks/?msg=Нет+доступа", status_code=303)
    paused = pause_task(task_id)
    msg = "на+паузе" if paused else "продолжена"
    return RedirectResponse(f"/app/tasks/?msg=Задача+{task_id}+{msg}", status_code=303)


@router.post("/{task_id}/stop")
async def stop(request: Request, task_id: int):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        task = await _get_task_if_owned(s, task_id, user)
        if not task:
            return RedirectResponse("/app/tasks/?msg=Нет+доступа", status_code=303)
    stop_task(task_id)
    return RedirectResponse(f"/app/tasks/?msg=Задача+{task_id}+остановлена", status_code=303)


@router.post("/{task_id}/delete")
async def delete(request: Request, task_id: int):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        task = await _get_task_if_owned(s, task_id, user)
        if not task:
            return RedirectResponse("/app/tasks/?msg=Нет+доступа", status_code=303)
    stop_task(task_id)
    async with async_session_factory() as s:
        task = await s.get(Task, task_id)
        if task:
            await s.delete(task)
            await s.commit()
    return RedirectResponse("/app/tasks/", status_code=303)


@router.get("/{task_id}/log")
async def task_log(request: Request, task_id: int):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        task = await _get_task_if_owned(s, task_id, user)
    if not task:
        return JSONResponse({"log": []})
    return JSONResponse({
        "log": get_task_log(task),
        "status": task.status.value,
        "progress_today": task.progress_today,
        "progress_total": task.progress_total,
        "target_count": task.target_count,
        "error_count": task.error_count,
    })
