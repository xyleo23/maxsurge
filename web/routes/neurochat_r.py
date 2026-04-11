"""Роуты нейрочаттинга — AI партизанский маркетинг в чатах."""
import json
from pathlib import Path

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc

from db.models import (
    NeuroCampaign, NeuroCampaignStatus, NeuroMode, NeuroStyle,
    NeuroChatMessage, MaxAccount, AccountStatus, async_session_factory,
)
from db.plan_limits import check_limit
from web.routes._scope import scope_query
from web.routes.auth_r import get_current_user
from max_client import neurochat

router = APIRouter(prefix="/neurochat")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def page(request: Request, msg: str = "", err: str = ""):
    user = await get_current_user(request)
    async with async_session_factory() as s:
        camps_q = scope_query(select(NeuroCampaign), NeuroCampaign, user).order_by(desc(NeuroCampaign.created_at))
        campaigns = (await s.execute(camps_q)).scalars().all()
        acc_q = scope_query(select(MaxAccount), MaxAccount, user).where(MaxAccount.status == AccountStatus.ACTIVE)
        accounts = (await s.execute(acc_q)).scalars().all()

    running_ids = neurochat.get_running_ids()
    return templates.TemplateResponse(
        request=request,
        name="neurochat.html",
        context={
            "campaigns": campaigns,
            "accounts": accounts,
            "running_ids": running_ids,
            "msg": msg,
            "err": err,
            "modes": [("keywords", "По ключевым словам"), ("respond_all", "Отвечать на всё"), ("scripted", "Сценарный диалог")],
            "styles": [("conversational", "Разговорный"), ("business", "Деловой"), ("friendly", "Дружелюбный"), ("expert", "Экспертный")],
        },
    )


@router.post("/create")
async def create(
    request: Request,
    name: str = Form(...),
    account_id: int = Form(...),
    mode: str = Form("keywords"),
    chat_ids: str = Form(""),
    keywords: str = Form(""),
    support_replies: bool = Form(True),
    product_description: str = Form(""),
    style: str = Form("conversational"),
    mention_frequency: int = Form(30),
    ai_model: str = Form("gpt-4o-mini"),
    system_prompt: str = Form(""),
    delay_min_sec: int = Form(30),
    delay_max_sec: int = Form(120),
    daily_limit: int = Form(50),
):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    # Парсим chat_ids
    parsed_chats = []
    for part in chat_ids.replace("\n", ",").split(","):
        part = part.strip()
        if part:
            try:
                parsed_chats.append(int(part))
            except ValueError:
                pass

    async with async_session_factory() as s:
        # Проверка лимитов
        can, current, lim = await check_limit(s, user, NeuroCampaign, "max_tasks")
        if not can:
            return RedirectResponse(f"/app/neurochat/?err=Лимит кампаний: {current}/{lim}", status_code=303)

        # Аккаунт должен принадлежать пользователю
        acc = await s.get(MaxAccount, account_id)
        if not acc or (acc.owner_id != user.id and not user.is_superadmin):
            return RedirectResponse("/app/neurochat/?err=Аккаунт не найден", status_code=303)

        camp = NeuroCampaign(
            name=name,
            account_id=account_id,
            mode=NeuroMode(mode),
            chat_ids=json.dumps(parsed_chats),
            keywords=keywords,
            support_replies=support_replies,
            product_description=product_description,
            style=NeuroStyle(style),
            mention_frequency=max(1, mention_frequency),
            ai_model=ai_model,
            system_prompt=system_prompt,
            delay_min_sec=max(5, delay_min_sec),
            delay_max_sec=max(delay_min_sec + 1, delay_max_sec),
            daily_limit=max(1, daily_limit),
            owner_id=user.id,
            status=NeuroCampaignStatus.DRAFT,
        )
        s.add(camp)
        await s.commit()

    return RedirectResponse("/app/neurochat/?msg=Кампания создана", status_code=303)


async def _check_owner(campaign_id: int, user) -> NeuroCampaign | None:
    async with async_session_factory() as s:
        camp = await s.get(NeuroCampaign, campaign_id)
    if not camp:
        return None
    if not user.is_superadmin and camp.owner_id != user.id:
        return None
    return camp


@router.post("/{campaign_id}/start")
async def start(campaign_id: int, request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    camp = await _check_owner(campaign_id, user)
    if not camp:
        return RedirectResponse("/app/neurochat/?err=Не найдена", status_code=303)
    ok, msg = await neurochat.start_campaign(campaign_id)
    return RedirectResponse(f"/app/neurochat/?{'msg' if ok else 'err'}={msg}", status_code=303)


@router.post("/{campaign_id}/stop")
async def stop(campaign_id: int, request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    camp = await _check_owner(campaign_id, user)
    if not camp:
        return RedirectResponse("/app/neurochat/?err=Не найдена", status_code=303)
    ok, msg = await neurochat.stop_campaign(campaign_id)
    return RedirectResponse(f"/app/neurochat/?{'msg' if ok else 'err'}={msg}", status_code=303)


@router.post("/{campaign_id}/pause")
async def pause(campaign_id: int, request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    camp = await _check_owner(campaign_id, user)
    if not camp:
        return RedirectResponse("/app/neurochat/?err=Не найдена", status_code=303)
    ok, msg = await neurochat.pause_campaign(campaign_id)
    return RedirectResponse(f"/app/neurochat/?{'msg' if ok else 'err'}={msg}", status_code=303)


@router.post("/{campaign_id}/delete")
async def delete(campaign_id: int, request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    camp = await _check_owner(campaign_id, user)
    if not camp:
        return RedirectResponse("/app/neurochat/?err=Не найдена", status_code=303)
    await neurochat.stop_campaign(campaign_id)
    async with async_session_factory() as s:
        c = await s.get(NeuroCampaign, campaign_id)
        if c:
            await s.delete(c)
            await s.commit()
    return RedirectResponse("/app/neurochat/?msg=Удалено", status_code=303)


@router.get("/{campaign_id}/log", response_class=HTMLResponse)
async def view_log(campaign_id: int, request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    camp = await _check_owner(campaign_id, user)
    if not camp:
        return RedirectResponse("/app/neurochat/?err=Не найдена", status_code=303)
    async with async_session_factory() as s:
        q = select(NeuroChatMessage).where(NeuroChatMessage.campaign_id == campaign_id).order_by(desc(NeuroChatMessage.created_at)).limit(200)
        messages = (await s.execute(q)).scalars().all()
    return templates.TemplateResponse(
        request=request,
        name="neurochat_log.html",
        context={"campaign": camp, "messages": messages},
    )
