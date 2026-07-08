#!/usr/bin/env bash
# ATLAS — database backup script
# Run daily via cron: 0 2 * * * /opt/atlas/scripts/backup_db.sh
set -euo pipefail

BACKUP_DIR="${ATLAS_BACKUP_DIR:-/var/backups/atlas}"
RETENTION_DAYS="${ATLAS_BACKUP_RETENTION:-30}"
TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/atlas_${TIMESTAMP}.sql.gz"

mkdir -p "${BACKUP_DIR}"

echo "[$(date -u)] Starting ATLAS database backup..."
echo "  Target: ${BACKUP_FILE}"

# Use pg_dump with custom format for parallel restore
PGPASSWORD="${DATABASE_PASSWORD:-atlas}" pg_dump \
  --host="${DATABASE_HOST:-localhost}" \
  --port="${DATABASE_PORT:-5432}" \
  --username="${DATABASE_USER:-atlas}" \
  --dbname="${DATABASE_NAME:-atlas}" \
  --format=custom \
  --compress=9 \
  --no-owner \
  --no-privileges \
  | gzip > "${BACKUP_FILE}"

BACKUP_SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
echo "[$(date -u)] Backup complete: ${BACKUP_FILE} (${BACKUP_SIZE})"

# Upload to S3 if configured
if [ -n "${S3_BACKUP_BUCKET:-}" ]; then
  echo "[$(date -u)] Uploading to S3: s3://${S3_BACKUP_BUCKET}/atlas/${TIMESTAMP}.sql.gz"
  aws s3 cp "${BACKUP_FILE}" "s3://${S3_BACKUP_BUCKET}/atlas/${TIMESTAMP}.sql.gz" \
    --sse AES256
  echo "[$(date -u)] S3 upload complete"
fi

# Cleanup old backups
echo "[$(date -u)] Cleaning backups older than ${RETENTION_DAYS} days..."
find "${BACKUP_DIR}" -name "atlas_*.sql.gz" -mtime +${RETENTION_DAYS} -delete
echo "[$(date -u)] Cleanup complete"

echo "[$(date -u)] Backup finished successfully."
