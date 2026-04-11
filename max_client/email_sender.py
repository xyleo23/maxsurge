"""Email sender — SMTP-обёртка с DRY_RUN режимом по умолчанию.

Настройки через переменные окружения (.env):
  SMTP_DRY_RUN=1         — по умолчанию 1 (логируем вместо отправки)
  SMTP_HOST=smtp.yandex.ru
  SMTP_PORT=465
  SMTP_USER=noreply@maxsurge.ru
  SMTP_PASS=...
  SMTP_FROM="MaxSurge <noreply@maxsurge.ru>"
  SMTP_USE_SSL=1         — 1 для порта 465, 0 для 587/STARTTLS

В DRY_RUN режиме письма пишутся в logs/emails_dry.log и в EmailLog с dry_run=True.
"""
import asyncio
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from loguru import logger


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


DRY_RUN = _env("SMTP_DRY_RUN", "1") == "1"
SMTP_HOST = _env("SMTP_HOST")
SMTP_PORT = int(_env("SMTP_PORT", "465"))
SMTP_USER = _env("SMTP_USER")
SMTP_PASS = _env("SMTP_PASS")
SMTP_FROM = _env("SMTP_FROM", "MaxSurge <noreply@maxsurge.ru>")
SMTP_USE_SSL = _env("SMTP_USE_SSL", "1") == "1"

DRY_LOG_PATH = Path("logs/emails_dry.log")


def _build_message(to: str, subject: str, html_body: str, text_body: str | None = None) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = to
    if text_body:
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


def _send_sync(to: str, subject: str, html_body: str, text_body: str | None = None) -> None:
    """Синхронная реальная отправка (вызывается в executor из async)."""
    msg = _build_message(to, subject, html_body, text_body)
    context = ssl.create_default_context()
    if SMTP_USE_SSL:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=30) as s:
            if SMTP_USER and SMTP_PASS:
                s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
            s.ehlo()
            s.starttls(context=context)
            s.ehlo()
            if SMTP_USER and SMTP_PASS:
                s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)


async def send_email(to: str, subject: str, html_body: str, text_body: str | None = None) -> bool:
    """Асинхронная отправка. В DRY_RUN режиме только логирует.

    Возвращает True при успехе (или при DRY_RUN), False при ошибке реальной отправки.
    """
    if DRY_RUN:
        try:
            DRY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with DRY_LOG_PATH.open("a", encoding="utf-8") as f:
                f.write("\n" + "=" * 60 + "\n")
                f.write(f"To: {to}\nFrom: {SMTP_FROM}\nSubject: {subject}\n\n")
                f.write(html_body)
                f.write("\n")
            logger.info("[EMAIL DRY_RUN] to={} subject={}", to, subject)
        except Exception as e:
            logger.warning("DRY log write failed: {}", e)
        return True

    if not SMTP_HOST or not SMTP_USER:
        logger.warning("SMTP not configured (DRY_RUN=0 but SMTP_HOST/USER empty) — skipping {}", to)
        return False

    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _send_sync, to, subject, html_body, text_body)
        logger.info("[EMAIL SENT] to={} subject={}", to, subject)
        return True
    except Exception as e:
        logger.error("SMTP send failed to {}: {}", to, e)
        return False
