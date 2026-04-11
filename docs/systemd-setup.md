# MaxSurge systemd setup

**Когда:** 2026-04-11
**Зачем:** дать host-процессу `python main.py` автозапуск после ребута, централизованные логи через `journalctl`, graceful restart через `systemctl`.

## Файл юнита

Канонический путь: `/etc/systemd/system/maxsurge.service`
Копия в репо: `ops/maxsurge.service`

## Команды

```bash
# Первичная установка
sudo cp ops/maxsurge.service /etc/systemd/system/maxsurge.service
sudo systemctl daemon-reload
sudo systemctl enable maxsurge
sudo systemctl start maxsurge

# Проверка
systemctl status maxsurge
journalctl -u maxsurge -f       # tail логов в реальном времени
journalctl -u maxsurge -n 100   # последние 100 строк

# Рестарт после деплоя кода
sudo systemctl restart maxsurge

# Остановка
sudo systemctl stop maxsurge

# Обновление юнита
sudo cp ops/maxsurge.service /etc/systemd/system/maxsurge.service
sudo systemctl daemon-reload
sudo systemctl restart maxsurge
```

## План отката (rollback)

Если сервис не поднимется после `systemctl start maxsurge`:

```bash
sudo systemctl stop maxsurge
sudo systemctl disable maxsurge
cd /root/max_leadfinder
nohup ./venv/bin/python main.py > /tmp/maxsurge.out 2>&1 &
disown
```

## Особенности

- `Restart=on-failure` + `RestartSec=5` — если процесс упадёт с ненулевым exit code, systemd поднимет через 5 сек
- `KillMode=mixed` — SIGTERM отправляется главному PID (graceful shutdown FastAPI), потом SIGKILL детям через `TimeoutStopSec=15`
- `Type=simple` — юнит считается «стартовавшим», как только ExecStart запустился. Uvicorn готов принимать трафик через ~2 сек после этого
- БД `max_leadfinder.db` — SQLite — при рестарте возможен короткий момент с WAL-локом, но uvicorn переоткроет соединения через `on_event("startup")`

## Деплой-цикл теперь

1. `git pull` (или правки через sftp)
2. `sudo systemctl restart maxsurge`
3. `journalctl -u maxsurge -n 20` (проверить старт)
4. `curl https://maxsurge.ru/health`

## Downtime при рестарте

~2–5 секунд — время на graceful shutdown uvicorn и запуск нового процесса. Если критично — надо переходить на blue/green или docker-compose с двумя репликами за traefik. Пока не критично (трафик небольшой, час пика не идентифицирован).
