# Playwright E2E Tests (draft)

Браузерные тесты для MaxSurge. **Черновик, не подключён к CI.**

## Зачем

Дополнить `scripts/e2e_smoke.sh` (curl-smoke, 22 точки) реальными user-flows:
- Регистрация + вход + выход
- Создание/переименование/удаление ролей через модалку
- Массовые действия (bulk select, присвоить роль)
- Защита от CSRF / rate-limit

`e2e_smoke.sh` ловит 80% регрессий за 3 секунды — держим его как gate.
Playwright тяжелее (2–5 мин), но ловит оставшиеся 20% — JS-ошибки, сломанные Alpine-компоненты, таймауты в fetch.

## Быстрый старт

```bash
cd tests/playwright
npm install
npx playwright install chromium
# против прода
BASE_URL=https://maxsurge.ru \
  ADMIN_EMAIL=admin@maxsurge.ru \
  ADMIN_PASSWORD='...' \
  npx playwright test
# локально
BASE_URL=http://localhost:8090 npx playwright test
# интерактивно с браузером
npx playwright test --ui
# debug одного теста
npx playwright test auth_flow -g "login with valid"  --debug
# HTML-отчёт
npx playwright show-report
```

## Структура

```
tests/playwright/
├── package.json               deps: @playwright/test
├── playwright.config.ts       config: BASE_URL, ретраи, репортёры
├── README.md                  этот файл
└── tests/
    ├── public_pages.spec.ts   10 тестов: публичные страницы, заголовки безопасности
    ├── auth_flow.spec.ts       5 тестов: login/logout/rate-limit
    └── accounts_ui.spec.ts     3 теста: роли CRUD, bulk, фильтры каталога
```

## Окружение

| Env | Назначение | Дефолт |
|-----|------------|--------|
| `BASE_URL` | host для тестирования | `https://maxsurge.ru` |
| `ADMIN_EMAIL` | для auth-тестов | если не задано — тесты skip |
| `ADMIN_PASSWORD` | для auth-тестов | если не задано — тесты skip |
| `CI` | включает retry=2 + junit-отчёт | — |

## Что НЕ покрыто (осознанно)

- **Добавление MAX-аккаунта через QR** — требует реальной сессии MAX, в тестах триггерит `login.flood`. Тестируем бэкенд отдельно через unit-тесты.
- **Оплата через ЮKassa/Robokassa/Prodamus** — нужен sandbox у каждого, настраивать per-gateway. Отложено до ручного тест-прохода после первой живой оплаты.
- **AI-моделирование** (`/app/autoresponder`, `/app/neurochat`) — зависит от LLM-провайдера (OpenAI), стоит денег, flaky по latency.

## Подключение к CI (когда будет готово)

Добавить в `.github/workflows/deploy.yml` после health-check, ДО changelog:

```yaml
- name: Install Playwright
  run: cd tests/playwright && npm ci && npx playwright install --with-deps chromium
- name: Run E2E
  env:
    BASE_URL: https://maxsurge.ru
    ADMIN_EMAIL: ${{ secrets.ADMIN_EMAIL }}
    ADMIN_PASSWORD: ${{ secrets.ADMIN_PASSWORD }}
  run: cd tests/playwright && npx playwright test --reporter=list
- name: Upload trace on failure
  if: failure()
  uses: actions/upload-artifact@v4
  with:
    name: playwright-trace
    path: tests/playwright/test-results/
```

**Не делать без:**
- Отдельного тестового admin-аккаунта (не трогать прод-админа)
- Механизма очистки тестовых данных (сейчас ролей — ок, они удаляются в тесте)
- Готовности принять 2–5 минут лишнего времени деплоя
