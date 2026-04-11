#!/bin/bash
# External heartbeat — curl /health from the public URL, alert if down
set -u

URL="https://maxsurge.ru/health"
LOG_FILE="/root/max_leadfinder/backups/heartbeat.log"
STATE_FILE="/root/max_leadfinder/backups/heartbeat_state"

send_alert() {
    local msg="$1"
    if [ -f /root/max_leadfinder/.env ]; then
        set -a; . /root/max_leadfinder/.env 2>/dev/null || true; set +a
    fi
    if [ -n "${OWNER_TG_BOT_TOKEN:-}" ] && [ -n "${OWNER_TG_CHAT_ID:-}" ]; then
        curl -s -X POST "https://api.telegram.org/bot${OWNER_TG_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${OWNER_TG_CHAT_ID}" \
            -d "parse_mode=HTML" \
            --data-urlencode "text=❤️ <b>HEARTBEAT</b>

${msg}" >/dev/null 2>&1 || true
    fi
}

PREV_STATE=""
[ -f "$STATE_FILE" ] && PREV_STATE=$(cat "$STATE_FILE")

# Fetch with 10s timeout
RESPONSE=$(curl -sk --max-time 10 -o /tmp/heartbeat_body.json -w "%{http_code}" "$URL" 2>/dev/null)
HTTP_CODE=$RESPONSE

if [ "$HTTP_CODE" != "200" ]; then
    echo "[$(date)] DOWN http=$HTTP_CODE" >> "$LOG_FILE"
    if [ "$PREV_STATE" != "down" ]; then
        send_alert "Сайт недоступен: HTTP $HTTP_CODE
URL: $URL"
        echo "down" > "$STATE_FILE"
    fi
    exit 1
fi

# Parse JSON status
STATUS=$(cat /tmp/heartbeat_body.json | grep -o '"status":"[^"]*"' | head -1 | cut -d'"' -f4)

if [ "$STATUS" = "ok" ]; then
    if [ "$PREV_STATE" = "down" ]; then
        send_alert "Сайт восстановлен: status=ok"
    fi
    echo "up" > "$STATE_FILE"
    echo "[$(date)] OK" >> "$LOG_FILE"
elif [ "$STATUS" = "degraded" ]; then
    if [ "$PREV_STATE" != "degraded" ] && [ "$PREV_STATE" != "down" ]; then
        BODY=$(cat /tmp/heartbeat_body.json)
        send_alert "Сайт работает в degraded режиме
${BODY:0:500}"
        echo "degraded" > "$STATE_FILE"
    fi
    echo "[$(date)] DEGRADED" >> "$LOG_FILE"
else
    send_alert "Неожиданный status: $STATUS"
    echo "[$(date)] UNKNOWN status=$STATUS" >> "$LOG_FILE"
fi

rm -f /tmp/heartbeat_body.json
