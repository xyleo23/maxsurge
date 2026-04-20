"""Роуты чекера номеров — legacy (по лидам) + bulk (по произвольному списку)."""
import asyncio
from pathlib import Path
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from web.routes._scope import get_request_user, scope_query
from db.models import Lead, MaxAccount, AccountStatus, async_session_factory
from max_client.checker import (
    run_phone_checker, get_check_status, stop_checker,
    run_bulk_checker, get_bulk_status, stop_bulk_checker,
)

router = APIRouter(prefix="/checker")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

_task: asyncio.Task | None = None
_bulk_task: asyncio.Task | None = None


@router.get("/", response_class=HTMLResponse)
async def checker_page(request: Request, msg: str = ""):
    user = await get_request_user(request)
    async with async_session_factory() as s:
        lwp_q = scope_query(select(func.count(Lead.id)), Lead, user).where(
            Lead.phone.isnot(None), Lead.phone != "", Lead.max_user_id.is_(None)
        )
        leads_with_phone = (await s.execute(lwp_q)).scalar() or 0
        ll_q = scope_query(select(func.count(Lead.id)), Lead, user).where(Lead.max_user_id.isnot(None))
        leads_linked = (await s.execute(ll_q)).scalar() or 0
        acc_q = scope_query(select(MaxAccount), MaxAccount, user).where(
            MaxAccount.status == AccountStatus.ACTIVE
        )
        accounts = (await s.execute(acc_q)).scalars().all()

    return templates.TemplateResponse(request=request, name="checker.html", context={
        "leads_with_phone": leads_with_phone,
        "leads_linked": leads_linked,
        "accounts": accounts,
        "status": get_check_status(),
        "bulk_status": get_bulk_status(),
        "msg": msg,
    })


# ── Legacy — по лидам ────────────────────────────────────
@router.post("/start")
async def start_check(limit: int = Form(20), phone: str = Form("")):
    global _task
    _task = asyncio.create_task(run_phone_checker(limit, phone or None))
    return RedirectResponse("/app/checker/?msg=Чекер+запущен", status_code=303)


@router.post("/stop")
async def stop():
    stop_checker()
    return RedirectResponse("/app/checker/?msg=Остановлен", status_code=303)


@router.get("/status")
async def status():
    return JSONResponse(get_check_status())


# ── Bulk — по произвольному списку ───────────────────────
@router.post("/bulk-start")
async def bulk_start(
    request: Request,
    items: str = Form(...),               # текстарея: по одному на строку
    account_phones: str = Form(""),       # csv выбранных аккаунтов (phone)
    mode: str = Form("soft"),             # soft | mass | userid
    pause_from: int = Form(20),
    pause_to: int = Form(30),
    limit_per_account: int = Form(50),
):
    """Запустить фоновый чекер по произвольному списку номеров или User ID."""
    user = await get_request_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, 401)

    # Parse items from textarea
    lines = [ln.strip() for ln in (items or "").splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        return JSONResponse({"error": "empty_list"}, 400)
    lines = lines[:10000]  # safety cap

    # Parse account phones (csv or "auto")
    phones: list[str] = []
    if account_phones.strip():
        phones = [p.strip() for p in account_phones.split(",") if p.strip()]

    # Default to all active accounts of this user if none specified
    if not phones:
        async with async_session_factory() as s:
            q = scope_query(select(MaxAccount), MaxAccount, user).where(
                MaxAccount.status == AccountStatus.ACTIVE
            )
            phones = [a.phone for a in (await s.execute(q)).scalars().all()]
    if not phones:
        return JSONResponse({"error": "no_active_accounts"}, 400)

    # Validate ownership — user can only use their own accounts
    if not getattr(user, "is_superadmin", False):
        async with async_session_factory() as s:
            q = select(MaxAccount.phone).where(
                MaxAccount.owner_id == user.id, MaxAccount.phone.in_(phones)
            )
            owned = set((await s.execute(q)).scalars().all())
        phones = [p for p in phones if p in owned]
        if not phones:
            return JSONResponse({"error": "no_owned_accounts"}, 400)

    if mode not in ("soft", "mass", "userid"):
        mode = "soft"

    # Clamp inputs
    pause_from = max(0, min(pause_from, 300))
    pause_to = max(pause_from, min(pause_to, 600))
    limit_per_account = max(1, min(limit_per_account, 500))

    global _bulk_task
    if _bulk_task and not _bulk_task.done():
        return JSONResponse({"error": "already_running"}, 409)

    _bulk_task = asyncio.create_task(run_bulk_checker(
        items=lines,
        account_phones=phones,
        mode=mode,
        pause_from=pause_from,
        pause_to=pause_to,
        limit_per_account=limit_per_account,
    ))
    return JSONResponse({
        "ok": True,
        "total": len(lines),
        "accounts": phones,
        "mode": mode,
    })


@router.post("/bulk-stop")
async def bulk_stop():
    stop_bulk_checker()
    return JSONResponse({"ok": True})


@router.get("/bulk-status")
async def bulk_status():
    return JSONResponse(get_bulk_status())


@router.get("/bulk-export")
async def bulk_export():
    """Выгрузить CSV с результатами последнего прогона."""
    from fastapi.responses import Response
    import io
    import csv
    data = get_bulk_status()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["input", "status", "user_id", "account", "error"])
    for r in data.get("results", []):
        w.writerow([
            r.get("input", ""),
            r.get("status", ""),
            r.get("user_id", ""),
            r.get("account", ""),
            r.get("error", ""),
        ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=max-checker-results.csv"},
    )
