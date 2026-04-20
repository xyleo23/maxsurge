"""Запланированные посты в каналы/группы MAX."""
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, and_, or_

from db.models import ScheduledPost, PostStatus, MaxAccount, AccountStatus, async_session_factory
from web.routes._scope import get_request_user, scope_query

router = APIRouter(prefix="/posts")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def posts_page(request: Request, msg: str = ""):
    user = await get_request_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    async with async_session_factory() as s:
        # User's accounts for selector
        acc_q = scope_query(select(MaxAccount), MaxAccount, user).where(
            MaxAccount.status == AccountStatus.ACTIVE
        )
        accounts = (await s.execute(acc_q)).scalars().all()

    return templates.TemplateResponse(request=request, name="posts.html", context={
        "accounts": accounts,
        "msg": msg,
    })


@router.get("/list")
async def list_posts(request: Request, from_date: str = "", to_date: str = ""):
    """JSON list of posts for calendar rendering."""
    user = await get_request_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, 401)

    # Default: window ±30 days
    now = datetime.utcnow()
    try:
        frm = datetime.fromisoformat(from_date) if from_date else now - timedelta(days=7)
        to  = datetime.fromisoformat(to_date)   if to_date   else now + timedelta(days=60)
    except ValueError:
        frm = now - timedelta(days=7)
        to  = now + timedelta(days=60)

    async with async_session_factory() as s:
        q = scope_query(select(ScheduledPost), ScheduledPost, user).where(
            ScheduledPost.scheduled_at >= frm,
            ScheduledPost.scheduled_at <= to,
        ).order_by(ScheduledPost.scheduled_at)
        posts = (await s.execute(q)).scalars().all()

    return JSONResponse({
        "posts": [{
            "id": p.id,
            "account_id": p.account_id,
            "chat_id": p.chat_id,
            "chat_name": p.chat_name or "",
            "body": p.body,
            "attachment_url": p.attachment_url,
            "scheduled_at": p.scheduled_at.isoformat() if p.scheduled_at else None,
            "status": p.status,
            "error": p.error,
            "posted_at": p.posted_at.isoformat() if p.posted_at else None,
        } for p in posts]
    })


@router.post("/add")
async def add_post(
    request: Request,
    account_id: int = Form(...),
    chat_id: int = Form(...),
    chat_name: str = Form(""),
    body: str = Form(...),
    attachment_url: str = Form(""),
    scheduled_at: str = Form(...),   # ISO
):
    user = await get_request_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, 401)

    try:
        when = datetime.fromisoformat(scheduled_at)
    except ValueError:
        return JSONResponse({"error": "bad_datetime"}, 400)

    body = (body or "").strip()
    if not body:
        return JSONResponse({"error": "empty_body"}, 400)

    async with async_session_factory() as s:
        # Verify account ownership
        acc = await s.get(MaxAccount, account_id)
        if not acc or (acc.owner_id != user.id and not user.is_superadmin):
            return JSONResponse({"error": "forbidden_account"}, 403)

        p = ScheduledPost(
            owner_id=user.id,
            account_id=account_id,
            chat_id=chat_id,
            chat_name=(chat_name or "")[:256] or None,
            body=body[:10000],
            attachment_url=(attachment_url or "").strip()[:512] or None,
            scheduled_at=when,
            status=PostStatus.PENDING.value,
        )
        s.add(p)
        await s.commit()
        await s.refresh(p)

    return JSONResponse({"ok": True, "id": p.id})


@router.post("/{post_id}/update")
async def update_post(
    request: Request, post_id: int,
    body: str = Form(""),
    scheduled_at: str = Form(""),
):
    user = await get_request_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, 401)

    async with async_session_factory() as s:
        p = await s.get(ScheduledPost, post_id)
        if not p or (p.owner_id != user.id and not user.is_superadmin):
            return JSONResponse({"error": "not_found"}, 404)
        if p.status != PostStatus.PENDING.value:
            return JSONResponse({"error": "already_" + p.status}, 400)
        if body:
            p.body = body[:10000]
        if scheduled_at:
            try:
                p.scheduled_at = datetime.fromisoformat(scheduled_at)
            except ValueError:
                pass
        await s.commit()
    return JSONResponse({"ok": True})


@router.post("/{post_id}/delete")
async def delete_post(request: Request, post_id: int):
    user = await get_request_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, 401)
    async with async_session_factory() as s:
        p = await s.get(ScheduledPost, post_id)
        if not p or (p.owner_id != user.id and not user.is_superadmin):
            return JSONResponse({"error": "not_found"}, 404)
        await s.delete(p)
        await s.commit()
    return JSONResponse({"ok": True})


@router.get("/account-chats/{account_id}")
async def account_chats(request: Request, account_id: int):
    """Get chats/channels the account can post to (admin/owner role)."""
    user = await get_request_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, 401)

    async with async_session_factory() as s:
        acc = await s.get(MaxAccount, account_id)
        if not acc or (acc.owner_id != user.id and not user.is_superadmin):
            return JSONResponse({"error": "forbidden"}, 403)

    try:
        from max_client.account import account_manager
        client = await account_manager.get_client(acc.phone)
        if not client:
            return JSONResponse({"error": "not_connected"}, 400)
        my_uid = acc.max_user_id or getattr(client, "user_id", None)

        def _role(ch) -> str:
            if my_uid is None:
                return "member"
            if getattr(ch, "owner", None) == my_uid:
                return "owner"
            if my_uid in (getattr(ch, "admins", None) or []):
                return "admin"
            return "member"

        result = []
        for c in (client.chats or []) + (client.channels or []):
            role = _role(c)
            # Only expose chats where we can post (owner/admin)
            if role in ("owner", "admin"):
                result.append({
                    "id": c.id,
                    "name": getattr(c, "title", getattr(c, "name", "?")),
                    "role": role,
                    "is_channel": c in (client.channels or []),
                })
        return JSONResponse({"chats": result})
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, 500)
