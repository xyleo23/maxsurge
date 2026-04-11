"""Роутер для email-операций: unsubscribe."""
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from db.models import async_session_factory as asf
from db.models_onboarding import EmailPreferences
from max_client.onboarding import parse_unsubscribe_token

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/email/unsubscribe", response_class=HTMLResponse)
async def unsubscribe(request: Request, token: str = ""):
    user_id = parse_unsubscribe_token(token) if token else None
    status = "error"
    if user_id is not None:
        try:
            async with asf() as s:
                pref = await s.get(EmailPreferences, user_id)
                if pref is None:
                    pref = EmailPreferences(user_id=user_id, unsubscribed=True, unsubscribed_at=datetime.utcnow())
                    s.add(pref)
                else:
                    pref.unsubscribed = True
                    pref.unsubscribed_at = datetime.utcnow()
                await s.commit()
            status = "ok"
        except Exception:
            status = "error"

    html = _RENDER[status]
    return HTMLResponse(html)


_RENDER = {
    "ok": """<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"/>
<title>Вы отписались — MaxSurge</title>
<script src="https://cdn.tailwindcss.com"></script></head>
<body class="bg-[#0a0e1a] text-gray-100 min-h-screen flex items-center justify-center px-6">
<div class="max-w-md text-center bg-[#0f172a] border border-[#1e293b] rounded-2xl p-10">
  <div class="w-14 h-14 mx-auto mb-5 rounded-full bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center">
    <svg class="w-7 h-7 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
  </div>
  <h1 class="text-2xl font-bold mb-3">Вы отписаны от рассылок</h1>
  <p class="text-gray-400 text-sm leading-relaxed mb-6">Мы больше не будем присылать вам онбординг-письма и маркетинговые рассылки. Уведомления о биллинге и безопасности аккаунта продолжат приходить — это системные письма, их нельзя отключить.</p>
  <a href="/" class="inline-block bg-gradient-to-r from-indigo-600 to-purple-600 text-white px-6 py-2.5 rounded-xl font-medium text-sm">На главную</a>
</div></body></html>""",
    "error": """<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"/>
<title>Ошибка — MaxSurge</title>
<script src="https://cdn.tailwindcss.com"></script></head>
<body class="bg-[#0a0e1a] text-gray-100 min-h-screen flex items-center justify-center px-6">
<div class="max-w-md text-center bg-[#0f172a] border border-[#1e293b] rounded-2xl p-10">
  <div class="w-14 h-14 mx-auto mb-5 rounded-full bg-rose-500/10 border border-rose-500/30 flex items-center justify-center">
    <svg class="w-7 h-7 text-rose-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
  </div>
  <h1 class="text-2xl font-bold mb-3">Ссылка недействительна</h1>
  <p class="text-gray-400 text-sm leading-relaxed mb-6">Ссылка отписки испорчена или устарела. Если хотите отписаться — напишите в поддержку <a href="https://t.me/beliaevd" class="text-indigo-400 hover:text-indigo-300">@beliaevd</a>.</p>
  <a href="/" class="inline-block bg-gradient-to-r from-indigo-600 to-purple-600 text-white px-6 py-2.5 rounded-xl font-medium text-sm">На главную</a>
</div></body></html>""",
}
