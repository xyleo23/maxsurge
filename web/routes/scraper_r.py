"""Управление скрапером 2GIS."""
import asyncio
from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from web.routes._scope import get_request_user
from db.models import Lead, async_session_factory
from scraper.dgis import run_scrape
from config import get_settings

router = APIRouter(prefix="/scraper")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))
settings = get_settings()

_scrape_task: asyncio.Task | None = None
_scrape_status: dict = {"running": False, "saved": 0, "skipped": 0, "log": []}


def get_scrape_status() -> dict:
    return dict(_scrape_status)


async def _do_scrape(cities: list[str], queries: list[str], owner_id: int | None = None, proxy: str | None = None):
    global _scrape_status
    _scrape_status = {"running": True, "saved": 0, "skipped": 0, "log": []}
    try:
        results = await run_scrape(cities, queries, proxy=proxy)
        _scrape_status["log"].append(f"Собрано с 2GIS: {len(results)} записей")

        async with async_session_factory() as s:
            for r in results:
                # Проверяем дубликат по dgis_id
                existing = (await s.execute(
                    select(Lead).where(Lead.dgis_id == r["dgis_id"])
                )).scalar_one_or_none()

                if existing:
                    _scrape_status["skipped"] += 1
                    continue

                s.add(Lead(**r, owner_id=owner_id))
                _scrape_status["saved"] += 1
            await s.commit()

        _scrape_status["log"].append(f"Сохранено новых: {_scrape_status['saved']}, пропущено дублей: {_scrape_status['skipped']}")
    except Exception as e:
        _scrape_status["log"].append(f"ОШИБКА: {e}")
    finally:
        _scrape_status["running"] = False


@router.get("/", response_class=HTMLResponse)
async def scraper_page(request: Request, msg: str = ""):
    return templates.TemplateResponse(request=request, name="scraper.html", context={
        "cities": settings.cities_list,
        "queries": settings.queries_list,
        "status": get_scrape_status(),
        "msg": msg,
    })


@router.post("/start")
async def start_scrape(
    request: Request,
    cities: str = Form(""),
    queries: str = Form(""),
    proxy: str = Form(""),
):
    global _scrape_task
    if _scrape_status.get("running"):
        return RedirectResponse("/app/scraper/?msg=Скрапер+уже+работает", status_code=303)

    user = await get_request_user(request)
    owner_id = user.id if user else None
    proxy_url = proxy.strip() or getattr(settings, "SCRAPER_PROXY", "") or None

    city_list = [c.strip() for c in cities.split(",") if c.strip()] or settings.cities_list
    query_list = [q.strip() for q in queries.split(",") if q.strip()] or settings.queries_list

    _scrape_task = asyncio.create_task(_do_scrape(city_list, query_list, owner_id, proxy_url))
    return RedirectResponse("/app/scraper/?msg=Скрапер+запущен", status_code=303)


@router.get("/status")
async def scrape_status():
    return JSONResponse(get_scrape_status())
