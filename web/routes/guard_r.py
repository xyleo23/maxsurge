"""Роуты Стража чата."""
from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc

from db.models import (
    ChatGuard, GuardEvent, GuardAction, MaxAccount, AccountStatus,
    async_session_factory,
)
from db.plan_limits import check_limit
from web.routes._scope import scope_query
from web.routes.auth_r import get_current_user
from max_client import guard as guard_mod

router = APIRouter(prefix="/guard")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def page(request: Request, msg: str = "", err: str = ""):
    user = await get_current_user(request)
    async with async_session_factory() as s:
        q = scope_query(select(ChatGuard), ChatGuard, user).order_by(desc(ChatGuard.created_at))
        guards = (await s.execute(q)).scalars().all()
        acc_q = scope_query(select(MaxAccount), MaxAccount, user).where(MaxAccount.status == AccountStatus.ACTIVE)
        accounts = (await s.execute(acc_q)).scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="guard.html",
        context={
            "guards": guards,
            "accounts": accounts,
            "running": guard_mod.get_running_ids(),
            "msg": msg,
            "err": err,
        },
    )


@router.post("/create")
async def create(
    request: Request,
    name: str = Form(...),
    account_id: int = Form(...),
    chat_id: int = Form(...),
    delete_links: bool = Form(False),
    delete_mentions: bool = Form(False),
    delete_forwards: bool = Form(False),
    stop_words: str = Form(""),
    stop_words_action: str = Form("delete"),
    flood_limit: int = Form(0),
    flood_interval_sec: int = Form(10),
    flood_action: str = Form("delete"),
    whitelist_ids: str = Form(""),
    ai_moderation: bool = Form(False),
    ai_toxicity_threshold: float = Form(0.8),
    welcome_enabled: bool = Form(False),
    welcome_text: str = Form(""),
    rules_text: str = Form(""),
):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    async with async_session_factory() as s:
        can, cur, lim = await check_limit(s, user, ChatGuard, "max_tasks")
        if not can:
            return RedirectResponse(f"/app/guard/?err=Лимит {cur}/{lim}", status_code=303)
        acc = await s.get(MaxAccount, account_id)
        if not acc or (acc.owner_id != user.id and not user.is_superadmin):
            return RedirectResponse("/app/guard/?err=Аккаунт не найден", status_code=303)

        g = ChatGuard(
            name=name,
            account_id=account_id,
            chat_id=chat_id,
            delete_links=delete_links,
            delete_mentions=delete_mentions,
            delete_forwards=delete_forwards,
            stop_words=stop_words,
            stop_words_action=GuardAction(stop_words_action),
            flood_limit=max(0, flood_limit),
            flood_interval_sec=max(1, flood_interval_sec),
            flood_action=GuardAction(flood_action),
            whitelist_ids=whitelist_ids,
            ai_moderation=ai_moderation,
            ai_toxicity_threshold=max(0.0, min(1.0, ai_toxicity_threshold)),
            welcome_enabled=welcome_enabled,
            welcome_text=welcome_text or "Добро пожаловать!",
            rules_text=rules_text,
            owner_id=user.id,
        )
        s.add(g)
        await s.commit()
    return RedirectResponse("/app/guard/?msg=Страж создан", status_code=303)


async def _check_owner(guard_id: int, user) -> ChatGuard | None:
    async with async_session_factory() as s:
        g = await s.get(ChatGuard, guard_id)
    if not g:
        return None
    if not user.is_superadmin and g.owner_id != user.id:
        return None
    return g


@router.post("/{guard_id}/start")
async def start(guard_id: int, request: Request):
    user = await get_current_user(request)
    if not user or not await _check_owner(guard_id, user):
        return RedirectResponse("/app/guard/?err=Нет доступа", status_code=303)
    ok, msg = await guard_mod.start_guard(guard_id)
    return RedirectResponse(f"/app/guard/?{'msg' if ok else 'err'}={msg}", status_code=303)


@router.post("/{guard_id}/stop")
async def stop(guard_id: int, request: Request):
    user = await get_current_user(request)
    if not user or not await _check_owner(guard_id, user):
        return RedirectResponse("/app/guard/?err=Нет доступа", status_code=303)
    ok, msg = await guard_mod.stop_guard(guard_id)
    return RedirectResponse(f"/app/guard/?{'msg' if ok else 'err'}={msg}", status_code=303)


@router.post("/{guard_id}/delete")
async def delete(guard_id: int, request: Request):
    user = await get_current_user(request)
    if not user or not await _check_owner(guard_id, user):
        return RedirectResponse("/app/guard/?err=Нет доступа", status_code=303)
    await guard_mod.stop_guard(guard_id)
    async with async_session_factory() as s:
        g = await s.get(ChatGuard, guard_id)
        if g:
            await s.delete(g)
            await s.commit()
    return RedirectResponse("/app/guard/?msg=Удалён", status_code=303)


@router.get("/{guard_id}/log", response_class=HTMLResponse)
async def view_log(guard_id: int, request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    guard = await _check_owner(guard_id, user)
    if not guard:
        return RedirectResponse("/app/guard/?err=Не найден", status_code=303)
    async with async_session_factory() as s:
        q = select(GuardEvent).where(GuardEvent.guard_id == guard_id).order_by(desc(GuardEvent.created_at)).limit(500)
        events = (await s.execute(q)).scalars().all()
    return templates.TemplateResponse(
        request=request,
        name="guard_log.html",
        context={"guard": guard, "events": events},
    )
