"""Реферальная программа: ссылка, статистика, комиссии."""
import secrets
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func

from db.models import SiteUser, RefCommission, async_session_factory
from web.routes.auth_r import get_current_user

router = APIRouter(prefix="/referral")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def referral_page(request: Request, msg: str = ""):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    # Убедиться что у юзера есть ref_code
    if not user.ref_code:
        async with async_session_factory() as s:
            db_user = await s.get(SiteUser, user.id)
            if db_user and not db_user.ref_code:
                db_user.ref_code = secrets.token_urlsafe(8).replace("_", "").replace("-", "")[:12]
                await s.commit()
                user = db_user

    async with async_session_factory() as s:
        # Количество привлечённых юзеров
        total_referred = (await s.execute(
            select(func.count(SiteUser.id)).where(SiteUser.referred_by == user.id)
        )).scalar() or 0

        # Всего платежей этих юзеров
        total_commissions_count = (await s.execute(
            select(func.count(RefCommission.id)).where(RefCommission.referrer_id == user.id)
        )).scalar() or 0

        # Список последних рефералов
        referred_users = (await s.execute(
            select(SiteUser).where(SiteUser.referred_by == user.id).order_by(SiteUser.created_at.desc()).limit(20)
        )).scalars().all()

        # Последние комиссии
        commissions = (await s.execute(
            select(RefCommission).where(RefCommission.referrer_id == user.id).order_by(RefCommission.created_at.desc()).limit(20)
        )).scalars().all()

    ref_link = f"https://maxsurge.ru/register?ref={user.ref_code}"

    return templates.TemplateResponse(request=request, name="referral.html", context={
        "user": user,
        "ref_link": ref_link,
        "total_referred": total_referred,
        "total_commissions_count": total_commissions_count,
        "balance": user.ref_balance or 0,
        "earned_total": user.ref_earned_total or 0,
        "referred_users": referred_users,
        "commissions": commissions,
        "msg": msg,
    })


# Публичная страница сбора ref из query
@router.get("/track", response_class=HTMLResponse)
async def track(request: Request, ref: str = ""):
    """Установить cookie с ref кодом и редирект на register."""
    response = RedirectResponse(f"/register?ref={ref}", status_code=303)
    if ref:
        response.set_cookie("maxsurge_ref", ref, max_age=60 * 60 * 24 * 30, httponly=False, samesite="lax")
    return response
