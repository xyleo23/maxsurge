"""Changelog /changelog — публичная история обновлений.

Как добавить новую запись:
1. Добавьте словарь в начало списка CHANGELOG (ниже).
2. Формат: date (ISO), title (str), groups (list[dict]).
3. Каждая group: tag in {"new", "improve", "fix", "security", "ops"}, items (list[str]).
4. HTML допустим в items (ссылки, <code>, <strong>).
5. Рестарт не требуется — роут читает список в памяти при старте.
   Для мгновенного подхвата после редактирования — systemctl restart maxsurge.

Первая запись в списке = самая свежая = отображается сверху.
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


# ── Теги категорий → цвет бейджа + подпись ──────────────────
TAG_META = {
    "new":      {"label": "Новое",         "color": "emerald"},
    "improve":  {"label": "Улучшение",     "color": "indigo"},
    "fix":      {"label": "Исправление",   "color": "amber"},
    "security": {"label": "Безопасность",  "color": "rose"},
    "ops":      {"label": "Инфраструктура","color": "slate"},
}


# ── История обновлений ───────────────────────────────────────
CHANGELOG = [
    {
        "date": "2026-04-11",
        "title": "Лендинг v2, страж чата, боты, нейрочаттинг",
        "groups": [
            {"tag": "new", "items": [
                "<strong>Страж чата (P3)</strong> — автомодерация групп с фильтрами спама, ссылок и мата.",
                "<strong>MAX Bot API (P2)</strong> — lead-боты, bonus-боты и support-боты через @MasterBot.",
                "<strong>Нейрочаттинг</strong> — AI guerrilla marketing: автоответы ботов в групповых чатах с ненавязчивым упоминанием продукта.",
                "<strong>Парсинг участников (P4)</strong> — сбор user_id через историю сообщений чата.",
            ]},
            {"tag": "improve", "items": [
                "<strong>Лендинг v2:</strong> новый hero, блок метрик, killer-секция 2GIS, 9 карточек функций, 6 ниш бизнеса, сравнение с альтернативами, расширенный FAQ (10 вопросов), виджет Telegram-поддержки.",
                "<strong>FAQPage schema.org</strong> для лучшего поискового сниппета.",
                "Бейджи «киллер-фича» на 2GIS и TG→MAX форвардере в секции функций.",
            ]},
            {"tag": "ops", "items": [
                "Автозапуск сервиса через <code>systemd</code> — MaxSurge переживает перезагрузку VPS без ручного вмешательства.",
                "Git-репозиторий проекта: <a href=\"https://github.com/xyleo23/maxsurge\" target=\"_blank\" rel=\"noopener\">github.com/xyleo23/maxsurge</a>.",
            ]},
        ],
    },
    {
        "date": "2026-04-09",
        "title": "Реферальная программа, 2FA и TG→MAX форвардер",
        "groups": [
            {"tag": "new", "items": [
                "<strong>Реферальная программа:</strong> 20% с оплат приглашённых пользователей, личный кабинет реферала, ссылки с трекингом.",
                "<strong>TG→MAX форвардер:</strong> перенос аудитории из Telegram-каналов в MAX через персонализированные приглашения.",
            ]},
            {"tag": "security", "items": [
                "<strong>Двухфакторная аутентификация (2FA)</strong> через TOTP (Google Authenticator, 1Password, etc).",
            ]},
        ],
    },
    {
        "date": "2026-04-07",
        "title": "Блог, страница /about, биллинг через ЮKassa",
        "groups": [
            {"tag": "new", "items": [
                "<strong><a href=\"/blog/\">Блог</a></strong> — первые 5 SEO-статей: гайд по MAX для бизнеса, сбор лидов из 2GIS, CRM и лидогенерация, прогрев аккаунтов, AI автоответчик.",
                "<strong>Страница /about</strong> — прозрачность о работе сервиса.",
                "<strong>Биллинг:</strong> подключена ЮKassa, оплата по карте РФ, автопродление подписки.",
                "<strong>Юридические страницы:</strong> /terms, /privacy, договор-оферта.",
            ]},
        ],
    },
    {
        "date": "2026-04-05",
        "title": "AI автоответчик, парсинг чатов, каталог",
        "groups": [
            {"tag": "new", "items": [
                "<strong>AI автоответчик</strong> с эмуляцией набора «печатает…» и режимом на базе LLM.",
                "<strong>Парсинг чатов MAX:</strong> вступление в чаты и сбор user_id участников.",
                "<strong>Каталог чатов MAX</strong> с категориями для быстрого поиска целевой аудитории.",
            ]},
            {"tag": "improve", "items": [
                "Спинтакс <code>{привет|здравствуйте}</code> для уникализации сообщений.",
                "Эмуляция набора текста для обхода антиспама.",
            ]},
        ],
    },
    {
        "date": "2026-04-02",
        "title": "Публичный запуск MaxSurge v3.0",
        "groups": [
            {"tag": "new", "items": [
                "<strong>MaxSurge v3.0</strong> — веб-панель инструментов для продвижения в мессенджере MAX запущена в публичный доступ.",
                "Базовые модули: рассылка сообщений, инвайтинг в чаты, сбор лидов из 2GIS с привязкой к MAX ID, прогрев аккаунтов.",
                "4 тарифа: Trial (7 дней бесплатно), Start (1 490 ₽/мес), Basic (2 990 ₽/мес), Pro (4 990 ₽/мес).",
            ]},
        ],
    },
]


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
