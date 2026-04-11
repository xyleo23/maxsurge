"""Public API для приёма лидов от userscript/расширения.

Аутентификация через Bearer-токен (SiteUser.api_key).
Позволяет пользователю парсить 2GIS локально в браузере и слать
результаты на сервер — обходит блокировку IP сервера.
"""
import secrets
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException, Form, Depends
from fastapi.responses import JSONResponse, PlainTextResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import select

from db.models import SiteUser, Lead, LeadStatus, async_session_factory
from db.plan_limits import check_limit
from web.routes.auth_r import get_current_user

router = APIRouter()
templates_obj = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


class IngestLead(BaseModel):
    name: str
    address: str | None = None
    city: str | None = None
    phone: str | None = None
    website: str | None = None
    categories: str | None = None
    source_query: str | None = None
    dgis_id: str | None = None


class IngestBatch(BaseModel):
    leads: list[IngestLead]


async def _user_by_api_key(request: Request) -> SiteUser:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401, "Bearer token required")
    token = auth.split(None, 1)[1].strip()
    if not token:
        raise HTTPException(401, "Empty token")
    async with async_session_factory() as s:
        res = await s.execute(select(SiteUser).where(SiteUser.api_key == token))
        user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(401, "Invalid token")
    return user


# ── Публичный API ingest ────────────────────────
@router.post("/api/v1/ingest/leads")
async def ingest_leads(batch: IngestBatch, request: Request):
    user = await _user_by_api_key(request)
    added = 0
    skipped = 0
    async with async_session_factory() as s:
        can, cur, lim = await check_limit(s, user, Lead, "max_leads")
        if not can:
            return JSONResponse(
                {"ok": False, "error": f"Лимит лидов {cur}/{lim}"},
                status_code=402,
            )
        for item in batch.leads:
            # Дедуп по dgis_id
            if item.dgis_id:
                exists = (await s.execute(
                    select(Lead).where(Lead.dgis_id == item.dgis_id)
                )).scalar_one_or_none()
                if exists:
                    skipped += 1
                    continue
            s.add(Lead(
                name=item.name[:500],
                address=item.address[:500] if item.address else None,
                city=item.city[:256] if item.city else None,
                phone=item.phone[:64] if item.phone else None,
                website=item.website[:500] if item.website else None,
                categories=item.categories[:500] if item.categories else None,
                source_query=item.source_query[:256] if item.source_query else None,
                dgis_id=item.dgis_id[:64] if item.dgis_id else None,
                status=LeadStatus.NEW,
                owner_id=user.id,
            ))
            added += 1
        await s.commit()
    return {"ok": True, "added": added, "skipped": skipped}


@router.get("/api/v1/ingest/ping")
async def ingest_ping(request: Request):
    user = await _user_by_api_key(request)
    return {"ok": True, "email": user.email, "plan": user.plan.value}


# ── Страница управления расширением ────────────
@router.get("/app/extension/", response_class=HTMLResponse)
async def ext_page(request: Request, msg: str = ""):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    # Генерим api_key если нет
    if not user.api_key:
        async with async_session_factory() as s:
            u = await s.get(SiteUser, user.id)
            u.api_key = secrets.token_urlsafe(32)
            await s.commit()
            await s.refresh(u)
            user = u

    return templates_obj.TemplateResponse(
        request=request,
        name="extension.html",
        context={"user": user, "msg": msg},
    )


@router.post("/app/extension/regenerate")
async def ext_regenerate(request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    async with async_session_factory() as s:
        u = await s.get(SiteUser, user.id)
        u.api_key = secrets.token_urlsafe(32)
        await s.commit()
    return RedirectResponse("/app/extension/?msg=Ключ+обновлён", status_code=303)


# ── Выдача userscript ───────────────────────────
USERSCRIPT_TEMPLATE = r"""// ==UserScript==
// @name         MaxSurge 2GIS Collector
// @namespace    https://maxsurge.ru
// @version      1.0.0
// @description  Собирает лиды из 2GIS и отправляет в MaxSurge (обходит блокировку серверного IP)
// @match        https://2gis.ru/*
// @grant        GM_xmlhttpRequest
// @grant        GM_setValue
// @grant        GM_getValue
// @run-at       document-idle
// @connect      maxsurge.ru
// ==/UserScript==

(function () {
  'use strict';

  const API_URL = 'https://maxsurge.ru/api/v1/ingest/leads';
  const API_KEY = '__API_KEY__';

  function log(...args) { console.log('[MaxSurge]', ...args); }

  function parseCards() {
    const items = [];
    const seen = new Set();
    // 2GIS карточки рендерятся с data-атрибутами + .card__name
    document.querySelectorAll('[class*="_name_"], [class*="card"][class*="name"]').forEach(el => {
      const container = el.closest('article, [class*="_card_"], [class*="miniCard"]') || el.parentElement;
      if (!container) return;
      const name = (el.innerText || '').trim();
      if (!name || seen.has(name)) return;
      seen.add(name);
      const text = container.innerText || '';
      const phoneMatch = text.match(/(\+?\d[\d\s\-()]{7,}\d)/);
      const addrMatch = text.match(/(ул\.|улица|проспект|просп\.|пр-?т|переулок|пер\.|пл\.|площадь|дом|д\.|корп\.)[^\n]+/i);
      const catMatch = text.split('\n').slice(0, 3).join(' · ');
      const url = location.href;
      const city = (location.pathname.split('/')[1] || '').replace(/[_-]/g, ' ');
      const query = new URLSearchParams(location.search).get('q') || '';
      items.push({
        name,
        phone: phoneMatch ? phoneMatch[1].replace(/[\s\-()]/g, '') : null,
        address: addrMatch ? addrMatch[0].trim() : null,
        city,
        categories: catMatch,
        source_query: query,
        dgis_id: btoa(unescape(encodeURIComponent(name + '|' + (addrMatch ? addrMatch[0] : '')))).slice(0, 48),
      });
    });
    return items;
  }

  function send(items) {
    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({
        method: 'POST',
        url: API_URL,
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + API_KEY,
        },
        data: JSON.stringify({ leads: items }),
        onload: r => {
          try { resolve(JSON.parse(r.responseText)); } catch { resolve({ ok: false, raw: r.responseText }); }
        },
        onerror: e => reject(e),
      });
    });
  }

  function createButton() {
    if (document.getElementById('maxsurge-btn')) return;
    const btn = document.createElement('button');
    btn.id = 'maxsurge-btn';
    btn.innerText = '⚡ В MaxSurge';
    Object.assign(btn.style, {
      position: 'fixed',
      bottom: '24px',
      right: '24px',
      zIndex: 99999,
      padding: '12px 20px',
      background: 'linear-gradient(135deg,#6366f1,#a855f7)',
      color: '#fff',
      border: 'none',
      borderRadius: '12px',
      fontSize: '14px',
      fontWeight: '600',
      cursor: 'pointer',
      boxShadow: '0 10px 30px rgba(99,102,241,0.4)',
      fontFamily: 'sans-serif',
    });
    btn.onclick = async () => {
      btn.innerText = '⏳ Парсим...';
      const items = parseCards();
      if (items.length === 0) {
        btn.innerText = '❌ Ничего не найдено';
        setTimeout(() => btn.innerText = '⚡ В MaxSurge', 2000);
        return;
      }
      btn.innerText = `📤 Отправка ${items.length}...`;
      try {
        const res = await send(items);
        if (res.ok) {
          btn.innerText = `✅ +${res.added}${res.skipped ? ' (дубли: ' + res.skipped + ')' : ''}`;
        } else {
          btn.innerText = '❌ ' + (res.error || 'Ошибка');
        }
      } catch (e) {
        btn.innerText = '❌ Нет связи';
        log(e);
      }
      setTimeout(() => btn.innerText = '⚡ В MaxSurge', 4000);
    };
    document.body.appendChild(btn);
  }

  const observer = new MutationObserver(() => createButton());
  observer.observe(document.body, { childList: true, subtree: true });
  createButton();
  log('MaxSurge userscript loaded');
})();
"""


@router.get("/app/extension/userscript.user.js", response_class=PlainTextResponse)
async def userscript(request: Request):
    user = await get_current_user(request)
    if not user:
        return PlainTextResponse("// Требуется вход", status_code=401)
    if not user.api_key:
        async with async_session_factory() as s:
            u = await s.get(SiteUser, user.id)
            u.api_key = secrets.token_urlsafe(32)
            await s.commit()
            user = u
    script = USERSCRIPT_TEMPLATE.replace("__API_KEY__", user.api_key)
    return PlainTextResponse(
        script,
        headers={
            "Content-Type": "application/javascript; charset=utf-8",
            "Content-Disposition": 'attachment; filename="maxsurge-2gis.user.js"',
        },
    )
