"""Webhook CRUD — настройки webhook-эндпоинтов + тестовая отправка.

Роуты:
  GET  /app/webhooks         — UI-страница настроек (Jinja)
  POST /app/webhooks/create  — создать эндпоинт (form)
  POST /app/webhooks/delete  — удалить (form)
  POST /app/webhooks/toggle  — вкл/выкл (form)
  POST /app/webhooks/test    — тестовая отправка (JSON)
  GET  /app/webhooks/logs    — последние 50 доставок (JSON)

Документация для внешних разработчиков: /help/webhook-api
"""
import json
import secrets
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, select

from db.models import async_session_factory as asf
from db.models_webhook import WebhookEndpoint, WebhookLog
from max_client.webhook_dispatcher import WEBHOOK_EVENTS, dispatch_webhook

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _get_user(request: Request):
    return getattr(request.state, "user", None)


@router.get("/webhooks", response_class=HTMLResponse)
async def webhooks_page(request: Request):
    user = _get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    async with asf() as s:
        result = await s.execute(
            select(WebhookEndpoint)
            .where(WebhookEndpoint.owner_id == user.id)
            .order_by(WebhookEndpoint.created_at.desc())
        )
        endpoints = result.scalars().all()
    return templates.TemplateResponse(request=request, name="webhooks.html", context={
        "endpoints": endpoints,
        "events": WEBHOOK_EVENTS,
        "user": user,
    })


@router.post("/webhooks/create")
async def create_webhook(request: Request, url: str = Form(...), events: str = Form("*")):
    user = _get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    secret = secrets.token_hex(32)
    async with asf() as s:
        ep = WebhookEndpoint(
            owner_id=user.id,
            url=url.strip(),
            secret=secret,
            events=events.strip() or "*",
            active=True,
        )
        s.add(ep)
        await s.commit()
    return RedirectResponse("/app/webhooks", status_code=303)


@router.post("/webhooks/delete")
async def delete_webhook(request: Request, endpoint_id: int = Form(...)):
    user = _get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    async with asf() as s:
        ep = await s.get(WebhookEndpoint, endpoint_id)
        if ep and ep.owner_id == user.id:
            await s.delete(ep)
            await s.commit()
    return RedirectResponse("/app/webhooks", status_code=303)


@router.post("/webhooks/toggle")
async def toggle_webhook(request: Request, endpoint_id: int = Form(...)):
    user = _get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    async with asf() as s:
        ep = await s.get(WebhookEndpoint, endpoint_id)
        if ep and ep.owner_id == user.id:
            ep.active = not ep.active
            await s.commit()
    return RedirectResponse("/app/webhooks", status_code=303)


@router.post("/webhooks/test")
async def test_webhook(request: Request, endpoint_id: int = Form(...)):
    user = _get_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    async with asf() as s:
        ep = await s.get(WebhookEndpoint, endpoint_id)
        if not ep or ep.owner_id != user.id:
            return JSONResponse({"error": "not found"}, status_code=404)
    n = await dispatch_webhook(user.id, "test_ping", {
        "message": "Тестовый вебхук от MaxSurge",
        "endpoint_id": endpoint_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    })
    return JSONResponse({"ok": True, "dispatched_to": n})


@router.get("/webhooks/logs")
async def webhook_logs(request: Request):
    user = _get_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    async with asf() as s:
        eps = await s.execute(
            select(WebhookEndpoint.id).where(WebhookEndpoint.owner_id == user.id)
        )
        ep_ids = [r[0] for r in eps.fetchall()]
        if not ep_ids:
            return JSONResponse({"logs": []})
        logs = await s.execute(
            select(WebhookLog)
            .where(WebhookLog.endpoint_id.in_(ep_ids))
            .order_by(WebhookLog.created_at.desc())
            .limit(50)
        )
        rows = logs.scalars().all()
    return JSONResponse({"logs": [
        {
            "id": r.id,
            "endpoint_id": r.endpoint_id,
            "event": r.event_type,
            "status_code": r.status_code,
            "success": r.success,
            "response_ms": r.response_ms,
            "error": r.error,
            "attempt": r.attempt,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in rows
    ]})
