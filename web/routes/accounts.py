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

from db.models import MaxAccount, AccountStatus, AccountRole, async_session_factory
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
        err_msg = str(e)[:200]
        logger.warning("qr_start failed for {}: {}", phone, err_msg)
        # Rate limit from MAX — return 429 not 500
        if "no.attempts" in err_msg or "too many" in err_msg.lower() or "попыток" in err_msg.lower():
            return JSONResponse({"error": "Слишком много попыток. Подождите 10-15 минут и попробуйте снова."}, status_code=429)
        # Connection error — proxy or network issue
        if "ConnectionRefused" in err_msg or "Connection refused" in err_msg:
            return JSONResponse({"error": "Не удалось подключиться к MAX. Проверьте прокси или подождите."}, status_code=502)
        return JSONResponse({"error": f"Ошибка: {err_msg}"}, status_code=400)


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
#  TEST SEND — send a test message to self
# ════════════════════════════════════════════════════════════════════

@router.post("/{account_id}/test-send")
async def test_send(request: Request, account_id: int, text: str = Form("🧪 MaxSurge test")):
    """Send a test message to self (own dialog)."""
    user = await get_request_user(request)
    async with async_session_factory() as s:
        acc = await s.get(MaxAccount, account_id)
        if not acc:
            return JSONResponse({"error": "not_found"}, 404)
        if user and not user.is_superadmin and acc.owner_id != user.id:
            return JSONResponse({"error": "forbidden"}, 403)
    try:
        client = await account_manager.get_client(acc.phone)
        if not client:
            return JSONResponse({"error": "not_connected"}, 400)

        me_id = client.me.id if client.me else None
        if not me_id:
            return JSONResponse({"error": "no_me_id"}, 500)

        # Find self dialog (dialog where id == me.id)
        self_dialog = None
        for d in (client.dialogs or []):
            if d.id == me_id:
                self_dialog = d
                break

        # If no self dialog, use first available dialog
        if not self_dialog and client.dialogs:
            self_dialog = client.dialogs[0]
            logger.info("[test-send] no self dialog, using first: {}", self_dialog.id)

        if not self_dialog:
            return JSONResponse({"error": "no_dialogs_available"}, 400)

        from max_client.ops import send_message
        result = await send_message(client, chat_id=self_dialog.id, text=text[:500])
        msg_id = getattr(result, "id", None) if result else None
        return JSONResponse({
            "status": "sent",
            "chat_id": self_dialog.id,
            "message_id": msg_id,
            "text": text[:500],
        })
    except Exception as e:
        err = str(e)[:200]
        logger.exception("test-send failed")
        return JSONResponse({"error": err}, 500)


# ════════════════════════════════════════════════════════════════════
#  HEALTH CHECK — Validity + Restrictions
# ════════════════════════════════════════════════════════════════════

@router.post("/{account_id}/check-validity")
async def check_validity(request: Request, account_id: int):
    """Check if account is alive (can connect + sync)."""
    user = await get_request_user(request)
    async with async_session_factory() as s:
        acc = await s.get(MaxAccount, account_id)
        if not acc:
            return JSONResponse({"error": "not_found"}, 404)
        if user and not user.is_superadmin and acc.owner_id != user.id:
            return JSONResponse({"error": "forbidden"}, 403)
    try:
        client = await account_manager.restore_session(acc.phone)
        if client:
            return JSONResponse({"status": "valid", "phone": acc.phone})
        else:
            return JSONResponse({"status": "invalid", "phone": acc.phone, "error": "restore_failed"})
    except Exception as e:
        return JSONResponse({"status": "invalid", "phone": acc.phone, "error": str(e)[:200]})


@router.post("/{account_id}/check-restrictions")
async def check_restrictions(request: Request, account_id: int):
    """Check if account can send messages."""
    user = await get_request_user(request)
    async with async_session_factory() as s:
        acc = await s.get(MaxAccount, account_id)
        if not acc:
            return JSONResponse({"error": "not_found"}, 404)
        if user and not user.is_superadmin and acc.owner_id != user.id:
            return JSONResponse({"error": "forbidden"}, 403)
    try:
        client = await account_manager.get_client(acc.phone)
        if not client:
            return JSONResponse({"status": "error", "error": "not_connected"})
        from max_client.ops import fetch_chats
        chats = await fetch_chats(client)
        return JSONResponse({"status": "ok", "phone": acc.phone, "chats_count": len(chats) if chats else 0, "can_send": True})
    except Exception as e:
        err = str(e)[:200]
        restricted = any(w in err.lower() for w in ("restricted", "banned", "limit", "forbidden"))
        return JSONResponse({"status": "restricted" if restricted else "error", "phone": acc.phone, "error": err, "can_send": False})


# ════════════════════════════════════════════════════════════════════
#  ACCOUNT CHATS/CHANNELS LIST
# ════════════════════════════════════════════════════════════════════

@router.get("/{account_id}/chats")
async def account_chats(request: Request, account_id: int):
    """List all chats/channels/dialogs for a specific account."""
    user = await get_request_user(request)
    async with async_session_factory() as s:
        acc = await s.get(MaxAccount, account_id)
        if not acc:
            return JSONResponse({"error": "not_found"}, 404)
        if user and not user.is_superadmin and acc.owner_id != user.id:
            return JSONResponse({"error": "forbidden"}, 403)
    try:
        client = await account_manager.get_client(acc.phone)
        if not client:
            return JSONResponse({"error": "not_connected"}, 400)
        result = {
            "phone": acc.phone,
            "chats": [{"id": c.id, "name": getattr(c, "title", getattr(c, "name", "?")), "type": "chat"} for c in (client.chats or [])],
            "channels": [{"id": c.id, "name": getattr(c, "title", getattr(c, "name", "?")), "type": "channel"} for c in (client.channels or [])],
            "dialogs": [{"id": d.id, "name": getattr(d, "title", getattr(d, "name", str(d.id))), "type": "dialog"} for d in (client.dialogs or [])],
        }
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, 500)


# ════════════════════════════════════════════════════════════════════
#  ACCOUNT ROLES/TAGS
# ════════════════════════════════════════════════════════════════════

@router.post("/{account_id}/set-comment")
async def set_comment(request: Request, account_id: int, comment: str = Form("")):
    """Set a free-form comment on the account."""
    user = await get_request_user(request)
    async with async_session_factory() as s:
        acc = await s.get(MaxAccount, account_id)
        if not acc:
            return JSONResponse({"error": "not_found"}, 404)
        if user and not user.is_superadmin and acc.owner_id != user.id:
            return JSONResponse({"error": "forbidden"}, 403)
        acc.comment = (comment or "").strip()[:500] or None
        await s.commit()
    return JSONResponse({"ok": True, "comment": acc.comment or ""})


@router.post("/{account_id}/toggle-active")
async def toggle_active(request: Request, account_id: int):
    """Flip account between ACTIVE and PAUSED (user-controlled on/off)."""
    user = await get_request_user(request)
    async with async_session_factory() as s:
        acc = await s.get(MaxAccount, account_id)
        if not acc:
            return JSONResponse({"error": "not_found"}, 404)
        if user and not user.is_superadmin and acc.owner_id != user.id:
            return JSONResponse({"error": "forbidden"}, 403)
        if acc.status == AccountStatus.ACTIVE:
            acc.status = AccountStatus.PAUSED
        elif acc.status == AccountStatus.PAUSED:
            acc.status = AccountStatus.ACTIVE
        else:
            return JSONResponse({"error": f"cannot_toggle_from_{acc.status.value}", "current": acc.status.value}, 400)
        await s.commit()
        new_status = acc.status.value
    return JSONResponse({"ok": True, "status": new_status})


@router.post("/bulk-check-validity")
async def bulk_check_validity(request: Request, account_ids: str = Form("")):
    """Check validity on multiple accounts in parallel.

    account_ids: comma-separated list of IDs.
    Returns: {"results": [{"id":, "phone":, "status":, "error":}, ...]}
    """
    user = await get_request_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, 401)

    try:
        ids = [int(x) for x in account_ids.split(",") if x.strip()]
    except ValueError:
        return JSONResponse({"error": "bad_ids"}, 400)
    ids = ids[:50]  # cap to avoid abuse

    async with async_session_factory() as s:
        from sqlalchemy import select
        q = select(MaxAccount).where(MaxAccount.id.in_(ids))
        if not user.is_superadmin:
            q = q.where(MaxAccount.owner_id == user.id)
        accs = (await s.execute(q)).scalars().all()

    import asyncio as _asyncio
    async def _check_one(acc):
        try:
            client = await account_manager.restore_session(acc.phone)
            return {"id": acc.id, "phone": acc.phone, "status": "valid" if client else "invalid"}
        except Exception as e:
            return {"id": acc.id, "phone": acc.phone, "status": "invalid", "error": str(e)[:100]}

    results = await _asyncio.gather(*[_check_one(a) for a in accs], return_exceptions=False)
    return JSONResponse({"results": results})


@router.get("/roles")
async def list_roles(request: Request):
    """Return all roles owned by current user (for modal + select dropdown)."""
    user = await get_request_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, 401)
    async with async_session_factory() as s:
        from sqlalchemy import select
        q = select(AccountRole).where(AccountRole.owner_id == user.id).order_by(AccountRole.name)
        roles = (await s.execute(q)).scalars().all()
    return JSONResponse({
        "roles": [{"id": r.id, "name": r.name, "color": r.color} for r in roles]
    })


@router.post("/roles/add")
async def add_role(request: Request, name: str = Form(...), color: str = Form("#64748b")):
    user = await get_request_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, 401)
    name = (name or "").strip()[:64]
    if not name:
        return JSONResponse({"error": "empty_name"}, 400)
    color = (color or "#64748b").strip()[:16]
    async with async_session_factory() as s:
        from sqlalchemy import select
        existing = (await s.execute(
            select(AccountRole).where(AccountRole.owner_id == user.id, AccountRole.name == name)
        )).scalar_one_or_none()
        if existing:
            return JSONResponse({"error": "duplicate", "id": existing.id}, 400)
        role = AccountRole(owner_id=user.id, name=name, color=color)
        s.add(role)
        await s.commit()
        await s.refresh(role)
    return JSONResponse({"ok": True, "id": role.id, "name": role.name, "color": role.color})


@router.post("/roles/{role_id}/update")
async def update_role(request: Request, role_id: int, name: str = Form(...), color: str = Form("#64748b")):
    user = await get_request_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, 401)
    async with async_session_factory() as s:
        role = await s.get(AccountRole, role_id)
        if not role or role.owner_id != user.id:
            return JSONResponse({"error": "not_found"}, 404)
        old_name = role.name
        role.name = (name or "").strip()[:64] or old_name
        role.color = (color or role.color).strip()[:16]
        await s.commit()
        # Cascade rename: update MaxAccount.role
        if old_name != role.name:
            from sqlalchemy import update
            await s.execute(
                update(MaxAccount)
                .where(MaxAccount.owner_id == user.id, MaxAccount.role == old_name)
                .values(role=role.name)
            )
            await s.commit()
    return JSONResponse({"ok": True, "id": role.id, "name": role.name, "color": role.color})


@router.post("/roles/{role_id}/delete")
async def delete_role(request: Request, role_id: int):
    user = await get_request_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, 401)
    async with async_session_factory() as s:
        role = await s.get(AccountRole, role_id)
        if not role or role.owner_id != user.id:
            return JSONResponse({"error": "not_found"}, 404)
        name = role.name
        await s.delete(role)
        await s.commit()
        # Cascade clear MaxAccount.role where it matches
        from sqlalchemy import update
        await s.execute(
            update(MaxAccount)
            .where(MaxAccount.owner_id == user.id, MaxAccount.role == name)
            .values(role="")
        )
        await s.commit()
    return JSONResponse({"ok": True})


@router.post("/bulk-set-role")
async def bulk_set_role(request: Request, account_ids: str = Form(...), role: str = Form("")):
    """Assign same role to multiple accounts. Empty role = clear."""
    user = await get_request_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, 401)
    try:
        ids = [int(x) for x in account_ids.split(",") if x.strip()]
    except ValueError:
        return JSONResponse({"error": "bad_ids"}, 400)
    ids = ids[:200]
    role = (role or "").strip()[:64]
    async with async_session_factory() as s:
        from sqlalchemy import update
        q = update(MaxAccount).where(MaxAccount.id.in_(ids)).values(role=role)
        if not user.is_superadmin:
            q = q.where(MaxAccount.owner_id == user.id)
        await s.execute(q)
        await s.commit()
    return JSONResponse({"ok": True, "updated": len(ids)})


@router.post("/{account_id}/set-role")
async def set_role(request: Request, account_id: int, role: str = Form("")):
    """Set custom role/tag for account."""
    user = await get_request_user(request)
    async with async_session_factory() as s:
        acc = await s.get(MaxAccount, account_id)
        if not acc:
            return RedirectResponse("/app/accounts/?msg=Не+найден", status_code=303)
        if user and not user.is_superadmin and acc.owner_id != user.id:
            return RedirectResponse("/app/accounts/?msg=Нет+доступа", status_code=303)
        acc.role = role.strip()[:32]
        await s.commit()
    return RedirectResponse("/app/accounts/?msg=Роль+обновлена", status_code=303)


# ════════════════════════════════════════════════════════════════════
#  EXPORT ACCOUNTS (JSON/CSV)
# ════════════════════════════════════════════════════════════════════

@router.get("/export/json")
async def export_json(request: Request):
    """Export all accounts as JSON."""
    user = await get_request_user(request)
    async with async_session_factory() as s:
        q = scope_query(select(MaxAccount), MaxAccount, user)
        accounts = (await s.execute(q)).scalars().all()
    data = [
        {"phone": a.phone, "login_token": a.login_token or "", "device_id": a.device_id or "",
         "proxy": a.proxy or "", "role": getattr(a, "role", ""), "profile_name": a.profile_name or "",
         "max_user_id": a.max_user_id, "status": a.status.value}
        for a in accounts
    ]
    return JSONResponse(data, headers={"Content-Disposition": "attachment; filename=max_accounts.json"})


@router.get("/export/csv")
async def export_csv(request: Request):
    """Export all accounts as CSV."""
    import io, csv as _csv
    from fastapi.responses import StreamingResponse
    user = await get_request_user(request)
    async with async_session_factory() as s:
        q = scope_query(select(MaxAccount), MaxAccount, user)
        accounts = (await s.execute(q)).scalars().all()
    output = io.StringIO()
    writer = _csv.writer(output)
    writer.writerow(["phone", "login_token", "device_id", "proxy", "role", "profile_name", "max_user_id", "status"])
    for a in accounts:
        writer.writerow([a.phone, a.login_token or "", a.device_id or "", a.proxy or "",
                         getattr(a, "role", ""), a.profile_name or "", a.max_user_id or "", a.status.value])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=max_accounts.csv"})


# ════════════════════════════════════════════════════════════════════
#  BULK JOIN GROUPS (Max Master 1.4.0 inspired)
# ════════════════════════════════════════════════════════════════════

@router.post("/bulk-join")
async def bulk_join_groups(request: Request, account_id: int = Form(...), links: str = Form(...)):
    """Join multiple groups/channels by invite links. One link per line."""
    user = await get_request_user(request)
    async with async_session_factory() as s:
        acc = await s.get(MaxAccount, account_id)
        if not acc:
            return RedirectResponse("/app/accounts/?msg=Аккаунт+не+найден", status_code=303)
        if user and not user.is_superadmin and acc.owner_id != user.id:
            return RedirectResponse("/app/accounts/?msg=Нет+доступа", status_code=303)
    client = await account_manager.get_client(acc.phone)
    if not client:
        return RedirectResponse("/app/accounts/?msg=Аккаунт+не+подключён", status_code=303)
    import asyncio as _aio
    from max_client.ops import join_group, join_channel
    link_list = [l.strip() for l in links.strip().split("\n") if l.strip()]
    joined, errors = 0, 0
    for link in link_list[:50]:
        try:
            try:
                await join_group(client, link)
            except Exception:
                await join_channel(client, link)
            joined += 1
            await _aio.sleep(2)
        except Exception as e:
            logger.debug("bulk_join failed for {}: {}", link, e)
            errors += 1
    return RedirectResponse(f"/app/accounts/?msg=Вступлено+{joined},+ошибок+{errors}+из+{len(link_list)}", status_code=303)


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
