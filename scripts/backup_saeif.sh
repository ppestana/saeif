#!/bin/bash
set -e
BACKUP_DIR="/var/backups/saeif"
DATE=$(date +%Y%m%d_%H%M%S)
LOG="/var/log/saeif/backup.log"
source /srv/saeif/.env
BACKUP_FILE="${BACKUP_DIR}/saeif_${DATE}.sql.gz"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] A iniciar backup..." >> "$LOG"
PGPASSWORD="$DB_PASSWORD" pg_dump -h 127.0.0.1 -p 5434 -U "$DB_USER" -d "$DB_NAME" | gzip > "$BACKUP_FILE"
SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup concluído: $BACKUP_FILE ($SIZE)" >> "$LOG"
find "$BACKUP_DIR" -name "*.sql.gz" -mtime +7 -delete
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Limpeza concluída" >> "$LOG"
