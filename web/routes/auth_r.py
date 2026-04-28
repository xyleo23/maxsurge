"""Авторизация: регистрация, вход, выход, email-верификация, сброс пароля."""
import asyncio
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer
import pyotp
from passlib.hash import bcrypt
from sqlalchemy import select

from config import get_settings
from db.models import SiteUser, UserPlan, async_session_factory
from web.routes._rate_limit import rate_limit, get_client_ip
from max_client.tg_notifier import on_signup
from max_client.email_client import (
    send_welcome_email,
    send_verify_email,
    send_password_reset_email,
)

settings = get_settings()
router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

_serializer = URLSafeTimedSerializer(settings.SECRET_KEY)
COOKIE_NAME = "maxsurge_session"
MAX_AGE = 60 * 60 * 24 * 30  # 30 days


def _create_session_token(user_id: int, email: str) -> str:
    return _serializer.dumps({"uid": user_id, "email": email})


def _verify_session_token(token: str) -> dict | None:
    try:
        return _serializer.loads(token, max_age=MAX_AGE)
    except Exception:
        return None


async def get_current_user(request: Request) -> SiteUser | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    data = _verify_session_token(token)
    if not data:
        return None
    async with async_session_factory() as s:
        user = (await s.execute(
            select(SiteUser).where(SiteUser.id == data["uid"])
        )).scalar_one_or_none()
    return user


def _send_async(fn, *args):
    """Отправка email в фоне, не блокирует ответ."""
    asyncio.create_task(asyncio.to_thread(fn, *args))


# ── Landing ──────────────────────────────────────────
@router.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    user = await get_current_user(request)
    if user:
        return RedirectResponse("/app/", status_code=303)
    return templates.TemplateResponse(request=request, name="landing.html", context={})


# ── Register ──────────────────────────────────────────
@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, msg: str = ""):
    return templates.TemplateResponse(request=request, name="register.html", context={"msg": msg})


@router.post("/auth/register")
async def register(request: Request, email: str = Form(...), password: str = Form(...), name: str = Form("")):
    ip = get_client_ip(request)
    ok, reset = rate_limit(f"register:{ip}", max_requests=3, window_sec=3600)
    if not ok:
        return RedirectResponse(
            f"/register?msg=Слишком+много+попыток.+Попробуйте+через+{reset}+сек",
            status_code=303,
        )

    email = email.strip().lower()
    if len(password) < 8:
        return RedirectResponse("/register?msg=Пароль+минимум+8+символов", status_code=303)
    if not any(c.isdigit() for c in password):
        return RedirectResponse("/register?msg=Пароль+должен+содержать+хотя+бы+одну+цифру", status_code=303)
    if not any(c.isupper() for c in password) and not any(c.islower() for c in password):
        return RedirectResponse("/register?msg=Пароль+должен+содержать+буквы", status_code=303)

    async with async_session_factory() as s:
        existing = (await s.execute(
            select(SiteUser).where(SiteUser.email == email)
        )).scalar_one_or_none()
        if existing:
            return RedirectResponse("/register?msg=Email+уже+зарегистрирован", status_code=303)

        verify_token = secrets.token_urlsafe(32)
        ref_code = secrets.token_urlsafe(8).replace("_", "").replace("-", "")[:12]

        # Найти реферера по коду из query / cookie
        referrer_id = None
        ref_from_query = request.query_params.get("ref") or ""
        ref_from_cookie = request.cookies.get("maxsurge_ref") or ""
        ref_code_in = (ref_from_query or ref_from_cookie).strip()
        if ref_code_in:
            referrer = (await s.execute(
                select(SiteUser).where(SiteUser.ref_code == ref_code_in)
            )).scalar_one_or_none()
            if referrer:
                referrer_id = referrer.id

        user = SiteUser(
            email=email,
            password_hash=bcrypt.using(rounds=12).hash(password),
            name=name.strip() or None,
            plan=UserPlan.TRIAL,
            plan_expires_at=datetime.utcnow() + timedelta(days=7),
            email_verified=False,
            email_verify_token=verify_token,
            ref_code=ref_code,
            referred_by=referrer_id,
        )
        s.add(user)
        await s.commit()
        await s.refresh(user)

    # Отправка email (в фоне)
    _send_async(send_welcome_email, email, name)
    _send_async(send_verify_email, email, verify_token)

    # Уведомление владельцу
    on_signup(email, name, "trial")

    token = _create_session_token(user.id, user.email)
    response = RedirectResponse("/app/", status_code=303)
    response.set_cookie(COOKIE_NAME, token, max_age=MAX_AGE, httponly=True, samesite="lax", secure=True)
    return response


# ── Email verification ──────────────────────────────────
@router.get("/auth/verify")
async def verify_email(token: str):
    async with async_session_factory() as s:
        user = (await s.execute(
            select(SiteUser).where(SiteUser.email_verify_token == token)
        )).scalar_one_or_none()
        if not user:
            return RedirectResponse("/login?msg=Недействительная+ссылка", status_code=303)
        user.email_verified = True
        user.email_verify_token = None
        await s.commit()
    return RedirectResponse("/login?msg=Email+подтверждён.+Войдите+в+аккаунт.", status_code=303)


# ── Login ──────────────────────────────────────────
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, msg: str = ""):
    return templates.TemplateResponse(request=request, name="login.html", context={"msg": msg})


@router.post("/auth/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...), totp_code: str = Form("")):
    ip = get_client_ip(request)
    email = email.strip().lower()
    ok, reset = rate_limit(f"login:{ip}:{email}", max_requests=5, window_sec=600)
    if not ok:
        return RedirectResponse(
            f"/login?msg=Слишком+много+попыток.+Попробуйте+через+{reset}+сек",
            status_code=303,
        )

    async with async_session_factory() as s:
        user = (await s.execute(
            select(SiteUser).where(SiteUser.email == email)
        )).scalar_one_or_none()

    if not user or not bcrypt.verify(password, user.password_hash):
        try:
            from main import record_auth_failure
            record_auth_failure(ip)
        except Exception:
            pass
        return RedirectResponse("/login?msg=Неверный+email+или+пароль", status_code=303)

    if not user.is_active:
        return RedirectResponse("/login?msg=Аккаунт+заблокирован", status_code=303)

    # 2FA проверка
    if user.totp_enabled and user.totp_secret:
        if not totp_code:
            # Временный токен в cookie с email/pwd → форма 2FA
            challenge = _serializer.dumps({"uid": user.id, "challenge": True})
            response = RedirectResponse("/login-2fa", status_code=303)
            response.set_cookie("maxsurge_2fa_challenge", challenge, max_age=300, httponly=True, samesite="lax", secure=True)
            return response

        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(totp_code.strip(), valid_window=1):
            return RedirectResponse("/login?msg=Неверный+код+2FA", status_code=303)

    async with async_session_factory() as s:
        db_user = await s.get(SiteUser, user.id)
        if db_user:
            db_user.last_login = datetime.utcnow()
            await s.commit()
        is_super = getattr(user, "is_superadmin", False)

    # OOO5: alert on superadmin login
    if is_super:
        try:
            from max_client.tg_notifier import notify_async
            notify_async("\U0001f510 <b>Admin login</b>\n\n" + user.email + "\nIP: " + ip + "\nUA: " + request.headers.get("user-agent", "?")[:100])
        except Exception:
            pass
        try:
            from max_client.audit import log_audit
            await log_audit(user, "admin_login", "user", user.id, ip=ip, details=request.headers.get("user-agent", "")[:200])
        except Exception:
            pass

    token = _create_session_token(user.id, user.email)
    response = RedirectResponse("/app/", status_code=303)
    response.set_cookie(COOKIE_NAME, token, max_age=MAX_AGE, httponly=True, samesite="lax", secure=True)
    return response


# ── Logout ──────────────────────────────────────────
@router.get("/auth/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


# ── Forgot password ────────────────────────────────────
@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_page(request: Request, msg: str = ""):
    return templates.TemplateResponse(request=request, name="forgot.html", context={"msg": msg})


@router.post("/auth/forgot-password")
async def forgot_password(request: Request, email: str = Form(...)):
    ip = get_client_ip(request)
    email = email.strip().lower()
    ok, _ = rate_limit(f"forgot:{ip}:{email}", max_requests=3, window_sec=3600)
    if not ok:
        return RedirectResponse("/forgot-password?msg=Слишком+много+запросов", status_code=303)
    async with async_session_factory() as s:
        user = (await s.execute(
            select(SiteUser).where(SiteUser.email == email)
        )).scalar_one_or_none()

        if user:
            reset_token = secrets.token_urlsafe(32)
            user.password_reset_token = reset_token
            user.password_reset_expires = datetime.utcnow() + timedelta(hours=1)
            await s.commit()
            _send_async(send_password_reset_email, email, reset_token)

    # Всегда показываем одно и то же (не раскрываем наличие email)
    return RedirectResponse(
        "/forgot-password?msg=Если+email+зарегистрирован,+письмо+отправлено",
        status_code=303,
    )


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_page(request: Request, token: str = "", msg: str = ""):
    # Проверяем токен
    valid = False
    if token:
        async with async_session_factory() as s:
            user = (await s.execute(
                select(SiteUser).where(
                    SiteUser.password_reset_token == token,
                    SiteUser.password_reset_expires > datetime.utcnow(),
                )
            )).scalar_one_or_none()
            valid = user is not None

    return templates.TemplateResponse(request=request, name="reset.html", context={
        "token": token,
        "valid": valid,
        "msg": msg,
    })


@router.post("/auth/reset-password")
async def reset_password(token: str = Form(...), new_password: str = Form(...)):
    if len(new_password) < 8:
        return RedirectResponse(
            f"/reset-password?token={token}&msg=Пароль+минимум+6+символов",
            status_code=303,
        )

    async with async_session_factory() as s:
        user = (await s.execute(
            select(SiteUser).where(
                SiteUser.password_reset_token == token,
                SiteUser.password_reset_expires > datetime.utcnow(),
            )
        )).scalar_one_or_none()

        if not user:
            return RedirectResponse("/forgot-password?msg=Ссылка+недействительна+или+истекла", status_code=303)

        user.password_hash = bcrypt.using(rounds=12).hash(new_password)
        user.password_reset_token = None
        user.password_reset_expires = None
        await s.commit()

    return RedirectResponse("/login?msg=Пароль+изменён.+Войдите+с+новым+паролем.", status_code=303)


# ── Resend verification email ──────────────────────────
@router.post("/auth/resend-verify")
async def resend_verify(request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    if user.email_verified:
        return RedirectResponse("/app/settings/?msg=Email+уже+подтверждён", status_code=303)

    async with async_session_factory() as s:
        db_user = await s.get(SiteUser, user.id)
        if db_user:
            if not db_user.email_verify_token:
                db_user.email_verify_token = secrets.token_urlsafe(32)
            await s.commit()
            _send_async(send_verify_email, db_user.email, db_user.email_verify_token)

    return RedirectResponse("/app/settings/?msg=Письмо+с+подтверждением+отправлено", status_code=303)


@router.get("/login-2fa", response_class=HTMLResponse)
async def login_2fa_page(request: Request, msg: str = ""):
    challenge = request.cookies.get("maxsurge_2fa_challenge", "")
    if not challenge:
        return RedirectResponse("/login", status_code=303)
    try:
        data = _serializer.loads(challenge, max_age=300)
        uid = data.get("uid")
    except Exception:
        return RedirectResponse("/login?msg=Сессия+истекла", status_code=303)

    return templates.TemplateResponse(request=request, name="login_2fa.html", context={
        "msg": msg,
    })


@router.post("/auth/login-2fa")
async def login_2fa_verify(request: Request, totp_code: str = Form(...)):
    challenge = request.cookies.get("maxsurge_2fa_challenge", "")
    if not challenge:
        return RedirectResponse("/login", status_code=303)
    try:
        data = _serializer.loads(challenge, max_age=300)
        uid = data.get("uid")
    except Exception:
        return RedirectResponse("/login?msg=Сессия+истекла", status_code=303)

    async with async_session_factory() as s:
        user = await s.get(SiteUser, uid)

    if not user or not user.totp_secret:
        return RedirectResponse("/login", status_code=303)

    totp = pyotp.TOTP(user.totp_secret)
    if not totp.verify(totp_code.strip(), valid_window=1):
        return RedirectResponse("/login-2fa?msg=Неверный+код", status_code=303)

    async with async_session_factory() as s:
        db_user = await s.get(SiteUser, user.id)
        if db_user:
            db_user.last_login = datetime.utcnow()
            await s.commit()

    token = _create_session_token(user.id, user.email)
    response = RedirectResponse("/app/", status_code=303)
    response.set_cookie(COOKIE_NAME, token, max_age=MAX_AGE, httponly=True, samesite="lax", secure=True)
    response.delete_cookie("maxsurge_2fa_challenge")
    return response
