#!/bin/bash
# Docker container health monitor — alerts when critical services die
set -u

LOG_FILE="/root/max_leadfinder/backups/docker_monitor.log"
STATE_DIR="/root/max_leadfinder/backups/docker_state"
mkdir -p "$STATE_DIR"

# Critical containers — MUST be running
CRITICAL=(
    "n8n-traefik"
    "instagram_bot_postgres"
    "instagram_bot_redis"
    "jewelry-crm-db-1"
    "jewelry-crm-backend-1"
)

send_alert() {
    local msg="$1"
    if [ -f /root/max_leadfinder/.env ]; then
        set -a; . /root/max_leadfinder/.env 2>/dev/null || true; set +a
    fi
    if [ -n "${OWNER_TG_BOT_TOKEN:-}" ] && [ -n "${OWNER_TG_CHAT_ID:-}" ]; then
        curl -s -X POST "https://api.telegram.org/bot${OWNER_TG_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${OWNER_TG_CHAT_ID}" \
            -d "parse_mode=HTML" \
            --data-urlencode "text=🐳 <b>Docker alert</b>

${msg}" >/dev/null 2>&1 || true
    fi
}

for name in "${CRITICAL[@]}"; do
    STATE_FILE="$STATE_DIR/${name//\//_}.state"
    STATUS=$(docker inspect -f '{{.State.Status}}' "$name" 2>/dev/null || echo "missing")
    PREV=""
    [ -f "$STATE_FILE" ] && PREV=$(cat "$STATE_FILE")

    if [ "$STATUS" != "running" ]; then
        if [ "$PREV" != "down" ]; then
            send_alert "Контейнер <code>${name}</code> не запущен: <b>${STATUS}</b>"
            echo "down" > "$STATE_FILE"
        fi
        echo "[$(date)] DOWN $name status=$STATUS" >> "$LOG_FILE"
    else
        # Check health if available
        HEALTH=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$name" 2>/dev/null || echo "none")
        if [ "$HEALTH" = "unhealthy" ]; then
            if [ "$PREV" != "unhealthy" ]; then
                send_alert "Контейнер <code>${name}</code>: <b>unhealthy</b>"
                echo "unhealthy" > "$STATE_FILE"
            fi
            echo "[$(date)] UNHEALTHY $name" >> "$LOG_FILE"
        else
            if [ "$PREV" = "down" ] || [ "$PREV" = "unhealthy" ]; then
                send_alert "Контейнер <code>${name}</code> восстановлен"
            fi
            echo "up" > "$STATE_FILE"
        fi
    fi
done

# Summary on first run or every 6h
COUNT_RUNNING=$(docker ps --format '{{.Names}}' 2>/dev/null | wc -l)
COUNT_TOTAL=$(docker ps -a --format '{{.Names}}' 2>/dev/null | wc -l)
echo "[$(date)] OK running=$COUNT_RUNNING/$COUNT_TOTAL" >> "$LOG_FILE"
