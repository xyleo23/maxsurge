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
        "date": "2026-04-12",
        "title": "PWA, кампании, tracking, блэклист, security hardening",
        "groups": [
            {"tag": "new", "items": [
                "<strong>PWA</strong> — MaxSurge теперь устанавливается как приложение на телефон (manifest + service worker).",
                "<strong>Кампании рассылки</strong> — сохраняйте конфиги (шаблон + аудитория + A/B) и запускайте повторно одним кликом.",
                "<strong>Click Tracking</strong> — короткие ссылки с подсчётом кликов и unique IP. Вставляйте в шаблоны для CTR.",
                "<strong>Блэклист</strong> — исключайте номера/user_id из рассылки и инвайтинга. Bulk add.",
                "<strong>Mass import user_id</strong> — загрузка файла со списком ID на странице инвайтинга + live counter.",
                "<strong>Дубли лидов</strong> — поиск по телефону + merge: оставляете одного, удаляете остальных.",
                "<strong>Контакт-карточка лида</strong> — popup при клике на имя: все данные + история отправок.",
                "<strong>User webhook URL</strong> — задайте URL в настройках, MaxSurge будет POST-ить события (лиды, платежи).",
                "<strong>Экспорт парсенных ID</strong> — кнопка на парсере для вставки в инвайтер.",
                "<strong>Расписание рассылок</strong> — кнопка «Запланировать» + datetime picker. Scheduler loop 60с.",
                "<strong>Quick-reply кнопки</strong> — inline keyboard в саппорт-боте для готовых ответов.",
            ]},
            {"tag": "improve", "items": [
                "Дашборд: Chart.js графики лидов и сообщений за 14 дней.",
                "Маркетплейс шаблонов — публикация + копирование одним кликом.",
                "Онбординг расширен до 9 шагов, ссылка на /app/settings/ исправлена.",
                "Бонусные дни за крупные платежи (3000/5000/10000 -> +7/14/30д).",
                "2-уровневая реферальная программа: 20% L1 + 5% L2.",
            ]},
            {"tag": "security", "items": [
                "UFW firewall: default deny, только 22/80/443 открыты снаружи.",
                "CSRF double-submit cookie на все формы (auto-inject JS).",
                "Security HTTP headers: HSTS, CSP, X-Frame, X-Content, Referrer, Permissions.",
                "IP ban за brute-force: 10 fails / 10min -> 1h ban с TG алертом.",
                "Error rate spike detector: 20 ошибок за 5мин -> TG алерт.",
                "Admin login notify: TG + audit log при входе суперадмина.",
                "pip-audit еженедельный CVE скан (pip 24->26, закрыты 2 CVE).",
                "Secrets audit: проверка прав .env, gitignore, hardcoded secrets.",
            ]},
            {"tag": "ops", "items": [
                "/metrics Prometheus endpoint — 15 метрик для Grafana.",
                "/health deep checks — DB ping, disk, workers, db size.",
                "systemd watchdog 90s + Type=notify с sdnotify.",
                "Graceful shutdown: drain bots/guards/neurochats на SIGTERM.",
                "journald capped 500M + logrotate weekly.",
                "age-encrypted offsite backups (30d retention).",
                "Docker container monitor (traefik, postgres, redis) каждые 10мин.",
                "Error tracking DB + /app/admin/errors viewer.",
                "Weekly report (воскресенье 07:00 UTC): users/revenue/activity/errors.",
                "Ingest API rate-limit: 50 POST/мин + 1000 leads/ч на юзера.",
            ]},
        ],
    },
    {
        "date": "2026-04-11",
        "title": "Help Center, ROI-калькулятор, email онбординг",
        "groups": [
            {"tag": "new", "items": [
                "<strong>База знаний <a href=\"/help\">/help</a></strong> — 10 практических статей по быстрому старту, рассылкам, инвайтингу, парсингу 2GIS, автоответчику и безопасности. Client-side поиск по статьям.",
                "<strong>ROI-калькулятор на главной</strong> — интерактивный расчёт выручки и окупаемости MaxSurge для вашей ниши. Выбираете нишу → подставляются разумные дефолты → видите рекомендованный тариф.",
                "<strong>Email онбординг-серия</strong> — 4 письма на 0/2/5/7 день после регистрации: welcome, напоминание про 2GIS, проверка прогресса, уведомление об окончании триала. Пока в DRY_RUN режиме (логируем вместо отправки) — подключим SMTP отдельно.",
                "<strong>Отписка от рассылок</strong> — роут <code>/email/unsubscribe</code> с подписанным токеном, отдельная таблица <code>email_preferences</code>.",
                "<strong>A/B тестирование рассылок (E4)</strong> — отправляем 2 варианта на контрольную группу, выбираем победителя.",
                "<strong>Двухуровневая реферальная программа (E6)</strong> — 20% с первой линии, 5% со второй линии рефералов.",
                "<strong>Avito userscript (E5)</strong> — браузерное расширение собирает объявления с Avito в ингест API MaxSurge.",
                "<strong>Ежедневный digest + мониторинг здоровья (E7)</strong> — автоматические сводки и алерты в Telegram.",
            ]},
            {"tag": "ops", "items": [
                "Ops-скрипты: <code>backup_verify.sh</code>, <code>db_maintenance.sh</code>, <code>ssl_check.sh</code> — регулярная проверка бэкапов, чистка БД, мониторинг SSL-сертификата.",
                "Футер лендинга расширен: «База знаний» + «Журнал изменений».",
            ]},
        ],
    },
    {
        "date": "2026-04-11",
        "title": "Лендинг v2, страж чата, боты, нейрочаттинг",
        "groups": [
            {"tag": "new", "items": [
                "<strong>Страж чата (P3)</strong> — автомодерация групп с фильтрами спама, ссылок и мата.",
                "<strong>MAX Bot API (P2)</strong> — lead-боты, bonus-боты и support-боты через @MasterBot.",
                "<strong>Нейрочаттинг</strong> — AI guerrilla marketing: автоответы ботов в групповых чатах с ненавязчивым упоминанием продукта.",
                "<strong>Парсинг участников через историю (P4)</strong> — сбор user_id из истории сообщений чата (обход закрытых списков участников).",
                "<strong>Двухступенчатая модерация шаблонов (P5)</strong> — автоматическая проверка рассылочных шаблонов перед отправкой: спам-фильтр + AI-классификация.",
                "<strong>Tampermonkey userscript + public ingest API (P6)</strong> — браузерное расширение собирает данные прямо со страниц MAX и пушит в MaxSurge через публичный API-эндпоинт.",
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
