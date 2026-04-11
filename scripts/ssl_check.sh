#!/bin/bash
# SSL expiry check для maxsurge.ru — алертит в TG при <14/<7/<1 день
set -u

DOMAIN="maxsurge.ru"
LOG_FILE="/root/max_leadfinder/backups/ssl.log"
STATE_FILE="/root/max_leadfinder/backups/ssl_state"

send_alert() {
    local msg="$1"
    if [ -f /root/max_leadfinder/.env ]; then
        set -a
        . /root/max_leadfinder/.env 2>/dev/null || true
        set +a
    fi
    if [ -n "${OWNER_TG_BOT_TOKEN:-}" ] && [ -n "${OWNER_TG_CHAT_ID:-}" ]; then
        curl -s -X POST "https://api.telegram.org/bot${OWNER_TG_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${OWNER_TG_CHAT_ID}" \
            -d "parse_mode=HTML" \
            --data-urlencode "text=🔒 <b>SSL ALERT</b>

${msg}" >/dev/null 2>&1 || true
    fi
}

# Get expiry
END_DATE=$(echo | openssl s_client -servername "$DOMAIN" -connect "${DOMAIN}:443" 2>/dev/null \
    | openssl x509 -noout -enddate 2>/dev/null \
    | sed 's/notAfter=//')

if [ -z "$END_DATE" ]; then
    send_alert "Не удалось получить SSL сертификат для ${DOMAIN}"
    echo "[$(date)] FAIL to fetch cert" >> "$LOG_FILE"
    exit 1
fi

END_SEC=$(date -d "$END_DATE" +%s)
NOW_SEC=$(date +%s)
DAYS_LEFT=$(( (END_SEC - NOW_SEC) / 86400 ))

# Load previous alerted state (to avoid spam)
PREV_STATE=""
[ -f "$STATE_FILE" ] && PREV_STATE=$(cat "$STATE_FILE")

THRESHOLDS=(14 7 3 1)
for t in "${THRESHOLDS[@]}"; do
    if [ $DAYS_LEFT -le $t ]; then
        if [ "$PREV_STATE" != "alerted_$t" ] && [ -z "$(echo "$PREV_STATE" | grep -E "alerted_([1-9]|1[0-3])")" ]; then
            send_alert "Сертификат <b>${DOMAIN}</b> истекает через <b>${DAYS_LEFT}</b> дней (${END_DATE}). Проверьте traefik auto-renew!"
            echo "alerted_$t" > "$STATE_FILE"
        fi
        break
    fi
done

# Reset state if healthy again
if [ $DAYS_LEFT -gt 14 ]; then
    > "$STATE_FILE"
fi

echo "[$(date)] ${DOMAIN}: ${DAYS_LEFT} days left (expires ${END_DATE})" >> "$LOG_FILE"
