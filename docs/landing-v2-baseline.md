# Landing v2 — baseline (Шаг 1 аудита)

**Дата:** 2026-04-11
**Коммит:** `86cbd28` в ветке `feature/landing-v2`
**Файл:** `web/templates/landing.html` (58 042 B, 712 строк)
**Прод URL:** https://maxsurge.ru/

## HTTP / инфраструктура

| Параметр | Значение |
|---|---|
| HTTP код | 200 |
| Размер страницы | 58 041 B |
| Время ответа | 0.12 s |
| Процесс | host `python main.py` PID 1928095, RSS ~30 MB, uptime 1d 2h |
| Порт 8090 | занят host-процессом (не docker) |
| Ошибки в `logs/maxsurge.log` | нет (за последние 50 строк) |

## Внутренние ссылки (все проверены)

| URL | HTTP |
|---|---|
| `/` | 200 |
| `/login` | 200 |
| `/register` | 200 |
| `/about` | 200 |
| `/contacts` | 200 |
| `/blog/` | 200 |
| `/terms` | 200 |
| `/privacy` | 200 |

## Секции лендинга (все присутствуют)

- `id="metrics"` — social proof, 4 карточки
- `id="killer-2gis"` — 2GIS killer section, 4 шага
- `id="features"` — 9 карточек фич, бейджи «⭐ Киллер-фича» на 2GIS и TG→MAX
- `id="niches"` — 6 ниш бизнеса
- `id="compare"` — 2-колоночная таблица «MaxSurge vs Типичные решения» (без имён конкурентов)
- `id="pricing"` — 4 тарифа + бейдж гарантии возврата
- `id="reviews"` — 3 placeholder-отзыва (TODO: заменить реальными)
- `id="faq"` — 10 вопросов + FAQPage Schema.org
- `id="tg-support-widget"` — floating кнопка Telegram-поддержки

## Санитарные проверки

- ❌ «Единственный веб-инструмент» — отсутствует (убрано)
- ❌ «SenderMAX / MaxMstr / MaxSeller» в коде — отсутствует (убрано)
- ✅ Новый бейдж «Все инструменты для MAX в одной веб-панели» — на месте
- ✅ Цена «1 490 ₽/мес» в hero — на месте

## Известные TODO

1. **Слоган/название** — нужен финальный вариант от заказчика
2. **Telegram-виджет** — `t.me/maxsurge_support` placeholder, заменить на реальный
3. **Отзывы** — 3 placeholder-карточки с HTML-TODO, заменить или скрыть
4. **Инфра:** host-процесс без systemd/docker — нет автозапуска после ребута
5. **Смена root-пароля сервера** после работ

## Скриншоты

- `landing_desktop.png` (1440×full, 965 KB) — локально в `C:\Users\Admin\.claude\projects\`
- `landing_mobile.png` (390×full @2x, 2.2 MB) — локально там же
