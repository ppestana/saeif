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

# --- Backup dos produtos geoespaciais (10 Jul 2026) ---
# So os produtos derivados/finais (indices, camadas publicadas, rasters de
# risco) -- NAO as fontes brutas descarregadas (OSM portugal.gpkg, GHSL,
# INE GRID1K21_CONT/BGRI21_CONT), que sao grandes (2.5GB+) mas reproduziveis
# a partir de fontes publicas documentadas em data/*.meta.yaml. Backup de
# fontes brutas seria desperdicio de espaco para algo recuperavel por
# download; backup dos produtos finais protege contra ter de repetir horas
# de processamento (KDE, normalizacoes, combinacoes) em caso de perda de disco.
DATA_BACKUP_FILE="${BACKUP_DIR}/saeif_data_${DATE}.tar.gz"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] A iniciar backup dos produtos geoespaciais..." >> "$LOG"
cd /srv/saeif
tar -czf "$DATA_BACKUP_FILE" \
    --ignore-failed-read \
    data/*.tif \
    data/indice_i/ \
    data/layers/ \
    2>> "$LOG" || echo "[$(date '+%Y-%m-%d %H:%M:%S')] AVISO: tar terminou com avisos (ficheiros em falta nao sao criticos)" >> "$LOG"
DATA_SIZE=$(du -h "$DATA_BACKUP_FILE" | cut -f1)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup de dados concluído: $DATA_BACKUP_FILE ($DATA_SIZE)" >> "$LOG"
find "$BACKUP_DIR" -name "saeif_data_*.tar.gz" -mtime +7 -delete
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Limpeza de dados concluída" >> "$LOG"
