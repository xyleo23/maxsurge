#!/bin/bash
# True offsite backup: send latest DB backup to Telegram as file
# Runs after backup.sh, uses same .env for TG credentials
set -u

BACKUP_DIR="/root/max_leadfinder/backups"
LOG_FILE="$BACKUP_DIR/telegram_backup.log"

log() { echo "[$(date)] $*" >> "$LOG_FILE"; }

# Load env
if [ -f /root/max_leadfinder/.env ]; then
    set -a; . /root/max_leadfinder/.env 2>/dev/null || true; set +a
fi

if [ -z "${OWNER_TG_BOT_TOKEN:-}" ] || [ -z "${OWNER_TG_CHAT_ID:-}" ]; then
    log "FAIL: TG credentials missing"
    exit 1
fi

# Find latest backup
LATEST=$(ls -1t "$BACKUP_DIR"/maxsurge_*.db.gz 2>/dev/null | head -1)
if [ -z "$LATEST" ]; then
    log "FAIL: no backup files found"
    exit 2
fi

SIZE=$(du -h "$LATEST" | cut -f1)
NAME=$(basename "$LATEST")
CAPTION="📦 <b>MaxSurge backup</b>%0A<code>${NAME}</code> (${SIZE})%0A$(date -u '+%Y-%m-%d %H:%M UTC')"

# Send as document
RESPONSE=$(curl -s -X POST \
    "https://api.telegram.org/bot${OWNER_TG_BOT_TOKEN}/sendDocument" \
    -F "chat_id=${OWNER_TG_CHAT_ID}" \
    -F "document=@${LATEST}" \
    -F "caption=${CAPTION}" \
    -F "parse_mode=HTML" 2>&1)

if echo "$RESPONSE" | grep -q '"ok":true'; then
    log "OK sent $NAME ($SIZE)"
    exit 0
else
    log "FAIL: $RESPONSE"
    # Try sending an alert message as fallback
    curl -s -X POST "https://api.telegram.org/bot${OWNER_TG_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${OWNER_TG_CHAT_ID}" \
        --data-urlencode "text=🚨 Backup TG upload FAILED for ${NAME}" >/dev/null 2>&1
    exit 3
fi
