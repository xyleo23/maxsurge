# MaxSurge

**SaaS платформа для продвижения в мессенджере MAX**

CRM + маркетинг-автоматизация: рассылки, инвайтинг, парсинг лидов, AI-чатботы, автомодерация чатов, TG→MAX форвардер.

- **Prod:** [maxsurge.ru](https://maxsurge.ru)
- **Status page:** [stats.uptimerobot.com/dYEflYerQ1](https://stats.uptimerobot.com/dYEflYerQ1)
- **Repo:** [github.com/xyleo23/maxsurge](https://github.com/xyleo23/maxsurge)

---

## Стек

- **Backend:** FastAPI + Starlette, SQLAlchemy 2.x async, aiosqlite
- **Frontend:** Jinja2 + Tailwind (CDN) + Alpine.js
- **DB:** SQLite (WAL mode)
- **MAX клиент:** [vkmax](https://pypi.org/project/vkmax/) (WebSocket userbot API)
- **Платежи:** ЮKassa
- **Почта:** Яндекс 360 SMTP (noreply@maxsurge.ru)
- **AI:** OpenAI-совместимый API (GPT-4o-mini по умолчанию)
- **Очереди:** asyncio background tasks
- **Деплой:** systemd + Traefik SSL + UFW firewall

---

## Основные фичи

### Для пользователя
- **Сбор лидов** — 2GIS парсер (+ Tampermonkey расширение), парсер участников чатов MAX
- **Рассылка** — шаблоны с AI-модерацией, A/B тесты, расписание, кампании
- **Инвайтинг** — микропаузы, лимиты, whitelist
- **MAX боты** — лид-бот, бонус-бот, AI саппорт-бот
- **Нейрочат** — AI реагирует на ключевые слова в чатах
- **Страж чата** — автомодерация (spam, flood, AI toxicity)
- **TG→MAX форвардер** — реплицирует Telegram каналы в MAX
- **CRM** — лиды, история отправок, статусы

### Для бизнеса
- **Биллинг** — ЮKassa, 4 тарифа (Start/Basic/Pro/Lifetime), бонусные дни, 7-дневный триал
- **2-уровневые рефералы** — 20% L1 + 5% L2
- **Webhook API** — сторонние CRM получают события
- **CSV import/export** — для интеграций
- **Маркетплейс шаблонов** — пользователи публикуют, другие копируют

---

## Деплой

См. [DEPLOYMENT.md](./DEPLOYMENT.md) — полная инструкция для production сервера.

**Автодеплой:** push в `main` → GitHub Actions → SSH pull → restart + health check.

**Ручной деплой:**
```bash
ssh root@109.196.165.67
cd /root/max_leadfinder
git pull
systemctl restart maxsurge
```

---

## Структура

```
max_leadfinder/
├── main.py              # FastAPI app, middleware, lifespan
├── config.py            # Pydantic Settings
├── db/
│   ├── models.py        # SQLAlchemy ORM (29 tables)
│   ├── models_onboarding.py
│   └── models_webhook.py
├── max_client/          # Бизнес-логика (async workers)
│   ├── sender.py        # Рассылка
│   ├── inviter.py       # Инвайтинг
│   ├── parser.py        # Парсер чатов MAX
│   ├── neurochat.py     # AI нейрочат
│   ├── guard.py         # Страж чата
│   ├── bot_runner.py    # MAX Bot API pollers
│   ├── email_client.py  # Transactional emails
│   └── ai_client.py     # OpenAI wrapper
├── web/
│   ├── routes/          # FastAPI routers (~45 файлов)
│   ├── templates/       # Jinja2 (55+ шаблонов)
│   └── static/          # CSS, icons, og-image
├── scripts/             # Bash cron scripts
│   ├── backup.sh
│   ├── backup_verify.sh
│   ├── backup_telegram.sh
│   ├── heartbeat.sh
│   └── ...
├── tests/
│   └── test_critical.py
├── .github/workflows/
│   └── deploy.yml
└── requirements.txt
```

---

## Мониторинг

- **UptimeRobot** — HTTP /health, 5-мин интервал, email алерт
- **Heartbeat** — curl /health с сервера, TG алерт
- **Docker monitor** — traefik/postgres/redis healthchecks
- **SSL monitor** — алерт за 14/7/3/1 дней до expiry
- **Error rate tracker** — 20 ошибок за 5мин → TG
- **Error DB** — /app/admin/errors viewer
- **Daily digest** — users/revenue/leads в TG
- **Weekly report** — воскресенье 07:00 UTC
- **/metrics** — Prometheus endpoint (15 метрик)
- **/health** — deep checks (DB, disk, workers)

---

## Безопасность

- **SSL/TLS 1.3** — Let's Encrypt
- **SSH** — key-only
- **UFW** — default deny
- **CSRF** — SameSite cookie + X-CSRF-Token
- **Security headers** — HSTS, CSP, X-Frame, X-Content, Referrer, Permissions
- **fail2ban** — persistent bans
- **Rate limits** — per-IP auth, per-user ingest
- **bcrypt** — rounds=12
- **2FA** — TOTP (Google Authenticator)
- **Audit log** — superadmin actions
- **Secrets audit** — weekly scan

---

## Бэкапы

- **Daily** 03:00 UTC — sqlite3 .backup + gzip
- **Integrity check** 03:30
- **Offsite Telegram** 03:35 — бэкап файлом в TG
- **Age encryption** — .db.gz.age offsite
- **Retention** — 7 дней локально, 30 дней encrypted
- **Restore drill** — verified

---

## Лицензия

Proprietary. © 2026 ИП Беляев Д.М. (ИНН 233304095766, ОГРНИП 318237500162964)
