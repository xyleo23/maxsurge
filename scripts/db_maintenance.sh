#!/bin/bash
# Weekly DB maintenance — ротация send_logs, VACUUM, ANALYZE
set -u

DB_FILE="/root/max_leadfinder/max_leadfinder.db"
LOG_FILE="/root/max_leadfinder/backups/db_maint.log"
RETENTION_DAYS=90

log() { echo "[$(date)] $*" >> "$LOG_FILE"; }

send_alert() {
    local msg="$1"
    log "ALERT: $msg"
    if [ -f /root/max_leadfinder/.env ]; then
        set -a; . /root/max_leadfinder/.env 2>/dev/null || true; set +a
    fi
    if [ -n "${OWNER_TG_BOT_TOKEN:-}" ] && [ -n "${OWNER_TG_CHAT_ID:-}" ]; then
        curl -s -X POST "https://api.telegram.org/bot${OWNER_TG_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${OWNER_TG_CHAT_ID}" \
            --data-urlencode "text=🧹 DB maintenance: ${msg}" >/dev/null 2>&1 || true
    fi
}

trap 'send_alert "script error at line $LINENO"' ERR
set -e

# Snapshot before
SIZE_BEFORE=$(stat -c %s "$DB_FILE")
COUNTS_BEFORE=$(sqlite3 "$DB_FILE" "
    SELECT
      (SELECT COUNT(*) FROM send_logs) || '/' ||
      (SELECT COUNT(*) FROM guard_events) || '/' ||
      (SELECT COUNT(*) FROM neuro_chat_messages)
" 2>/dev/null || echo "?/?/?")

# Delete old send_logs
DEL_SL=$(sqlite3 "$DB_FILE" "DELETE FROM send_logs WHERE sent_at < datetime('now', '-${RETENTION_DAYS} days'); SELECT changes();")
DEL_GE=$(sqlite3 "$DB_FILE" "DELETE FROM guard_events WHERE created_at < datetime('now', '-${RETENTION_DAYS} days'); SELECT changes();")
DEL_NC=$(sqlite3 "$DB_FILE" "DELETE FROM neuro_chat_messages WHERE created_at < datetime('now', '-${RETENTION_DAYS} days'); SELECT changes();")

# VACUUM + ANALYZE
sqlite3 "$DB_FILE" "VACUUM;"
sqlite3 "$DB_FILE" "ANALYZE;"

SIZE_AFTER=$(stat -c %s "$DB_FILE")
SAVED_MB=$(echo "scale=2; ($SIZE_BEFORE - $SIZE_AFTER) / 1024 / 1024" | bc)

COUNTS_AFTER=$(sqlite3 "$DB_FILE" "
    SELECT
      (SELECT COUNT(*) FROM send_logs) || '/' ||
      (SELECT COUNT(*) FROM guard_events) || '/' ||
      (SELECT COUNT(*) FROM neuro_chat_messages)
" 2>/dev/null || echo "?/?/?")

log "OK delete send=$DEL_SL guard=$DEL_GE neuro=$DEL_NC | counts $COUNTS_BEFORE -> $COUNTS_AFTER | size $(($SIZE_BEFORE/1024/1024))MB -> $(($SIZE_AFTER/1024/1024))MB saved=${SAVED_MB}MB"
