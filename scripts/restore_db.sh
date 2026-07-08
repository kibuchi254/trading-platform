#!/usr/bin/env bash
# ATLAS — database restore script
# Usage: ./restore_db.sh <backup_file>
set -euo pipefail

BACKUP_FILE="${1:-}"
if [ -z "${BACKUP_FILE}" ]; then
  echo "Usage: $0 <backup_file>"
  echo "Example: $0 /var/backups/atlas/atlas_20260709_020000.sql.gz"
  exit 1
fi

if [ ! -f "${BACKUP_FILE}" ]; then
  echo "Error: Backup file not found: ${BACKUP_FILE}"
  exit 1
fi

echo "[$(date -u)] Starting ATLAS database restore..."
echo "  Source: ${BACKUP_FILE}"
echo "  Target: ${DATABASE_NAME:-atlas}@${DATABASE_HOST:-localhost}"
echo ""
echo "WARNING: This will OVERWRITE the current database."
read -p "Type 'CONFIRM' to continue: " confirm
if [ "${confirm}" != "CONFIRM" ]; then
  echo "Aborted."
  exit 1
fi

echo "[$(date -u)] Dropping existing connections..."
PGPASSWORD="${DATABASE_PASSWORD:-atlas}" psql \
  --host="${DATABASE_HOST:-localhost}" \
  --port="${DATABASE_PORT:-5432}" \
  --username="${DATABASE_USER:-atlas}" \
  --dbname="postgres" \
  --command="SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${DATABASE_NAME:-atlas}' AND pid <> pg_backend_pid();"

echo "[$(date -u)] Dropping and recreating database..."
PGPASSWORD="${DATABASE_PASSWORD:-atlas}" psql \
  --host="${DATABASE_HOST:-localhost}" \
  --port="${DATABASE_PORT:-5432}" \
  --username="${DATABASE_USER:-atlas}" \
  --dbname="postgres" \
  --command="DROP DATABASE IF EXISTS ${DATABASE_NAME:-atlas}; CREATE DATABASE ${DATABASE_NAME:-atlas} OWNER ${DATABASE_USER:-atlas};"

echo "[$(date -u)] Restoring from backup..."
gunzip -c "${BACKUP_FILE}" | \
PGPASSWORD="${DATABASE_PASSWORD:-atlas}" pg_restore \
  --host="${DATABASE_HOST:-localhost}" \
  --port="${DATABASE_PORT:-5432}" \
  --username="${DATABASE_USER:-atlas}" \
  --dbname="${DATABASE_NAME:-atlas}" \
  --no-owner \
  --no-privileges \
  --clean \
  --if-exists \
  --jobs=4 \
  --verbose 2>&1 | tail -20

echo "[$(date -u)] Running migrations to ensure schema is up to date..."
alembic upgrade head

echo "[$(date -u)] Restore complete."
