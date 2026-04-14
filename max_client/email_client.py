"""SMTP клиент для отправки email (верификация, восстановление, welcome)."""
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from loguru import logger

from config import get_settings

settings = get_settings()


def _send_email(to_email: str, subject: str, html_body: str, text_body: str = "") -> bool:
    """Отправить email через SMTP."""
    smtp_host = getattr(settings, "SMTP_HOST", "")
    smtp_port = getattr(settings, "SMTP_PORT", 465)
    smtp_user = getattr(settings, "SMTP_USER", "")
    smtp_password = getattr(settings, "SMTP_PASSWORD", "")
    smtp_from = getattr(settings, "SMTP_FROM", smtp_user or "noreply@maxsurge.ru")
    smtp_from_name = getattr(settings, "SMTP_FROM_NAME", "MaxSurge")

    if not smtp_host or not smtp_user or not smtp_password:
        logger.warning("SMTP не настроен, email {} не отправлен", to_email)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{smtp_from_name} <{smtp_from}>"
    msg["To"] = to_email

    if text_body:
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        context = ssl.create_default_context()
        if int(smtp_port) == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context, timeout=15) as server:
                server.login(smtp_user, smtp_password)
                server.sendmail(smtp_from, to_email, msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                server.starttls(context=context)
                server.login(smtp_user, smtp_password)
                server.sendmail(smtp_from, to_email, msg.as_string())
        logger.info("Email отправлен: {} → {}", subject, to_email)
        return True
    except Exception as e:
        logger.error("Ошибка SMTP ({}): {}", to_email, e)
        return False


def _base_html(title: str, content: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f8fafc;padding:40px 20px">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" border="0" style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.06)">
        <tr><td style="background:linear-gradient(135deg,#6366f1,#a855f7,#ec4899);padding:30px;text-align:center">
          <div style="display:inline-block;background:rgba(255,255,255,0.15);padding:12px 20px;border-radius:10px">
            <span style="color:#fff;font-size:24px;font-weight:bold;letter-spacing:0.5px">&#9889; MaxSurge</span>
          </div>
        </td></tr>
        <tr><td style="padding:40px 40px 20px">
          <h1 style="margin:0 0 20px;color:#0f172a;font-size:22px">{title}</h1>
          <div style="color:#475569;font-size:15px;line-height:1.6">{content}</div>
        </td></tr>
        <tr><td style="padding:20px 40px 30px;border-top:1px solid #e2e8f0;color:#94a3b8;font-size:12px;text-align:center">
          MaxSurge — сервис для бизнес-коммуникаций в мессенджере MAX<br/>
          <a href="https://maxsurge.ru" style="color:#6366f1;text-decoration:none">maxsurge.ru</a>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def send_welcome_email(email: str, name: str | None = None) -> bool:
    """Приветственное письмо после регистрации."""
    display = name or email.split("@")[0]
    content = f"""
    <p>Добро пожаловать в MaxSurge, <strong>{display}</strong>!</p>
    <p>Ваш аккаунт успешно создан. Вам доступен пробный период на <strong>7 дней</strong> со всеми основными функциями.</p>
    <p>Что можно сделать прямо сейчас:</p>
    <ul>
      <li>Подключить MAX аккаунт через SMS</li>
      <li>Собрать лиды из 2GIS</li>
      <li>Создать задачу рассылки</li>
      <li>Настроить AI автоответчик</li>
    </ul>
    <p style="margin-top:30px">
      <a href="https://maxsurge.ru/app/" style="display:inline-block;background:linear-gradient(135deg,#6366f1,#a855f7);color:#fff;padding:14px 30px;border-radius:8px;text-decoration:none;font-weight:600">Перейти в панель</a>
    </p>
    <p style="color:#94a3b8;font-size:13px;margin-top:30px">
      Вопросы? Пишите на <a href="mailto:support@maxsurge.ru" style="color:#6366f1">support@maxsurge.ru</a>
    </p>
    """
    return _send_email(
        email,
        "Добро пожаловать в MaxSurge",
        _base_html("Добро пожаловать!", content),
    )


def send_verify_email(email: str, token: str) -> bool:
    """Письмо с ссылкой для подтверждения email."""
    verify_url = f"https://maxsurge.ru/auth/verify?token={token}"
    content = f"""
    <p>Спасибо за регистрацию в MaxSurge!</p>
    <p>Чтобы подтвердить ваш email, нажмите кнопку ниже:</p>
    <p style="margin:30px 0">
      <a href="{verify_url}" style="display:inline-block;background:linear-gradient(135deg,#6366f1,#a855f7);color:#fff;padding:14px 30px;border-radius:8px;text-decoration:none;font-weight:600">Подтвердить email</a>
    </p>
    <p style="color:#94a3b8;font-size:13px">
      Если кнопка не работает, скопируйте ссылку в браузер:<br/>
      <a href="{verify_url}" style="color:#6366f1;word-break:break-all">{verify_url}</a>
    </p>
    <p style="color:#94a3b8;font-size:13px;margin-top:20px">
      Если вы не регистрировались на MaxSurge — просто проигнорируйте это письмо.
    </p>
    """
    return _send_email(
        email,
        "Подтвердите email на MaxSurge",
        _base_html("Подтверждение email", content),
    )


def send_password_reset_email(email: str, token: str) -> bool:
    """Письмо со ссылкой для сброса пароля."""
    reset_url = f"https://maxsurge.ru/reset-password?token={token}"
    content = f"""
    <p>Мы получили запрос на восстановление пароля для вашего аккаунта MaxSurge.</p>
    <p>Чтобы установить новый пароль, нажмите кнопку ниже:</p>
    <p style="margin:30px 0">
      <a href="{reset_url}" style="display:inline-block;background:linear-gradient(135deg,#6366f1,#a855f7);color:#fff;padding:14px 30px;border-radius:8px;text-decoration:none;font-weight:600">Сбросить пароль</a>
    </p>
    <p style="color:#94a3b8;font-size:13px">
      Ссылка действительна <strong>1 час</strong>.<br/>
      Если кнопка не работает:<br/>
      <a href="{reset_url}" style="color:#6366f1;word-break:break-all">{reset_url}</a>
    </p>
    <p style="color:#94a3b8;font-size:13px;margin-top:20px">
      Если вы не запрашивали сброс пароля — проигнорируйте это письмо.
    </p>
    """
    return _send_email(
        email,
        "Восстановление пароля MaxSurge",
        _base_html("Восстановление пароля", content),
    )



# ── Marketing email templates ────────────────────────
def send_trial_ending_email(email: str, days_left: int, name: str | None = None) -> bool:
    subject = f"MaxSurge: пробный период заканчивается через {days_left} д."
    greeting = f"Привет, {name}!" if name else "Привет!"
    body = (
        "<h2 style='color:#1e293b;margin:0 0 16px'>" + greeting + "</h2>"
        "<p>Ваш пробный период MaxSurge заканчивается через <strong>" + str(days_left) + " дн.</strong></p>"
        "<p>Чтобы не потерять данные — выберите тариф:</p>"
        "<p style='text-align:center;margin:24px 0'>"
        "<a href='https://maxsurge.ru/app/billing/' style='background:linear-gradient(135deg,#6366f1,#a855f7);color:#fff;padding:12px 32px;border-radius:8px;text-decoration:none;font-weight:600'>Выбрать тариф</a>"
        "</p>"
        "<p style='color:#94a3b8;font-size:13px'>При оплате от 3000₽ — бонусные дни бесплатно.</p>"
    )
    return _send_email(email, subject, _base_html("MaxSurge", body))


def send_upsell_email(email: str, current_plan: str, name: str | None = None) -> bool:
    subject = "MaxSurge: откройте больше возможностей"
    greeting = f"Привет, {name}!" if name else "Привет!"
    body = (
        "<h2 style='color:#1e293b;margin:0 0 16px'>" + greeting + "</h2>"
        "<p>Вы на тарифе <strong>" + current_plan + "</strong>. С апгрейдом вы получите:</p>"
        "<ul><li>Больше аккаунтов</li><li>Нейрочаттинг AI</li><li>Страж чата</li><li>A/B тесты</li></ul>"
        "<p style='text-align:center;margin:24px 0'>"
        "<a href='https://maxsurge.ru/app/billing/' style='background:linear-gradient(135deg,#6366f1,#a855f7);color:#fff;padding:12px 32px;border-radius:8px;text-decoration:none;font-weight:600'>Посмотреть тарифы</a>"
        "</p>"
    )
    return _send_email(email, subject, _base_html("MaxSurge", body))


def send_winback_email(email: str, name: str | None = None) -> bool:
    subject = "MaxSurge: скучаем по вам"
    greeting = f"Привет, {name}!" if name else "Привет!"
    body = (
        "<h2 style='color:#1e293b;margin:0 0 16px'>" + greeting + "</h2>"
        "<p>Мы добавили много нового:</p>"
        "<ul><li>Нейрочаттинг — AI маркетинг в чатах</li>"
        "<li>MAX боты — лид/бонус/саппорт</li>"
        "<li>Страж чата — автомодерация</li>"
        "<li>Click tracking — CTR аналитика</li></ul>"
        "<p style='text-align:center;margin:24px 0'>"
        "<a href='https://maxsurge.ru/app/' style='background:linear-gradient(135deg,#6366f1,#a855f7);color:#fff;padding:12px 32px;border-radius:8px;text-decoration:none;font-weight:600'>Вернуться</a>"
        "</p>"
    )
    return _send_email(email, subject, _base_html("MaxSurge", body))
