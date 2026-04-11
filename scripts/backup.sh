#!/bin/bash
# MaxSurge DB backup script (daily cron)
set -e

BACKUP_DIR="/root/max_leadfinder/backups"
DB_FILE="/root/max_leadfinder/max_leadfinder.db"
RETENTION_DAYS=7
DATE=$(date +%Y-%m-%d_%H-%M)

mkdir -p "$BACKUP_DIR"

# SQLite backup (safe - uses .backup command)
sqlite3 "$DB_FILE" ".backup '$BACKUP_DIR/maxsurge_$DATE.db'"

# Compress
gzip -f "$BACKUP_DIR/maxsurge_$DATE.db"

# Remove old backups (>retention days)
find "$BACKUP_DIR" -name "maxsurge_*.db.gz" -mtime +$RETENTION_DAYS -delete

# Log
BACKUP_SIZE=$(du -h "$BACKUP_DIR/maxsurge_$DATE.db.gz" | cut -f1)
TOTAL_COUNT=$(ls -1 "$BACKUP_DIR"/maxsurge_*.db.gz 2>/dev/null | wc -l)
echo "[$(date)] Backup OK: maxsurge_$DATE.db.gz ($BACKUP_SIZE), total: $TOTAL_COUNT files" >> "$BACKUP_DIR/backup.log"
