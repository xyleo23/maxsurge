"""Changelog /changelog — публичная история обновлений.

Данные живут в web/data/changelog_data.py (общий модуль для веба и TG-паблишера).
Чтобы добавить запись — редактируйте changelog_data.py.
Для мгновенного подхвата после правок — systemctl restart maxsurge.
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from web.data.changelog_data import CHANGELOG, TAG_META

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _latest_entry():
    """Возвращает первую запись из CHANGELOG — для виджета «Последнее обновление» на главной."""
    return CHANGELOG[0] if CHANGELOG else None


@router.get("/changelog", response_class=HTMLResponse)
async def changelog_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="changelog.html",
        context={"entries": CHANGELOG, "tag_meta": TAG_META},
    )
