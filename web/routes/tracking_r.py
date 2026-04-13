"""Click tracking — короткие ссылки с подсчётом кликов.

Пользователь создаёт tracked link → получает https://maxsurge.ru/go/CODE
Вставляет в шаблоны. При переходе +1 click, redirect на target_url.
"""
import secrets
from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc

from db.models import ClickTrack, async_session_factory
from web.routes._scope import scope_query
from web.routes.auth_r import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/go/{code}")
async def redirect_tracked(code: str, request: Request):
    """Public redirect endpoint — increments click counter."""
    async with async_session_factory() as s:
        res = await s.execute(select(ClickTrack).where(ClickTrack.short_code == code))
        track = res.scalar_one_or_none()
        if not track:
            return RedirectResponse("/", status_code=302)
        ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or ""
        track.clicks += 1
        # Track unique IPs (simple CSV, max 10KB)
        ips = set((track.unique_ips or "").split(","))
        if ip and ip not in ips and len(track.unique_ips or "") < 10000:
            ips.add(ip)
            track.unique_ips = ",".join(i for i in ips if i)
        await s.commit()
    return RedirectResponse(track.target_url, status_code=302)


@router.get("/app/tracking/", response_class=HTMLResponse)
async def tracking_page(request: Request, msg: str = ""):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    async with async_session_factory() as s:
        tracks = (await s.execute(
            scope_query(select(ClickTrack), ClickTrack, user).order_by(desc(ClickTrack.created_at))
        )).scalars().all()
    return templates.TemplateResponse(
        request=request,
        name="tracking.html",
        context={"tracks": tracks, "msg": msg},
    )


@router.post("/app/tracking/create")
async def create_track(
    request: Request,
    target_url: str = Form(...),
    campaign_name: str = Form(""),
):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    code = secrets.token_urlsafe(6)[:8]
    async with async_session_factory() as s:
        s.add(ClickTrack(
            owner_id=user.id,
            short_code=code,
            target_url=target_url.strip(),
            campaign_name=campaign_name.strip() or None,
        ))
        await s.commit()
    return RedirectResponse(f"/app/tracking/?msg=Ссылка+создана:+/go/{code}", status_code=303)


@router.post("/app/tracking/{track_id}/delete")
async def delete_track(track_id: int, request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    async with async_session_factory() as s:
        t = await s.get(ClickTrack, track_id)
        if t and (t.owner_id == user.id or user.is_superadmin):
            await s.delete(t)
            await s.commit()
    return RedirectResponse("/app/tracking/?msg=Удалено", status_code=303)
