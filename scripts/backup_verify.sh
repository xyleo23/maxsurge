#!/bin/bash
# MaxSurge backup verification — cron-friendly
# Checks: latest backup age, size, gzip validity, SQLite integrity, off-site copy
set -u

BACKUP_DIR="/root/max_leadfinder/backups"
OFFSITE_DIR="/var/backups/maxsurge"
LOG_FILE="$BACKUP_DIR/verify.log"
MAX_AGE_HOURS=26  # допускаем небольшой slip
MIN_SIZE_BYTES=512

mkdir -p "$OFFSITE_DIR"

log() {
    echo "[$(date)] $*" >> "$LOG_FILE"
}

send_alert() {
    local msg="$1"
    log "ALERT: $msg"
    # Use env vars from /root/max_leadfinder/.env
    if [ -f /root/max_leadfinder/.env ]; then
        set -a
        . /root/max_leadfinder/.env 2>/dev/null || true
        set +a
    fi
    if [ -n "${OWNER_TG_BOT_TOKEN:-}" ] && [ -n "${OWNER_TG_CHAT_ID:-}" ]; then
        curl -s -X POST "https://api.telegram.org/bot${OWNER_TG_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${OWNER_TG_CHAT_ID}" \
            -d "parse_mode=HTML" \
            --data-urlencode "text=🚨 <b>BACKUP ALERT</b>

${msg}" >/dev/null 2>&1 || true
    fi
}

# 1. Find latest
LATEST=$(ls -1t "$BACKUP_DIR"/maxsurge_*.db.gz 2>/dev/null | head -1)
if [ -z "$LATEST" ]; then
    send_alert "Нет ни одного бэкапа в $BACKUP_DIR"
    exit 1
fi

# 2. Age check
AGE_SEC=$(( $(date +%s) - $(stat -c %Y "$LATEST") ))
AGE_HOURS=$(( AGE_SEC / 3600 ))
if [ $AGE_HOURS -gt $MAX_AGE_HOURS ]; then
    send_alert "Последний бэкап слишком старый: $(basename $LATEST) (${AGE_HOURS}ч назад, порог ${MAX_AGE_HOURS}ч)"
    exit 2
fi

# 3. Size check
SIZE=$(stat -c %s "$LATEST")
if [ $SIZE -lt $MIN_SIZE_BYTES ]; then
    send_alert "Подозрительно малый бэкап: $(basename $LATEST) = ${SIZE}B < ${MIN_SIZE_BYTES}B"
    exit 3
fi

# 4. Gzip validity
if ! gzip -t "$LATEST" 2>/dev/null; then
    send_alert "Битый gzip: $(basename $LATEST)"
    exit 4
fi

# 5. SQLite integrity test (restore to temp, check)
TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT
gunzip -c "$LATEST" > "$TMPDIR/test.db"
INTEG=$(sqlite3 "$TMPDIR/test.db" "PRAGMA integrity_check;" 2>&1)
if [ "$INTEG" != "ok" ]; then
    send_alert "SQLite integrity check FAILED для $(basename $LATEST): $INTEG"
    exit 5
fi

# 6. Row count sanity
USERS=$(sqlite3 "$TMPDIR/test.db" "SELECT COUNT(*) FROM site_users;" 2>/dev/null || echo 0)
LEADS=$(sqlite3 "$TMPDIR/test.db" "SELECT COUNT(*) FROM leads;" 2>/dev/null || echo 0)

# 7. Off-site copy + age encryption
AGE_PUB="age1wnkcz2hp4j7jfdl869vgq68n2why3ghjzapej9mz3tq6kg92vv0qx256g4"
ENCRYPTED="$OFFSITE_DIR/$(basename $LATEST).age"
if [ ! -f "$ENCRYPTED" ]; then
    age -r "$AGE_PUB" -o "$ENCRYPTED" "$LATEST" 2>/dev/null || send_alert "age encrypt failed для $(basename $LATEST)"
fi
# Оставляем также plain копию на 3 дня для быстрого восстановления
cp "$LATEST" "$OFFSITE_DIR/$(basename $LATEST)"
# Clean off-site: plain >3 дней, encrypted >30 дней
find "$OFFSITE_DIR" -name "maxsurge_*.db.gz" ! -name "*.age" -mtime +3 -delete 2>/dev/null
find "$OFFSITE_DIR" -name "*.age" -mtime +30 -delete 2>/dev/null

log "OK $(basename $LATEST) age=${AGE_HOURS}h size=${SIZE}B users=$USERS leads=$LEADS offsite=yes"
exit 0
