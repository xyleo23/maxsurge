"""MaxSurge v3.0 — точка входа с авторизацией."""
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware

sys.path.insert(0, str(Path(__file__).parent))

from config import get_settings
from db.models import init_db
import db.models_onboarding  # noqa: F401 — register tables
import db.models_webhook  # noqa: F401 — register webhook tables  # noqa: F401 — register tables
import asyncio
import traceback
from max_client.account import account_manager
from max_client.tg_notifier import on_error
from max_client.subscription_checker import run_periodic_check

# Auth
from db.models import SiteUser, UserPlan, async_session_factory as asf
from passlib.hash import bcrypt as bcrypt_hash
from sqlalchemy import select
from web.routes.auth_r import router as auth_router, get_current_user
from web.routes.legal_r import router as legal_router
from web.routes.metrics_r import router as metrics_router
from web.routes.posts_r import router as posts_router
from web.routes.import_contacts_r import router as import_contacts_router
from web.routes.blog_r import router as blog_router
from web.routes.changelog_r import router as changelog_router
from web.routes.help_r import router as help_router
from web.routes.email_r import router as email_router
from web.routes.webhook_r import router as webhook_router
from web.routes.lead_capture_r import router as lead_capture_router

# Panel routes
from web.routes.dashboard import router as dashboard_router
from web.routes.leads import router as leads_router
from web.routes.accounts import router as accounts_router
from web.routes.templates_r import router as templates_router
from web.routes.sender_r import router as sender_router
from web.routes.scraper_r import router as scraper_router
from web.routes.parser_r import router as parser_router
from web.routes.checker_r import router as checker_router
from web.routes.warming_r import router as warming_router
from web.routes.profile_r import router as profile_router
from web.routes.catalog_r import router as catalog_router
from web.routes.analytics_r import router as analytics_router
from web.routes.autoresponder_r import router as autoresponder_router
from web.routes.inviter_r import router as inviter_router
from web.routes.forwarder_r import router as forwarder_router
from web.routes.tasks_r import router as tasks_router
from web.routes.files_r import router as files_router
from web.routes.settings_r import router as settings_router
from web.routes.billing_r import router as billing_router
from web.routes.referral_r import router as referral_router
from web.routes.twofa_r import router as twofa_router
from web.routes.neurochat_r import router as neurochat_router
from web.routes.bots_r import router as bots_router
from web.routes.guard_r import router as guard_router
from web.routes.api_ingest_r import router as api_ingest_router
from web.routes.logs_r import router as logs_router
from web.routes.csv_r import router as csv_router
from web.routes.marketplace_r import router as marketplace_router
from web.routes.blacklist_r import router as blacklist_router
from web.routes.campaigns_r import router as campaigns_router
from web.routes.tracking_r import router as tracking_router
from web.routes.notifications_r import router as notifications_router
from web.routes.admin_r import router as admin_router

settings = get_settings()

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")
logger.add("logs/maxsurge.log", rotation="10 MB", retention="7 days", level="DEBUG")

from contextlib import asynccontextmanager


def _spawn(coro, name: str):
    """asyncio.create_task + log unhandled exceptions instead of silent failure."""
    import asyncio as _asy
    async def _wrapped():
        try:
            await coro
        except _asy.CancelledError:
            raise
        except Exception as e:
            logger.exception("[lifespan] background task '{}' crashed: {}", name, e)
    return _asy.create_task(_wrapped(), name=name)


@asynccontextmanager
async def lifespan(application):
    # ── STARTUP ──
    await init_db()
    try:
        await account_manager.restore_all()
        from max_client.neurochat import restore_running as restore_neurochat
        from max_client.bot_runner import restore_running as restore_bots
        from max_client.guard import restore_running as restore_guards
        _spawn(restore_neurochat(), "restore_neurochat")
        _spawn(restore_bots(), "restore_bots")
        _spawn(restore_guards(), "restore_guards")
    except Exception as e:
        logger.warning("Сессии: {}", e)
    # Auto-create superadmin from .env
    if settings.ADMIN_EMAIL:
        async with asf() as s:
            existing = (await s.execute(select(SiteUser).where(SiteUser.email == settings.ADMIN_EMAIL))).scalar_one_or_none()
            if not existing:
                admin = SiteUser(
                    email=settings.ADMIN_EMAIL,
                    password_hash=bcrypt_hash.using(rounds=12).hash(settings.ADMIN_PASSWORD),
                    name="Admin",
                    plan=UserPlan.PRO,
                    is_superadmin=True,
                )
                s.add(admin)
                await s.commit()
                logger.info("Суперадмин создан: {}", settings.ADMIN_EMAIL)
            elif not existing.is_superadmin:
                existing.is_superadmin = True
                await s.commit()
                logger.info("Суперадмин обновлён: {}", settings.ADMIN_EMAIL)
    _spawn(run_periodic_check(3600), "subscription_checker")
    from max_client.onboarding import run_onboarding_loop
    _spawn(run_onboarding_loop(), "onboarding_loop")
    from max_client.health_digest import run_periodic_digest, check_health
    _spawn(run_periodic_digest(), "health_digest")
    _spawn(check_health(), "health_check")
    from max_client.scheduler import run_scheduler_loop
    _spawn(run_scheduler_loop(), "task_scheduler")
    from max_client.health_digest import run_periodic_weekly as _rpw
    _spawn(_rpw(), "weekly_digest")
    from max_client.account_health import run_periodic_account_health
    _spawn(run_periodic_account_health(3600), "account_health")
    from max_client.post_scheduler import run_post_scheduler_loop
    _spawn(run_post_scheduler_loop(60), "post_scheduler")

    # systemd watchdog notifier
    try:
        import sdnotify, os
        wd_usec = int(os.environ.get("WATCHDOG_USEC", "0"))
        if wd_usec > 0:
            _notifier = sdnotify.SystemdNotifier()
            _notifier.notify("READY=1")
            interval = wd_usec / 2 / 1_000_000  # seconds
            async def _wd_loop():
                while True:
                    try:
                        _notifier.notify("WATCHDOG=1")
                    except Exception:
                        pass
                    await asyncio.sleep(interval)
            asyncio.create_task(_wd_loop())
            logger.info("[watchdog] started interval={}s", interval)
    except Exception as e:
        logger.warning("[watchdog] init failed: {}", e)

    logger.info("MaxSurge v3.0 на {}:{}", settings.WEB_HOST, settings.WEB_PORT)

    yield

    # ── SHUTDOWN ──
    logger.info("[shutdown] draining workers...")
    try:
        from max_client.bot_runner import get_running_ids as _b, stop_bot as _sb
        for bid in list(_b()):
            await _sb(bid)
    except Exception as e:
        logger.warning("shutdown bots err: {}", e)
    try:
        from max_client.neurochat import get_running_ids as _n, stop_campaign as _sn
        for cid in list(_n()):
            await _sn(cid)
    except Exception as e:
        logger.warning("shutdown neuro err: {}", e)
    try:
        from max_client.guard import get_running_ids as _g, stop_guard as _sg
        for gid in list(_g()):
            await _sg(gid)
    except Exception as e:
        logger.warning("shutdown guard err: {}", e)
    try:
        from max_client.account import account_manager as _am
        await _am.disconnect_all()
    except Exception:
        pass
    logger.info("[shutdown] done")


import os as _os
_debug = _os.environ.get("DEBUG", "0") == "1"
app = FastAPI(
    title="MaxSurge v3.0",
    docs_url="/api/docs" if _debug else None,
    redoc_url=None,
    openapi_url="/openapi.json" if _debug else None,
    lifespan=lifespan,
)
from pathlib import Path as _P
_static_dir = _P(__file__).parent / "web" / "static"
_static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")






# ── CSRF (double-submit cookie) ──────────────────
import secrets as _csrf_secrets

CSRF_COOKIE = "csrf_token"
CSRF_EXEMPT_PREFIXES = (
    "/api/v1/",           # Bearer-auth API
      "/app/billing/webhook",   # ЮKassa signed webhook
      "/app/billing/webhook-rb",  # Robokassa signed webhook
    "/app/billing/webhook-pd",  # Prodamus signed webhook
    "/auth/login",        # first request has no cookie yet
    "/auth/register",
    "/auth/verify",
    "/forgot-password",
    "/reset-password",
    "/api/lead",            # public lead capture (exit intent)
    "/email/unsubscribe",   # public unsubscribe
)


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Issue cookie on any safe GET
        method = request.method.upper()
        incoming = request.cookies.get(CSRF_COOKIE)

        if method in ("POST", "PUT", "PATCH", "DELETE"):
            path = request.url.path
            if not any(path.startswith(p) for p in CSRF_EXEMPT_PREFIXES):
                # Double-submit protection (two layers):
                # 1. SameSite=Lax cookie — blocks cross-origin POSTs automatically
                # 2. If X-CSRF-Token header present (fetch/JSON calls) — strict match
                #    HTML form POSTs include _csrf as hidden field in body, which
                #    we deliberately don't read (would consume body). The SameSite
                #    cookie is sufficient protection for form-encoded submits.
                token_header = request.headers.get("x-csrf-token", "")
                if not incoming:
                    from fastapi.responses import JSONResponse
                    return JSONResponse({"error": "csrf_invalid"}, status_code=403)
                if token_header and token_header != incoming:
                    # Header was explicitly set but doesn't match — reject
                    from fastapi.responses import JSONResponse
                    return JSONResponse({"error": "csrf_invalid"}, status_code=403)

        response = await call_next(request)
        if not incoming:
            new_token = _csrf_secrets.token_urlsafe(32)
            response.set_cookie(
                CSRF_COOKIE,
                new_token,
                httponly=False,  # JS should read and inject
                samesite="lax",
                secure=True,
                max_age=7 * 86400,
            )
        return response


# ── Security headers middleware ──────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # Long cache for static assets (7 days, immutable)
        path = request.url.path
        if path.startswith("/static/qr_login/"):
            response.headers.setdefault("Cache-Control", "no-store")
        elif path.startswith("/static/") or path in ("/favicon.ico", "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png"):
            response.headers.setdefault("Cache-Control", "public, max-age=604800, immutable")
        elif path in ("/robots.txt", "/sitemap.xml"):
            response.headers.setdefault("Cache-Control", "public, max-age=3600")
        else:
            response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        # Relaxed CSP — allows Tailwind CDN and Alpine
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self' 'unsafe-inline' 'unsafe-eval' https: data: blob:; "
            "img-src 'self' https: data: blob:; "
            "frame-ancestors 'self'"
        )
        return response


# ── IP ban (fail2ban-style) with file persistence ──────────────────────
import time as _time_mod
import json as _ban_json
_failed_logins: dict[str, list[float]] = {}  # ip -> [timestamps]
_banned_ips: dict[str, float] = {}             # ip -> ban_until_ts
_FAIL_THRESHOLD = 10
_FAIL_WINDOW = 600     # 10 min
_BAN_DURATION = 3600   # 1 hour
_BAN_FILE = Path(__file__).parent / "db" / "ip_bans.json"


def _load_bans():
    """Load persisted bans on startup."""
    try:
        if _BAN_FILE.exists():
            data = _ban_json.loads(_BAN_FILE.read_text())
            now = _time_mod.time()
            for ip, until in data.items():
                if until > now:
                    _banned_ips[ip] = until
            logger.info("[fail2ban] restored {} active bans", len(_banned_ips))
    except Exception as e:
        logger.warning("[fail2ban] load error: {}", e)


def _save_bans():
    """Persist current bans to file."""
    try:
        now = _time_mod.time()
        active = {ip: until for ip, until in _banned_ips.items() if until > now}
        _BAN_FILE.write_text(_ban_json.dumps(active))
    except Exception:
        pass


_load_bans()


def record_auth_failure(ip: str):
    now = _time_mod.time()
    bucket = _failed_logins.setdefault(ip, [])
    bucket.append(now)
    _failed_logins[ip] = [t for t in bucket if now - t < _FAIL_WINDOW]
    if len(_failed_logins[ip]) >= _FAIL_THRESHOLD:
        _banned_ips[ip] = now + _BAN_DURATION
        _failed_logins[ip] = []
        _save_bans()
        logger.warning("[fail2ban] IP {} banned for {}s after {} failures", ip, _BAN_DURATION, _FAIL_THRESHOLD)
        try:
            from max_client.tg_notifier import notify_async
            notify_async(f"🚫 <b>IP banned</b>\n\n<code>{ip}</code> забанен на 1ч за {_FAIL_THRESHOLD} неудачных логинов")
        except Exception:
            pass


def is_ip_banned(ip: str) -> bool:
    until = _banned_ips.get(ip, 0)
    if until and _time_mod.time() < until:
        return True
    if until:
        del _banned_ips[ip]
        _save_bans()
    return False


class IPBanMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "")
        if ip and is_ip_banned(ip):
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "banned", "retry_after": int(_banned_ips[ip] - _time_mod.time())}, status_code=429)
        return await call_next(request)


# ── Error rate tracker ──────────────────────────
_error_counter = {"count": 0, "window_start": _time_mod.time(), "last_alert": 0.0}
_ERROR_WINDOW = 300    # 5 min
_ERROR_THRESHOLD = 20  # 20 errors in 5 min

def record_error():
    now = _time_mod.time()
    if now - _error_counter["window_start"] > _ERROR_WINDOW:
        _error_counter["count"] = 0
        _error_counter["window_start"] = now
    _error_counter["count"] += 1
    if _error_counter["count"] >= _ERROR_THRESHOLD and now - _error_counter["last_alert"] > 600:
        _error_counter["last_alert"] = now
        try:
            from max_client.tg_notifier import notify_async
            notify_async(f"🔥 <b>Error rate spike</b>\n\n{_error_counter['count']} ошибок за {_ERROR_WINDOW//60} мин")
        except Exception:
            pass


# ── Error monitoring middleware ──────────────────
async def _persist_error(request, ex_type, ex_message, traceback_text, status_code):
    try:
        from db.models import ErrorLog, async_session_factory as _asf
        ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "")
        ua = request.headers.get("user-agent", "")[:500]
        uid = None
        try:
            user = getattr(request.state, "user", None)
            if user:
                uid = user.id
        except Exception:
            pass
        async with _asf() as _s:
            _s.add(ErrorLog(
                path=str(request.url.path)[:500],
                method=request.method[:16],
                status_code=status_code,
                ex_type=(ex_type or "")[:256],
                ex_message=(ex_message or "")[:2000],
                traceback=(traceback_text or "")[:8000],
                user_id=uid,
                ip=ip[:64] if ip else None,
                user_agent=ua,
            ))
            await _s.commit()
    except Exception:
        pass


class ErrorMonitoringMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            if response.status_code >= 500:
                logger.error("HTTP {} on {}", response.status_code, request.url.path)
                on_error(f"HTTP {response.status_code}", f"Path: {request.url.path}")
                record_error()
                await _persist_error(request, "HTTPError", f"HTTP {response.status_code}", "", response.status_code)
            return response
        except Exception as e:
            tb = traceback.format_exc()
            logger.error("Unhandled exception on {}: {}\n{}", request.url.path, e, tb)
            on_error(f"Unhandled exception on {request.url.path}", f"{type(e).__name__}: {str(e)[:300]}")
            record_error()
            await _persist_error(request, type(e).__name__, str(e), tb, 500)
            raise


# ── Auth middleware: protect /app/* ──────────────────
AUTH_EXEMPT_PATHS = (
    "/app/billing/webhook",
    "/app/billing/webhook-rb",  # ЮKassa signed webhook — no auth needed
)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/app") and not any(path.startswith(p) for p in AUTH_EXEMPT_PATHS):
            user = await get_current_user(request)
            if not user:
                return RedirectResponse("/login", status_code=303)
            request.state.user = user
        return await call_next(request)


app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(IPBanMiddleware)
app.add_middleware(ErrorMonitoringMiddleware)

# ── Public routes ──────────────────────────────────────
app.include_router(auth_router)
app.include_router(legal_router)
app.include_router(metrics_router)
app.include_router(posts_router, prefix="/app")
app.include_router(import_contacts_router, prefix="/app")
app.include_router(blog_router)
from web.routes.contact_r import router as contact_router
app.include_router(contact_router)
app.include_router(api_ingest_router)
app.include_router(tracking_router)
app.include_router(changelog_router)
app.include_router(help_router)
app.include_router(email_router)
app.include_router(lead_capture_router)

# ── Protected webhook management under /app ──────────────────
app.include_router(webhook_router, prefix="/app")

# ── Protected panel routes under /app ──────────────────
for r in [dashboard_router, leads_router, accounts_router, templates_router,
          sender_router, scraper_router, parser_router, checker_router,
          warming_router, profile_router, catalog_router, analytics_router,
          autoresponder_router, inviter_router, forwarder_router,
          tasks_router, files_router, admin_router, settings_router, billing_router, referral_router, twofa_router, neurochat_router, bots_router, guard_router, logs_router, csv_router, marketplace_router, notifications_router, blacklist_router, campaigns_router]:
    app.include_router(r, prefix="/app")






from fastapi.responses import FileResponse as _FR


@app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
async def favicon():
    return _FR("web/static/favicon.ico", media_type="image/x-icon")


@app.get("/apple-touch-icon.png", include_in_schema=False)
@app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
async def apple_icon():
    return _FR("web/static/apple-touch-icon.png", media_type="image/png")


@app.api_route("/health", methods=["GET", "HEAD"])
async def health(request: Request):
    """Health check — minimal public, detail requires Basic auth (same as /metrics).

    - Public  GET /health           -> {status, version}  (for UptimeRobot, Traefik probe)
    - Admin   GET /health?detail=1  -> + checks dict     (requires ADMIN_EMAIL/PASSWORD Basic)
    """
    import shutil as _sh
    import os as _os
    import time as _time
    from sqlalchemy import text as _text, select as _sel, func as _func
    from db.models import MaxAccount, AccountStatus, SiteUser, async_session_factory as _asf

    status = "ok"
    checks = {}

    # DB ping
    try:
        async with _asf() as _s:
            await _s.execute(_text("SELECT 1"))
        checks["db"] = {"ok": True}
    except Exception as e:
        status = "degraded"
        checks["db"] = {"ok": False, "error": str(e)[:200]}

    # Disk
    try:
        du = _sh.disk_usage("/")
        pct = round(du.used / du.total * 100, 1)
        checks["disk"] = {"ok": pct < 95, "used_pct": pct, "free_gb": round(du.free / 1e9, 1)}
        if pct >= 95:
            status = "degraded"
    except Exception as e:
        checks["disk"] = {"ok": False, "error": str(e)[:100]}

    # DB size
    try:
        db_path = "max_leadfinder.db"
        if _os.path.exists(db_path):
            db_mb = round(_os.path.getsize(db_path) / 1024 / 1024, 2)
            checks["db_file"] = {"ok": True, "size_mb": db_mb}
    except Exception as e:
        checks["db_file"] = {"ok": False, "error": str(e)[:100]}

    # Background tasks alive
    try:
        from max_client.bot_runner import get_running_ids as _bot_ids
        from max_client.neurochat import get_running_ids as _neuro_ids
        from max_client.guard import get_running_ids as _guard_ids
        checks["workers"] = {
            "bots_running": len(_bot_ids()),
            "neurochat_running": len(_neuro_ids()),
            "guards_running": len(_guard_ids()),
        }
    except Exception as e:
        checks["workers"] = {"error": str(e)[:100]}

    # Public response: always minimal
    response = {"status": status, "version": "3.0", "timestamp": int(_time.time())}

    # Detailed checks only with Basic auth matching ADMIN_EMAIL/PASSWORD
    if request.query_params.get("detail") == "1":
        import base64 as _b64
        auth = request.headers.get("authorization", "")
        authorized = False
        if auth.lower().startswith("basic "):
            try:
                u, p = _b64.b64decode(auth[6:]).decode("utf-8").split(":", 1)
                authorized = (u == settings.ADMIN_EMAIL and p == settings.ADMIN_PASSWORD)
            except Exception:
                pass
        if authorized:
            response["checks"] = checks
        else:
            from fastapi.responses import JSONResponse as _JR
            return _JR(
                {"status": status, "version": "3.0", "detail": "auth_required"},
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="health-detail"'},
            )

    return response






# ── Custom error pages ──────────────────────────
from fastapi.responses import HTMLResponse as _HTMLResp

_ERROR_404_HTML = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>404 — Страница не найдена | MaxSurge</title><link rel="icon" href="/favicon.ico"><style>body{margin:0;font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:linear-gradient(135deg,#0f172a,#1e293b);color:#e2e8f0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}.box{text-align:center;max-width:500px}.code{font-size:120px;font-weight:900;background:linear-gradient(135deg,#6366f1,#a855f7,#ec4899);-webkit-background-clip:text;-webkit-text-fill-color:transparent;line-height:1;margin-bottom:20px}h1{font-size:28px;margin:0 0 16px}p{color:#94a3b8;margin:0 0 30px;line-height:1.6}a{display:inline-block;background:linear-gradient(135deg,#6366f1,#a855f7);color:#fff;padding:14px 32px;border-radius:10px;text-decoration:none;font-weight:600}a:hover{opacity:0.9}</style></head><body><div class="box"><div class="code">404</div><h1>Страница не найдена</h1><p>Кажется, такой страницы нет. Возможно, адрес введён неверно или страница была удалена.</p><a href="/">← На главную</a></div></body></html>"""

_ERROR_500_HTML = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>500 — Внутренняя ошибка | MaxSurge</title><link rel="icon" href="/favicon.ico"><style>body{margin:0;font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:linear-gradient(135deg,#0f172a,#1e293b);color:#e2e8f0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}.box{text-align:center;max-width:500px}.code{font-size:120px;font-weight:900;background:linear-gradient(135deg,#ef4444,#f97316);-webkit-background-clip:text;-webkit-text-fill-color:transparent;line-height:1;margin-bottom:20px}h1{font-size:28px;margin:0 0 16px}p{color:#94a3b8;margin:0 0 30px;line-height:1.6}a{display:inline-block;background:linear-gradient(135deg,#6366f1,#a855f7);color:#fff;padding:14px 32px;border-radius:10px;text-decoration:none;font-weight:600}a:hover{opacity:0.9}</style></head><body><div class="box"><div class="code">500</div><h1>Что-то пошло не так</h1><p>Произошла внутренняя ошибка сервера. Мы уже получили уведомление и работаем над решением.</p><a href="/">← На главную</a></div></body></html>"""


from fastapi.exceptions import HTTPException as _HTTPExc
from starlette.exceptions import HTTPException as _StarletteHTTPExc

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    if request.url.path.startswith("/api/") or request.headers.get("accept", "").startswith("application/json"):
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "not_found"}, status_code=404)
    return _HTMLResp(_ERROR_404_HTML, status_code=404)


@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    if request.url.path.startswith("/api/") or request.headers.get("accept", "").startswith("application/json"):
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "internal_server_error"}, status_code=500)
    return _HTMLResp(_ERROR_500_HTML, status_code=500)


@app.get("/metrics")
async def metrics():
    """Prometheus text format. Scrape-safe, no auth (only counts, no PII)."""
    import shutil as _sh, os as _os
    from fastapi.responses import PlainTextResponse
    from sqlalchemy import select as _sel, func as _fn
    from db.models import (
        SiteUser, Lead, SendLog, MaxAccount, AccountStatus, Task, TaskStatus,
        Payment, PaymentStatus, async_session_factory as _asf,
    )

    lines = []
    def m(name, value, help_txt, mtype="gauge"):
        lines.append(f"# HELP {name} {help_txt}")
        lines.append(f"# TYPE {name} {mtype}")
        lines.append(f"{name} {value}")

    try:
        async with _asf() as _s:
            users = (await _s.execute(_sel(_fn.count(SiteUser.id)))).scalar() or 0
            leads = (await _s.execute(_sel(_fn.count(Lead.id)))).scalar() or 0
            sent_total = (await _s.execute(
                _sel(_fn.count(SendLog.id)).where(SendLog.status == "sent")
            )).scalar() or 0
            sent_failed = (await _s.execute(
                _sel(_fn.count(SendLog.id)).where(SendLog.status == "failed")
            )).scalar() or 0
            acc_active = (await _s.execute(
                _sel(_fn.count(MaxAccount.id)).where(MaxAccount.status == AccountStatus.ACTIVE)
            )).scalar() or 0
            acc_blocked = (await _s.execute(
                _sel(_fn.count(MaxAccount.id)).where(MaxAccount.status == AccountStatus.BLOCKED)
            )).scalar() or 0
            tasks_running = (await _s.execute(
                _sel(_fn.count(Task.id)).where(Task.status == TaskStatus.RUNNING)
            )).scalar() or 0
            payments_ok = (await _s.execute(
                _sel(_fn.count(Payment.id)).where(Payment.status == PaymentStatus.SUCCEEDED)
            )).scalar() or 0
            revenue = (await _s.execute(
                _sel(_fn.coalesce(_fn.sum(Payment.amount), 0)).where(Payment.status == PaymentStatus.SUCCEEDED)
            )).scalar() or 0.0

        m("maxsurge_users_total", users, "Total registered users")
        m("maxsurge_leads_total", leads, "Total leads across all users")
        m("maxsurge_messages_sent_total", sent_total, "Successful sendlog entries", "counter")
        m("maxsurge_messages_failed_total", sent_failed, "Failed sendlog entries", "counter")
        m("maxsurge_accounts_active", acc_active, "MAX accounts in ACTIVE state")
        m("maxsurge_accounts_blocked", acc_blocked, "MAX accounts in BLOCKED state")
        m("maxsurge_tasks_running", tasks_running, "Tasks in RUNNING state")
        m("maxsurge_payments_succeeded_total", payments_ok, "Successful payment count", "counter")
        m("maxsurge_revenue_rub_total", float(revenue), "Total revenue RUB", "counter")
    except Exception as e:
        lines.append(f"# maxsurge_db_error 1 ({e})")

    # Workers
    try:
        from max_client.bot_runner import get_running_ids as _bi
        from max_client.neurochat import get_running_ids as _ni
        from max_client.guard import get_running_ids as _gi
        m("maxsurge_bots_running", len(_bi()), "Running MAX bot API pollers")
        m("maxsurge_neurochat_running", len(_ni()), "Running neurochat campaigns")
        m("maxsurge_guards_running", len(_gi()), "Running chat guards")
    except Exception:
        pass

    # System
    try:
        du = _sh.disk_usage("/")
        m("maxsurge_disk_used_pct", round(du.used / du.total * 100, 2), "Disk usage percent")
        m("maxsurge_disk_free_bytes", du.free, "Free disk bytes")
        if _os.path.exists("max_leadfinder.db"):
            m("maxsurge_db_size_bytes", _os.path.getsize("max_leadfinder.db"), "DB file size")
    except Exception:
        pass

    # Error rate & bans
    try:
        m("maxsurge_error_counter", _error_counter.get("count", 0), "Errors in current 5min window", "counter")
        m("maxsurge_banned_ips", len(_banned_ips), "Currently banned IPs")
    except Exception:
        pass

    body = "\n".join(lines) + "\n"
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4; charset=utf-8")


if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.WEB_HOST, port=settings.WEB_PORT, reload=False)
