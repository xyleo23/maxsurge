# DEPLOYMENT

Полная инструкция для деплоя MaxSurge на production сервере.

## Текущий прод

- **Сервер:** 109.196.165.67 (Debian 12, 2 CPU, 4GB RAM)
- **Домен:** maxsurge.ru (Beget DNS, Let's Encrypt через Traefik)
- **Путь:** `/root/max_leadfinder`
- **Сервис:** `systemctl ... maxsurge` (systemd)
- **Порт приложения:** 8090 (проксируется через Traefik на 443)

## Первый деплой (bootstrap)

### 1. Система

```bash
apt update && apt install -y python3 python3-venv python3-pip git sqlite3 curl \
    lsof ufw age
```

### 2. UFW firewall

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow from 172.17.0.0/16 to any port 8090  # docker→maxsurge
ufw allow from 172.18.0.0/16 to any port 8090  # traefik→maxsurge
ufw enable
```

### 3. Traefik (если нет)

Traefik должен слушать 80/443 и роутить `maxsurge.ru` → `http://host.docker.internal:8090`.
Конфигурация Traefik вне scope этого репо (уже настроен в общем docker-compose).

### 4. Клонировать код

```bash
cd /root
git clone git@github.com:xyleo23/maxsurge.git max_leadfinder
cd max_leadfinder
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/pip install 'bcrypt==4.0.1'  # pin для совместимости с passlib
```

### 5. .env конфиг

Создать `.env` со значениями:

```ini
DATABASE_URL=sqlite+aiosqlite:///./max_leadfinder.db
WEB_HOST=0.0.0.0
WEB_PORT=8090

# Админ (создаётся автоматически при старте)
ADMIN_EMAIL=admin@maxsurge.ru
ADMIN_PASSWORD=<сильный-пароль>

# Session secret (генерируется python -c "import secrets; print(secrets.token_urlsafe(64))")
SECRET_KEY=<случайная-строка-64+-символов>

# AI (OpenAI)
AI_API_URL=https://api.openai.com/v1
AI_API_KEY=sk-proj-...
AI_MODEL=gpt-4o-mini

# ЮKassa (после одобрения — production keys)
YK_SHOP_ID=1279047
YK_SECRET_KEY=live_...
YK_RETURN_URL=https://maxsurge.ru/app/billing/success

# SMTP (Яндекс 360)
SMTP_HOST=smtp.yandex.ru
SMTP_PORT=465
SMTP_USER=noreply@maxsurge.ru
SMTP_PASSWORD=<пароль-ящика>
SMTP_FROM=noreply@maxsurge.ru
SMTP_FROM_NAME=MaxSurge
SMTP_DRY_RUN=0

# Owner notifications
OWNER_TG_BOT_TOKEN=<токен-бота>
OWNER_TG_CHAT_ID=<твой-chat-id>

# Misc
DGIS_CITIES=Москва,Екатеринбург
SEND_DELAY_SEC=15
SEND_MAX_PER_ACCOUNT_DAY=30
```

Права: `chmod 600 .env`

### 6. systemd unit

`/etc/systemd/system/maxsurge.service`:

```ini
[Unit]
Description=MaxSurge FastAPI app
Documentation=https://github.com/xyleo23/maxsurge
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=10

[Service]
Type=notify
User=root
WorkingDirectory=/root/max_leadfinder
ExecStart=/root/max_leadfinder/venv/bin/python main.py
ExecStartPre=/bin/bash -c 'pids=$(/usr/bin/lsof -ti:8090 2>/dev/null || true); if [ -n "$pids" ]; then kill -9 $pids || true; sleep 1; fi'
Restart=always
WatchdogSec=90
NotifyAccess=main
RestartSec=5
SyslogIdentifier=maxsurge
KillMode=mixed
TimeoutStopSec=15

MemoryMax=2G
MemoryHigh=1500M
TasksMax=512
LimitNOFILE=65536

NoNewPrivileges=true
ProtectSystem=full
ReadWritePaths=/root/max_leadfinder /var/backups/maxsurge
PrivateTmp=true

Environment=PYTHONUNBUFFERED=1
EnvironmentFile=/root/max_leadfinder/.env

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable maxsurge
systemctl start maxsurge
systemctl status maxsurge
curl http://localhost:8090/health
```

### 7. Cron (бэкапы и мониторинг)

```cron
0 3 * * *     /root/max_leadfinder/scripts/backup.sh
30 3 * * *    /root/max_leadfinder/scripts/backup_verify.sh
35 3 * * *    /root/max_leadfinder/scripts/backup_telegram.sh
0 4 * * 0     /root/max_leadfinder/scripts/db_maintenance.sh
0 5 * * 1     /root/max_leadfinder/scripts/pip_audit.sh
0 6 * * 1     /root/max_leadfinder/scripts/secrets_audit.sh
0 8 * * *     /root/max_leadfinder/scripts/ssl_check.sh
*/5 * * * *   /root/max_leadfinder/scripts/heartbeat.sh
*/10 * * * *  /root/max_leadfinder/scripts/docker_monitor.sh
```

### 8. DNS (Beget)

- **A**: `@ → 109.196.165.67`
- **A**: `www → 109.196.165.67`
- **MX**: `@ → mx.yandex.net. (priority 10)`
- **TXT**: `@ → v=spf1 redirect=_spf.yandex.net`
- **TXT**: `mail._domainkey → v=DKIM1; k=rsa; ...` (из Яндекс 360)

### 9. Яндекс 360

1. admin.yandex.ru → подключить домен `maxsurge.ru`
2. Подтвердить через `<meta name="yandex-verification">` (уже в base.html)
3. Создать ящик `noreply@maxsurge.ru`
4. Скопировать пароль в `.env` → `SMTP_PASSWORD`

### 10. GitHub Actions (автодеплой)

В репо Settings → Secrets:
- `SSH_DEPLOY_KEY` — содержимое `/root/.ssh/github_deploy` (private key)
- `TG_BOT_TOKEN` — для notifications on failure
- `TG_CHAT_ID` — для notifications on failure

Deploy key создаётся на сервере:
```bash
ssh-keygen -t ed25519 -N '' -f /root/.ssh/github_deploy -C 'github-actions-deploy'
cat /root/.ssh/github_deploy.pub >> /root/.ssh/authorized_keys
cat /root/.ssh/github_deploy  # в GitHub Secret
```

## Обновление прод

### Автоматически
```bash
git push origin main
# GitHub Actions: pull → pip install (if requirements changed) → restart → /health check
```

### Вручную
```bash
ssh root@109.196.165.67
cd /root/max_leadfinder
git fetch origin main
git reset --hard origin/main
# Если изменился requirements.txt:
./venv/bin/pip install -r requirements.txt
systemctl restart maxsurge
sleep 3
curl -sf http://localhost:8090/health | python3 -m json.tool
```

## Откат (rollback)

```bash
cd /root/max_leadfinder
git log --oneline -10  # найти хеш предыдущего рабочего коммита
git reset --hard <hash>
systemctl restart maxsurge
```

Или восстановление БД из бэкапа:
```bash
systemctl stop maxsurge
cp max_leadfinder.db max_leadfinder.db.broken
gunzip -c backups/maxsurge_YYYY-MM-DD_HH-MM.db.gz > max_leadfinder.db
systemctl start maxsurge
curl http://localhost:8090/health
```

## Health check

```bash
curl -s https://maxsurge.ru/health | python3 -m json.tool
```

Ожидаемый output:
```json
{
  "status": "ok",
  "version": "3.0",
  "checks": {
    "db": {"ok": true, "users": 6},
    "disk": {"ok": true, "used_pct": 63.2},
    "db_file": {"ok": true, "size_mb": 0.5},
    "workers": {"bots_running": 0, "neurochat_running": 0, "guards_running": 0}
  }
}
```

## Логи

```bash
# Live логи
journalctl -u maxsurge -f

# Ошибки за последний час
journalctl -u maxsurge --since '1 hour ago' -p err

# Файловые логи loguru (10MB rotation)
tail -f /root/max_leadfinder/logs/maxsurge.log
```

## Troubleshooting

### Service не стартует
```bash
systemctl status maxsurge --no-pager
journalctl -u maxsurge -n 100 --no-pager
```
Часто причина: синтаксическая ошибка в коде или отсутствующая env-переменная.

### Port 8090 занят
```bash
lsof -i :8090
# kill stale process, systemd automatically retries
```
ExecStartPre в unit автоматически убивает застрявшие процессы.

### DB locked
SQLite в WAL mode — блокировок быть не должно. Если появились:
```bash
sqlite3 max_leadfinder.db 'PRAGMA journal_mode=WAL'
systemctl restart maxsurge
```

### SSL expired
Traefik автоматически обновляет Let's Encrypt. Если не обновил:
```bash
docker logs n8n-traefik | grep -i cert
```

### High memory
```bash
systemctl status maxsurge  # смотри Memory
# MemoryMax=2G в unit ограничивает верхний предел
# Рестарт освобождает память:
systemctl restart maxsurge
```
