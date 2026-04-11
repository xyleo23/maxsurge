#!/bin/bash
# MaxSurge DB backup script (daily cron) — hardened with TG alerts
set -u

BACKUP_DIR="/root/max_leadfinder/backups"
DB_FILE="/root/max_leadfinder/max_leadfinder.db"
RETENTION_DAYS=7
DATE=$(date +%Y-%m-%d_%H-%M)

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
            --data-urlencode "text=🚨 BACKUP FAILED: ${msg}" >/dev/null 2>&1 || true
    fi
    echo "[$(date)] FAILED: $msg" >> "$BACKUP_DIR/backup.log"
}

trap 'send_alert "backup.sh exited at line $LINENO with status $?"' ERR

mkdir -p "$BACKUP_DIR"
set -e

sqlite3 "$DB_FILE" ".backup '$BACKUP_DIR/maxsurge_$DATE.db'"
gzip -f "$BACKUP_DIR/maxsurge_$DATE.db"

# Sanity check
if [ ! -s "$BACKUP_DIR/maxsurge_$DATE.db.gz" ]; then
    send_alert "backup file missing or empty"
    exit 1
fi

find "$BACKUP_DIR" -name "maxsurge_*.db.gz" -mtime +$RETENTION_DAYS -delete

BACKUP_SIZE=$(du -h "$BACKUP_DIR/maxsurge_$DATE.db.gz" | cut -f1)
TOTAL_COUNT=$(ls -1 "$BACKUP_DIR"/maxsurge_*.db.gz 2>/dev/null | wc -l)
echo "[$(date)] Backup OK: maxsurge_$DATE.db.gz ($BACKUP_SIZE), total: $TOTAL_COUNT files" >> "$BACKUP_DIR/backup.log"
