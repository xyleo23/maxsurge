# Playwright E2E Tests

Браузерные тесты для MaxSurge. **Активны в CI** (GitHub Actions `e2e.yml`).

## Что покрыто (21 тест)

- **public_pages** (10) — landing, login, register с legal-consent, /terms с ИНН/ОГРНИП, /privacy с 152-ФЗ, /status, /openapi 404, /api/docs 404, /metrics 401, security headers
- **auth_flow** (4) — login valid, admin redirect unauthenticated, bad login, logout
- **accounts_ui** (6) — roles CRUD via API (create/rename/delete), bulk-check-validity, catalog URL state, checker 3 режимов, posts calendar, import-contacts dual-pane
- **setup** (1) — login once, сохраняет state в `.auth/admin.json` для переиспользования

## Быстрый старт локально

```bash
cd tests/playwright
npm install
npx playwright install chromium

# Против прода (только публичные тесты)
BASE_URL=https://maxsurge.ru npx playwright test --project=public

# С авторизацией (нужны ADMIN_EMAIL / ADMIN_PASSWORD)
BASE_URL=https://maxsurge.ru \
  ADMIN_EMAIL=admin@maxsurge.ru \
  ADMIN_PASSWORD='...' \
  npx playwright test

# Интерактивный UI
npx playwright test --ui

# Debug одного теста
npx playwright test accounts_ui -g "roles CRUD" --debug

# HTML-отчёт после падения
npx playwright show-report
```

## Структура

```
tests/playwright/
├── package.json
├── playwright.config.ts       # projects: setup → public / auth / app
├── README.md                  # этот файл
├── .auth/                     # gitignored: storage state after setup
└── tests/
    ├── auth.setup.ts          # login once, saves .auth/admin.json
    ├── public_pages.spec.ts   # 10 tests
    ├── auth_flow.spec.ts      # 4 tests (serial mode, own context)
    └── accounts_ui.spec.ts    # 6 tests (uses storageState)
```

## Projects

| Project | Что тестирует | storageState |
|---------|---------------|--------------|
| `setup` | логинится и сохраняет state | — |
| `public` | публичные страницы | нет |
| `auth`  | login/logout flows | нет (свой логин) |
| `app`   | внутренние UI страницы | да (`.auth/admin.json`) |

Dependency: `app` ← `setup`. Если setup падает (rate-limit), app-тесты не запускаются.

## CI: .github/workflows/e2e.yml

Триггеры:
1. `workflow_run` — после успешного `Deploy to production` (e2e.yml подхватывает успешный деплой)
2. `pull_request` на main — проверка ветки перед мерджем
3. `workflow_dispatch` — ручной запуск

При failure:
- HTML-отчёт и трейсы сохраняются как artifacts (14 / 7 дней соответственно)
- Telegram-уведомление (если заданы `TG_BOT_TOKEN` + `TG_CHAT_ID` секреты)

## Требуемые GitHub Secrets

| Secret | Назначение | Обязателен |
|--------|-----------|------------|
| `E2E_ADMIN_EMAIL` | email для login-тестов | да |
| `E2E_ADMIN_PASSWORD` | пароль | да |
| `TG_BOT_TOKEN` | уведомления о падении | опционально |
| `TG_CHAT_ID` | куда слать | опционально |

**Рекомендация:** создайте отдельного юзера `e2e@maxsurge.ru` (PRO-тариф, не superadmin) специально для тестов. Не используйте вашего admin — если тесты часто гоняются, можно словить rate-limit на login.

```bash
# В GitHub: Settings → Secrets and variables → Actions → New secret
E2E_ADMIN_EMAIL=e2e@maxsurge.ru
E2E_ADMIN_PASSWORD=<сгенерируйте 32+ символа>
```

Создать юзера:
```python
# scripts/create_e2e_user.py (если будет нужно)
# или вручную через /app/admin/users/ под админом → создать e2e@... → назначить PRO
```

## Что НЕ покрыто (осознанно)

- **Добавление MAX-аккаунта через QR** — сжигает лимиты MAX, требует реальный телефон
- **Оплата через ЮKassa/Robokassa/Prodamus** — нужен sandbox у каждого
- **Рассылка/инвайтинг** — тронет реальных пользователей MAX
- **AI** (`/app/autoresponder`, `/app/neurochat`) — стоит денег, flaky по latency

Для этих фич — ручное прохождение чек-листа перед релизом.

## Производительность

- Локально (против maxsurge.ru): ~40 сек все 21 тестов
- В CI: ~60-80 сек (холодный старт + retries)
- Workers: 2 локально, 1 в CI (serial — не ловим rate-limit)

## Troubleshooting

**`waitForURL timeout` в auth.setup** — rate-limit на login. Ждите 10 мин, либо `systemctl restart maxsurge` на сервере чтобы сбросить in-memory счётчик.

**Flaky Alpine components** — если модалка не открылась, добавьте `await page.waitForTimeout(500)` после `click()`.

**Прод недоступен** — проверьте `/health` вручную перед запуском.
