"""Dual-pane импорт контактов из групп MAX → Lead."""
from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from db.models import Lead, LeadStatus, MaxAccount, AccountStatus, async_session_factory
from web.routes._scope import get_request_user, scope_query
from max_client.account import account_manager

router = APIRouter(prefix="/import-contacts")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def page(request: Request, msg: str = ""):
    user = await get_request_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    async with async_session_factory() as s:
        acc_q = scope_query(select(MaxAccount), MaxAccount, user).where(
            MaxAccount.status == AccountStatus.ACTIVE
        )
        accounts = (await s.execute(acc_q)).scalars().all()
    return templates.TemplateResponse(request=request, name="import_contacts.html", context={
        "accounts": accounts,
        "msg": msg,
    })


@router.get("/chats/{account_id}")
async def list_chats(request: Request, account_id: int):
    """All chats/channels the account is a member of."""
    user = await get_request_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, 401)
    async with async_session_factory() as s:
        acc = await s.get(MaxAccount, account_id)
        if not acc or (acc.owner_id != user.id and not user.is_superadmin):
            return JSONResponse({"error": "forbidden"}, 403)
    try:
        client = await account_manager.get_client(acc.phone)
        if not client:
            return JSONResponse({"error": "not_connected"}, 400)
        chats = [{
            "id": c.id,
            "name": getattr(c, "title", getattr(c, "name", "?")),
            "type": "chat",
            "members": getattr(c, "participants_count", None) or getattr(c, "members_count", None),
        } for c in (client.chats or [])]
        channels = [{
            "id": c.id,
            "name": getattr(c, "title", getattr(c, "name", "?")),
            "type": "channel",
            "members": getattr(c, "participants_count", None) or getattr(c, "members_count", None),
        } for c in (client.channels or [])]
        return JSONResponse({"chats": chats + channels})
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, 500)


@router.get("/members/{account_id}/{chat_id}")
async def list_members(request: Request, account_id: int, chat_id: int, limit: int = 2000):
    """Fetch members of a specific chat via existing parser."""
    user = await get_request_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, 401)
    async with async_session_factory() as s:
        acc = await s.get(MaxAccount, account_id)
        if not acc or (acc.owner_id != user.id and not user.is_superadmin):
            return JSONResponse({"error": "forbidden"}, 403)

    try:
        from max_client.parser import parse_chat_members
        client = await account_manager.get_client(acc.phone)
        if not client:
            return JSONResponse({"error": "not_connected"}, 400)

        members = await parse_chat_members(client, chat_id, max_count=max(100, min(limit, 10000)))
        out = []
        for m in members:
            out.append({
                "user_id": m.get("userId") or m.get("id"),
                "first_name": m.get("firstName", ""),
                "last_name": m.get("lastName", ""),
                "phone": m.get("phone", ""),
                "username": m.get("username") or m.get("login") or "",
            })
        return JSONResponse({"members": out, "total": len(out)})
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, 500)


@router.post("/commit")
async def commit(
    request: Request,
    selected: str = Form(...),          # csv of user_ids
    source_label: str = Form("import"),
    members_json: str = Form(""),        # client sends full dicts
):
    """Create Lead records from selected user_ids.

    Expects members_json as a list of {user_id, first_name, last_name, phone}.
    Only items whose user_id is in `selected` will be imported.
    """
    import json
    user = await get_request_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, 401)

    try:
        selected_ids = {int(x) for x in selected.split(",") if x.strip()}
        members = json.loads(members_json) if members_json else []
    except Exception as e:
        return JSONResponse({"error": f"bad_payload: {e}"}, 400)

    if not selected_ids:
        return JSONResponse({"error": "empty_selection"}, 400)

    selected_ids.discard(0)
    selected_ids.discard(None)

    created = 0
    skipped_dupe = 0

    async with async_session_factory() as s:
        # Dedup: don't create if this user already has a Lead with same max_user_id
        existing_q = select(Lead.max_user_id).where(
            Lead.owner_id == user.id,
            Lead.max_user_id.in_(list(selected_ids)),
        )
        existing = {uid for uid in (await s.execute(existing_q)).scalars().all() if uid}

        for m in members:
            uid = m.get("user_id")
            if not uid or int(uid) not in selected_ids:
                continue
            uid = int(uid)
            if uid in existing:
                skipped_dupe += 1
                continue
            full_name = (str(m.get("first_name") or "") + " " + str(m.get("last_name") or "")).strip()
            lead = Lead(
                owner_id=user.id,
                max_user_id=uid,
                name=full_name[:256] or None,
                phone=(m.get("phone") or "")[:32] or None,
                source=source_label[:64],
                status=LeadStatus.NEW,
            )
            s.add(lead)
            existing.add(uid)
            created += 1

        await s.commit()

    return JSONResponse({
        "ok": True,
        "created": created,
        "skipped_dupe": skipped_dupe,
        "total_selected": len(selected_ids),
    })
