"""Управление MAX аккаунтами (с изоляцией и лимитами)."""
from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from db.models import MaxAccount, async_session_factory
from db.plan_limits import check_limit
from max_client.account import account_manager
from web.routes._scope import get_request_user, scope_query

router = APIRouter(prefix="/accounts")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

_pending_sms: dict[str, str] = {}


@router.get("/", response_class=HTMLResponse)
async def accounts_list(request: Request, msg: str = ""):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        q = scope_query(select(MaxAccount), MaxAccount, user).order_by(MaxAccount.created_at.desc())
        accounts = (await s.execute(q)).scalars().all()
        can_add, current, limit = await check_limit(s, user, MaxAccount, "max_accounts")
    return templates.TemplateResponse(request=request, name="accounts.html", context={
        "accounts": accounts,
        "pending_phones": list(_pending_sms.keys()),
        "msg": msg,
        "can_add": can_add,
        "current_count": current,
        "limit": limit,
    })


async def _set_owner(phone: str, user_id: int | None):
    """Установить owner_id на аккаунте после создания."""
    if user_id is None:
        return
    async with async_session_factory() as s:
        acc = (await s.execute(select(MaxAccount).where(MaxAccount.phone == phone))).scalar_one_or_none()
        if acc and acc.owner_id is None:
            acc.owner_id = user_id
            await s.commit()


@router.post("/request-sms")
async def request_sms(request: Request, phone: str = Form(...)):
    user = await get_request_user(request)
    # Проверяем лимит
    async with async_session_factory() as s:
        can_add, current, limit = await check_limit(s, user, MaxAccount, "max_accounts")
    if not can_add:
        return RedirectResponse(
            f"/app/accounts/?msg=Достигнут+лимит+аккаунтов+({current}/{limit}).+Обновите+тариф.",
            status_code=303,
        )

    phone = phone.strip()
    try:
        sms_token = await account_manager.request_sms(phone)
        _pending_sms[phone] = sms_token
        return RedirectResponse(f"/app/accounts/?msg=SMS+отправлен+на+{phone}", status_code=303)
    except Exception as e:
        return RedirectResponse(f"/app/accounts/?msg=Ошибка:+{str(e)[:80]}", status_code=303)


@router.post("/verify-sms")
async def verify_sms(request: Request, phone: str = Form(...), code: str = Form(...)):
    user = await get_request_user(request)
    phone = phone.strip()
    try:
        result = await account_manager.verify_sms(phone, code.strip())
        _pending_sms.pop(phone, None)
        # Назначаем owner
        if user:
            await _set_owner(phone, user.id)
        name = result.get("profile_name", phone)
        return RedirectResponse(f"/app/accounts/?msg=Аккаунт+{name}+добавлен", status_code=303)
    except Exception as e:
        return RedirectResponse(f"/app/accounts/?msg=Ошибка+верификации:+{str(e)[:80]}", status_code=303)


@router.post("/{account_id}/delete")
async def delete_account(request: Request, account_id: int):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        acc = await s.get(MaxAccount, account_id)
        if not acc:
            return RedirectResponse("/app/accounts/", status_code=303)
        # Только владелец или админ
        if not (getattr(user, "is_superadmin", False) or acc.owner_id == (user.id if user else None)):
            return RedirectResponse("/app/accounts/?msg=Нет+доступа", status_code=303)
    await account_manager.delete_account(account_id)
    return RedirectResponse("/app/accounts/", status_code=303)


@router.post("/{account_id}/reset-counter")
async def reset_counter(request: Request, account_id: int):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        acc = await s.get(MaxAccount, account_id)
        if acc and (getattr(user, "is_superadmin", False) or acc.owner_id == (user.id if user else None)):
            acc.sent_today = 0
            await s.commit()
    return RedirectResponse("/app/accounts/", status_code=303)


@router.post("/add-by-token")
async def add_by_token(request: Request, login_token: str = Form(...), phone: str = Form("")):
    user = await get_request_user(request)
    # Проверяем лимит
    async with async_session_factory() as s:
        can_add, current, limit = await check_limit(s, user, MaxAccount, "max_accounts")
    if not can_add:
        return RedirectResponse(
            f"/app/accounts/?msg=Достигнут+лимит+аккаунтов+({current}/{limit})",
            status_code=303,
        )

    login_token = login_token.strip()
    phone = phone.strip() or None
    try:
        result = await account_manager.add_by_token(login_token, phone)
        added_phone = result.get("phone")
        if user and added_phone:
            await _set_owner(added_phone, user.id)
        name = result.get("profile_name") or added_phone
        return RedirectResponse(f"/app/accounts/?msg=Аккаунт+{name}+добавлен+по+токену", status_code=303)
    except Exception as e:
        return RedirectResponse(f"/app/accounts/?msg=Ошибка+импорта:+{str(e)[:80]}", status_code=303)
