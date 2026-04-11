"""Email onboarding серия из 4 писем — день 0, 2, 5, 7 после регистрации.

Запускается периодически раз в 30 минут как asyncio task из main.startup.
Идемпотентно — проверяет EmailLog, не шлёт повторно.
Уважает отписку через EmailPreferences.unsubscribed.
"""
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeSerializer
from loguru import logger
from sqlalchemy import and_, select

from config import get_settings
from db.models import SiteUser, async_session_factory as asf
from db.models_onboarding import EmailLog, EmailPreferences
from max_client.email_sender import send_email

settings = get_settings()
_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "web" / "templates"))
_signer = URLSafeSerializer(settings.SECRET_KEY if hasattr(settings, "SECRET_KEY") else "maxsurge-onboarding-salt", salt="unsubscribe")


# ── Серия писем: (день после регистрации, тип, subject, template) ────────
SERIES = [
    (0, "onboarding_day0", "Добро пожаловать в MaxSurge — начните за 5 минут", "emails/onboarding_day0.html"),
    (2, "onboarding_day2", "Попробовали парсинг 2GIS?", "emails/onboarding_day2.html"),
    (5, "onboarding_day5", "5 дней в MaxSurge — что получилось?", "emails/onboarding_day5.html"),
    (7, "onboarding_day7", "Завтра заканчивается триал MaxSurge", "emails/onboarding_day7.html"),
]


def make_unsubscribe_token(user_id: int) -> str:
    return _signer.dumps(user_id)


def parse_unsubscribe_token(token: str) -> int | None:
    try:
        value = _signer.loads(token)
        return int(value)
    except Exception:
        return None


async def _already_sent(s, user_id: int, email_type: str) -> bool:
    row = await s.execute(
        select(EmailLog).where(and_(EmailLog.user_id == user_id, EmailLog.email_type == email_type))
    )
    return row.scalar_one_or_none() is not None


async def _is_unsubscribed(s, user_id: int) -> bool:
    pref = await s.get(EmailPreferences, user_id)
    return bool(pref and pref.unsubscribed)


def _render_email(template_name: str, context: dict) -> str:
    """Рендерит HTML без request-контекста (для писем)."""
    template = _templates.get_template(template_name)
    return template.render(**context)


async def send_onboarding_email(user: SiteUser, email_type: str, subject: str, template: str) -> bool:
    token = make_unsubscribe_token(user.id)
    html = _render_email(template, {
        "user": user,
        "name": (user.name or "друг").strip() or "друг",
        "unsubscribe_url": f"https://maxsurge.ru/email/unsubscribe?token={token}",
        "site_url": "https://maxsurge.ru",
    })
    ok = await send_email(to=user.email, subject=subject, html_body=html)
    return ok


async def process_user(s, user: SiteUser, now: datetime) -> None:
    if await _is_unsubscribed(s, user.id):
        return
    days = (now - user.created_at).days
    for day_offset, email_type, subject, template in SERIES:
        if days < day_offset:
            continue
        if await _already_sent(s, user.id, email_type):
            continue
        from max_client.email_sender import DRY_RUN
        ok = await send_onboarding_email(user, email_type, subject, template)
        if ok:
            s.add(EmailLog(user_id=user.id, email_type=email_type, dry_run=DRY_RUN))
            await s.flush()
            logger.info("Onboarding sent: type={} user_id={} email={}", email_type, user.id, user.email)


async def check_and_send_onboarding() -> None:
    """Один проход по кандидатам для онбординга."""
    now = datetime.utcnow()
    cutoff = now - timedelta(days=10)  # не смотрим пользователей старше 10 дней
    try:
        async with asf() as s:
            result = await s.execute(
                select(SiteUser).where(SiteUser.created_at >= cutoff)
            )
            users = result.scalars().all()
            for user in users:
                try:
                    await process_user(s, user, now)
                except Exception as e:
                    logger.warning("onboarding user_id={} failed: {}", user.id, e)
            await s.commit()
    except Exception as e:
        logger.error("check_and_send_onboarding: {}", e)


async def run_onboarding_loop(interval_sec: int = 1800) -> None:
    """Бесконечный цикл — проверка каждые 30 минут."""
    logger.info("Onboarding loop started (interval={}s)", interval_sec)
    # Небольшая стартовая задержка, чтобы не гонять сразу после рестарта
    await asyncio.sleep(60)
    while True:
        await check_and_send_onboarding()
        await asyncio.sleep(interval_sec)
