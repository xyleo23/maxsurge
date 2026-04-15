"""Управление MAX аккаунтами — QR login, Token import, Session file import.

MAX отключил phone-auth через WS API в 25.12.13+. Доступные методы:
1. QR login (web.max.ru flow) — юзер сканирует QR с телефона
2. Token import — купленный аккаунт с готовым login_token + device_id
3. Session file (.db) — PyMax/Max Sheiker совместимый файл
"""
import json
from pathlib import Path

from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from loguru import logger
from sqlalchemy import select

from db.models import MaxAccount, async_session_factory
from db.plan_limits import check_limit
from max_client.account import account_manager
from web.routes._scope import get_request_user, scope_query

router = APIRouter(prefix="/accounts")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def accounts_list(request: Request, msg: str = ""):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        q = scope_query(select(MaxAccount), MaxAccount, user).order_by(MaxAccount.created_at.desc())
        accounts = (await s.execute(q)).scalars().all()
        can_add, current, limit = await check_limit(s, user, MaxAccount, "max_accounts")
    return templates.TemplateResponse(request=request, name="accounts.html", context={
        "accounts": accounts,
        "msg": msg,
        "can_add": can_add,
        "current_count": current,
        "limit": limit,
    })


async def _set_owner(phone: str, user_id: int | None):
    if user_id is None:
        return
    async with async_session_factory() as s:
        acc = (await s.execute(select(MaxAccount).where(MaxAccount.phone == phone))).scalar_one_or_none()
        if acc and acc.owner_id is None:
            acc.owner_id = user_id
            await s.commit()


# ════════════════════════════════════════════════════════════════════
#  QR LOGIN FLOW
# ════════════════════════════════════════════════════════════════════

@router.post("/qr/start")
async def qr_start(request: Request, phone: str = Form(...), proxy: str = Form("")):
    """Стартует QR login session. Возвращает JSON с путём к QR PNG."""
    user = await get_request_user(request)
    if not user:
        return JSONResponse({"error": "auth_required"}, status_code=401)

    async with async_session_factory() as s:
        can_add, current, limit = await check_limit(s, user, MaxAccount, "max_accounts")
    if not can_add:
        return JSONResponse({
            "error": f"Достигнут лимит аккаунтов ({current}/{limit}). Обновите тариф."
        }, status_code=403)

    phone = phone.strip()
    if not phone.startswith("+"):
        phone = "+" + phone.lstrip("+")

    proxy_url = proxy.strip() or None

    try:
        data = await account_manager.start_qr_login(phone=phone, proxy=proxy_url)
        return JSONResponse({
            "ok": True,
            "track_id": data["track_id"],
            "qr_png": data["qr_png"],
            "qr_link": data["qr_link"],
            "expires_at": data["expires_at"],
            "poll_interval": data["poll_interval"],
            "phone": phone,
        })
    except Exception as e:
        logger.exception("qr_start failed for {}", phone)
        return JSONResponse({"error": f"Ошибка: {str(e)[:200]}"}, status_code=500)


@router.post("/qr/poll")
async def qr_poll(request: Request, phone: str = Form(...)):
    """Проверяет статус QR login. Вызывается клиентом по интервалу."""
    user = await get_request_user(request)
    if not user:
        return JSONResponse({"error": "auth_required"}, status_code=401)

    phone = phone.strip()
    if not phone.startswith("+"):
        phone = "+" + phone.lstrip("+")

    try:
        result = await account_manager.poll_qr_login(phone)
        if result.get("status") == "confirmed":
            # Назначаем owner
            confirmed_phone = result.get("profile", {}).get("phone") or phone
            await _set_owner(confirmed_phone, user.id)
        return JSONResponse(result)
    except Exception as e:
        logger.exception("qr_poll failed for {}", phone)
        return JSONResponse({"status": "error", "error": str(e)[:200]}, status_code=500)


@router.post("/qr/cancel")
async def qr_cancel(request: Request, phone: str = Form(...)):
    """Отменяет активную QR login сессию."""
    user = await get_request_user(request)
    if not user:
        return JSONResponse({"error": "auth_required"}, status_code=401)

    phone = phone.strip()
    if not phone.startswith("+"):
        phone = "+" + phone.lstrip("+")
    await account_manager.cancel_qr_login(phone)
    return JSONResponse({"ok": True})


# ════════════════════════════════════════════════════════════════════
#  TOKEN IMPORT (для купленных аккаунтов)
# ════════════════════════════════════════════════════════════════════

@router.post("/add-by-token")
async def add_by_token(
    request: Request,
    phone: str = Form(...),
    login_token: str = Form(...),
    device_id: str = Form(""),
    proxy: str = Form(""),
    app_version: str = Form("25.12.13"),
):
    """Импортирует MAX аккаунт по готовому токену (купленный на marketplace)."""
    user = await get_request_user(request)

    async with async_session_factory() as s:
        can_add, current, limit = await check_limit(s, user, MaxAccount, "max_accounts")
    if not can_add:
        return RedirectResponse(
            f"/app/accounts/?msg=Лимит+({current}/{limit}).+Обновите+тариф.",
            status_code=303,
        )

    phone = phone.strip()
    if not phone.startswith("+"):
        phone = "+" + phone.lstrip("+")
    login_token = login_token.strip()
    device_id = device_id.strip() or None
    proxy_url = proxy.strip() or None

    try:
        result = await account_manager.add_by_token(
            phone=phone,
            login_token=login_token,
            device_id=device_id,
            proxy=proxy_url,
            app_version=app_version.strip() or "25.12.13",
            owner_id=user.id if user else None,
        )
        name = result.get("profile_name", phone)
        return RedirectResponse(
            f"/app/accounts/?msg=Аккаунт+{name}+({phone})+добавлен+по+токену",
            status_code=303,
        )
    except Exception as e:
        logger.exception("add_by_token failed for {}", phone)
        return RedirectResponse(
            f"/app/accounts/?msg=Ошибка+импорта:+{str(e)[:100]}",
            status_code=303,
        )


# ════════════════════════════════════════════════════════════════════
#  SESSION FILE IMPORT (.db файл)
# ════════════════════════════════════════════════════════════════════

@router.post("/add-by-session")
async def add_by_session(
    request: Request,
    phone: str = Form(...),
    proxy: str = Form(""),
    session_file: UploadFile = File(...),
):
    """Импортирует аккаунт из session.db файла (PyMax / Max Sheiker format)."""
    user = await get_request_user(request)

    async with async_session_factory() as s:
        can_add, current, limit = await check_limit(s, user, MaxAccount, "max_accounts")
    if not can_add:
        return RedirectResponse(
            f"/app/accounts/?msg=Лимит+({current}/{limit}).+Обновите+тариф.",
            status_code=303,
        )

    phone = phone.strip()
    if not phone.startswith("+"):
        phone = "+" + phone.lstrip("+")
    proxy_url = proxy.strip() or None

    try:
        content = await session_file.read()
        if len(content) < 100 or len(content) > 10 * 1024 * 1024:
            raise ValueError("Файл пустой или слишком большой")

        result = await account_manager.add_by_session_file(
            phone=phone,
            session_db_bytes=content,
            proxy=proxy_url,
            owner_id=user.id if user else None,
        )
        name = result.get("profile_name", phone)
        return RedirectResponse(
            f"/app/accounts/?msg=Аккаунт+{name}+импортирован+из+session.db",
            status_code=303,
        )
    except Exception as e:
        logger.exception("add_by_session failed for {}", phone)
        return RedirectResponse(
            f"/app/accounts/?msg=Ошибка+импорта+файла:+{str(e)[:100]}",
            status_code=303,
        )


# ════════════════════════════════════════════════════════════════════
#  Bulk import (CSV) — phone,login_token,device_id[,proxy]
# ════════════════════════════════════════════════════════════════════

@router.post("/bulk-import")
async def bulk_import(
    request: Request,
    csv_file: UploadFile = File(...),
    default_proxy: str = Form(""),
):
    """
    Массовый импорт аккаунтов из CSV.

    Формат CSV (с заголовком):
    phone,login_token,device_id,proxy
    +79001234567,eyJhbGc...,uuid-here,http://user:pass@host:port
    +79002345678,eyJhbGc...,uuid-here,
    """
    import csv as _csv
    import io

    user = await get_request_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    try:
        content = (await csv_file.read()).decode("utf-8")
    except Exception as e:
        return RedirectResponse(f"/app/accounts/?msg=Невалидный+CSV:+{e}", status_code=303)

    reader = _csv.DictReader(io.StringIO(content))
    imported, errors = 0, []
    default_proxy = default_proxy.strip() or None

    for row in reader:
        phone = (row.get("phone") or "").strip()
        token = (row.get("login_token") or row.get("token") or "").strip()
        device_id = (row.get("device_id") or row.get("device") or "").strip() or None
        proxy = (row.get("proxy") or "").strip() or default_proxy

        if not phone or not token:
            errors.append(f"{phone}: missing phone or token")
            continue
        if not phone.startswith("+"):
            phone = "+" + phone.lstrip("+")

        # Check limit each iteration
        async with async_session_factory() as s:
            can_add, current, limit = await check_limit(s, user, MaxAccount, "max_accounts")
        if not can_add:
            errors.append(f"{phone}: limit {current}/{limit}")
            break

        try:
            await account_manager.add_by_token(
                phone=phone,
                login_token=token,
                device_id=device_id,
                proxy=proxy,
                owner_id=user.id,
            )
            imported += 1
        except Exception as e:
            errors.append(f"{phone}: {str(e)[:80]}")

    summary = f"Импортировано+{imported}"
    if errors:
        summary += f",+ошибок+{len(errors)}"
    return RedirectResponse(f"/app/accounts/?msg={summary}", status_code=303)


# ════════════════════════════════════════════════════════════════════
#  LEGACY SMS endpoints — удалены (MAX отключил phone-auth)
#  Оставлены заглушки чтобы формы не падали на 404
# ════════════════════════════════════════════════════════════════════

@router.post("/request-sms")
async def request_sms_deprecated(request: Request, phone: str = Form("")):
    return RedirectResponse(
        "/app/accounts/?msg=SMS-авторизация+отключена+MAX'ом.+Используйте+QR+или+токен.",
        status_code=303,
    )


@router.post("/verify-sms")
async def verify_sms_deprecated(request: Request, phone: str = Form(""), code: str = Form("")):
    return RedirectResponse(
        "/app/accounts/?msg=SMS-авторизация+отключена+MAX'ом.+Используйте+QR+или+токен.",
        status_code=303,
    )


# ════════════════════════════════════════════════════════════════════
#  Account management (unchanged)
# ════════════════════════════════════════════════════════════════════

@router.post("/{account_id}/delete")
async def delete_account(request: Request, account_id: int):
    user = await get_request_user(request)
    async with async_session_factory() as session:
        acc = await session.get(MaxAccount, account_id)
        if not acc:
            return RedirectResponse("/app/accounts/?msg=Аккаунт+не+найден", status_code=303)
        if user and not user.is_superadmin and acc.owner_id != user.id:
            return RedirectResponse("/app/accounts/?msg=Нет+доступа", status_code=303)
    await account_manager.delete_account(account_id)
    return RedirectResponse("/app/accounts/?msg=Аккаунт+удалён", status_code=303)


@router.post("/{account_id}/reset-counter")
async def reset_counter(request: Request, account_id: int):
    user = await get_request_user(request)
    async with async_session_factory() as session:
        acc = await session.get(MaxAccount, account_id)
        if not acc:
            return RedirectResponse("/app/accounts/?msg=Аккаунт+не+найден", status_code=303)
        if user and not user.is_superadmin and acc.owner_id != user.id:
            return RedirectResponse("/app/accounts/?msg=Нет+доступа", status_code=303)
        acc.sent_today = 0
        await session.commit()
    return RedirectResponse(f"/app/accounts/?msg=Счётчик+сброшен", status_code=303)


@router.post("/{account_id}/set-proxy")
async def set_proxy(request: Request, account_id: int, proxy: str = Form("")):
    """Обновить proxy для аккаунта."""
    user = await get_request_user(request)
    async with async_session_factory() as session:
        acc = await session.get(MaxAccount, account_id)
        if not acc:
            return RedirectResponse("/app/accounts/?msg=Аккаунт+не+найден", status_code=303)
        if user and not user.is_superadmin and acc.owner_id != user.id:
            return RedirectResponse("/app/accounts/?msg=Нет+доступа", status_code=303)
        acc.proxy = proxy.strip() or None
        await session.commit()
    return RedirectResponse("/app/accounts/?msg=Прокси+обновлён", status_code=303)
