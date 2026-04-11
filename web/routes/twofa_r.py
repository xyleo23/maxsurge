"""2FA через TOTP (Google Authenticator, Authy, 1Password)."""
import base64
import io
from pathlib import Path

import pyotp
import qrcode
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from db.models import SiteUser, async_session_factory
from web.routes.auth_r import get_current_user

router = APIRouter(prefix="/2fa")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _generate_qr_base64(uri: str) -> str:
    """Генерирует QR код как base64 PNG."""
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


@router.get("/", response_class=HTMLResponse)
async def setup_page(request: Request, msg: str = ""):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    qr_base64 = None
    secret = None

    if not user.totp_enabled:
        # Генерируем секрет если ещё нет
        if not user.totp_secret:
            new_secret = pyotp.random_base32()
            async with async_session_factory() as s:
                db_user = await s.get(SiteUser, user.id)
                if db_user:
                    db_user.totp_secret = new_secret
                    await s.commit()
                    user = db_user

        secret = user.totp_secret
        totp = pyotp.TOTP(secret)
        uri = totp.provisioning_uri(
            name=user.email,
            issuer_name="MaxSurge",
        )
        qr_base64 = _generate_qr_base64(uri)

    return templates.TemplateResponse(request=request, name="2fa.html", context={
        "user": user,
        "secret": secret,
        "qr_base64": qr_base64,
        "msg": msg,
    })


@router.post("/enable")
async def enable_2fa(request: Request, code: str = Form(...)):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    if not user.totp_secret:
        return RedirectResponse("/app/2fa/?msg=Секрет+не+сгенерирован", status_code=303)

    totp = pyotp.TOTP(user.totp_secret)
    if not totp.verify(code.strip(), valid_window=1):
        return RedirectResponse("/app/2fa/?msg=Неверный+код", status_code=303)

    async with async_session_factory() as s:
        db_user = await s.get(SiteUser, user.id)
        if db_user:
            db_user.totp_enabled = True
            await s.commit()

    return RedirectResponse("/app/2fa/?msg=2FA+включена", status_code=303)


@router.post("/disable")
async def disable_2fa(request: Request, code: str = Form(...)):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    if not user.totp_enabled or not user.totp_secret:
        return RedirectResponse("/app/2fa/?msg=2FA+не+включена", status_code=303)

    totp = pyotp.TOTP(user.totp_secret)
    if not totp.verify(code.strip(), valid_window=1):
        return RedirectResponse("/app/2fa/?msg=Неверный+код", status_code=303)

    async with async_session_factory() as s:
        db_user = await s.get(SiteUser, user.id)
        if db_user:
            db_user.totp_enabled = False
            db_user.totp_secret = None
            await s.commit()

    return RedirectResponse("/app/2fa/?msg=2FA+отключена", status_code=303)
