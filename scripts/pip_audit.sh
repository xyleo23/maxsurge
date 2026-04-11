#!/bin/bash
# Weekly dependency vulnerability scan — alerts if issues found
set -u

LOG_FILE="/root/max_leadfinder/backups/pip_audit.log"
PY="/root/max_leadfinder/venv/bin/python"

send_alert() {
    local msg="$1"
    if [ -f /root/max_leadfinder/.env ]; then
        set -a; . /root/max_leadfinder/.env 2>/dev/null || true; set +a
    fi
    if [ -n "${OWNER_TG_BOT_TOKEN:-}" ] && [ -n "${OWNER_TG_CHAT_ID:-}" ]; then
        curl -s -X POST "https://api.telegram.org/bot${OWNER_TG_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${OWNER_TG_CHAT_ID}" \
            -d "parse_mode=HTML" \
            --data-urlencode "text=🔐 <b>pip-audit</b>

${msg}" >/dev/null 2>&1 || true
    fi
}

cd /root/max_leadfinder

# Run audit — non-zero exit means vulns found
OUTPUT=$($PY -m pip_audit --progress-spinner=off 2>&1)
RC=$?

if [ $RC -eq 0 ]; then
    echo "[$(date)] OK no vulns" >> "$LOG_FILE"
    exit 0
fi

# Trim to first 30 lines for TG
SHORT=$(echo "$OUTPUT" | head -30)
echo "[$(date)] VULNS FOUND rc=$RC" >> "$LOG_FILE"
echo "$OUTPUT" >> "$LOG_FILE"
echo "---" >> "$LOG_FILE"

send_alert "Найдены уязвимые зависимости:
<pre>${SHORT:0:3000}</pre>
Полный лог: $LOG_FILE"
exit $RC
