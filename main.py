"""MaxSurge v3.0 — точка входа с авторизацией."""
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

sys.path.insert(0, str(Path(__file__).parent))

from config import get_settings
from db.models import init_db
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
from web.routes.blog_r import router as blog_router

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
from web.routes.admin_r import router as admin_router

settings = get_settings()

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")
logger.add("logs/maxsurge.log", rotation="10 MB", retention="7 days", level="DEBUG")

app = FastAPI(title="MaxSurge v3.0", docs_url="/api/docs")


# ── Error monitoring middleware ──────────────────
class ErrorMonitoringMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            if response.status_code >= 500:
                logger.error("HTTP {} on {}", response.status_code, request.url.path)
                on_error(f"HTTP {response.status_code}", f"Path: {request.url.path}")
            return response
        except Exception as e:
            tb = traceback.format_exc()
            logger.error("Unhandled exception on {}: {}\n{}", request.url.path, e, tb)
            on_error(f"Unhandled exception on {request.url.path}", f"{type(e).__name__}: {str(e)[:300]}")
            raise


# ── Auth middleware: protect /app/* ──────────────────
class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/app"):
            user = await get_current_user(request)
            if not user:
                return RedirectResponse("/login", status_code=303)
            request.state.user = user
        return await call_next(request)


app.add_middleware(AuthMiddleware)
app.add_middleware(ErrorMonitoringMiddleware)

# ── Public routes ──────────────────────────────────────
app.include_router(auth_router)
app.include_router(legal_router)
app.include_router(blog_router)

# ── Protected panel routes under /app ──────────────────
for r in [dashboard_router, leads_router, accounts_router, templates_router,
          sender_router, scraper_router, parser_router, checker_router,
          warming_router, profile_router, catalog_router, analytics_router,
          autoresponder_router, inviter_router, forwarder_router,
          tasks_router, files_router, admin_router, settings_router, billing_router, referral_router, twofa_router, neurochat_router, bots_router]:
    app.include_router(r, prefix="/app")


@app.on_event("startup")
async def startup():
    await init_db()
    try:
        await account_manager.restore_all()
        from max_client.neurochat import restore_running as restore_neurochat
        from max_client.bot_runner import restore_running as restore_bots
        asyncio.create_task(restore_neurochat())
        asyncio.create_task(restore_bots())
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
    asyncio.create_task(run_periodic_check(3600))
    logger.info("MaxSurge v3.0 на {}:{}", settings.WEB_HOST, settings.WEB_PORT)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "3.0"}


if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.WEB_HOST, port=settings.WEB_PORT, reload=False)
