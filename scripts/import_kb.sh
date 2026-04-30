#!/usr/bin/env bash
# Import a pgvector knowledge-base dump produced by export_kb.sh.
#
# Usage:
#   ./scripts/import_kb.sh kb_20260430_2015.dump.gz
#
# Prerequisites on this machine:
#   1. The pgvector container is running:
#        cd infrastructure && docker compose up -d
#   2. backend/.env exists (with DATABASE_URL pointing at the container).
#
# This will WIPE existing data in the target DB (--clean --if-exists).

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <path-to-dump.gz>"
  exit 1
fi

DUMP_FILE="$1"
CONTAINER="${PGVECTOR_CONTAINER:-infrastructure-pgvector-1}"
DB_USER="${DB_USER:-user}"
DB_NAME="${DB_NAME:-firecrawl_docling_db}"

if [[ ! -f "$DUMP_FILE" ]]; then
  echo "ERROR: dump file not found: $DUMP_FILE"
  exit 1
fi

echo "==> Verifying container '$CONTAINER' is running..."
if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "ERROR: container '$CONTAINER' is not running."
  echo "Start it with: cd infrastructure && docker compose up -d"
  exit 1
fi

echo "==> Waiting for Postgres to accept connections..."
for i in {1..30}; do
  if docker exec "$CONTAINER" pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
    break
  fi
  sleep 1
  if [[ $i -eq 30 ]]; then
    echo "ERROR: Postgres did not become ready after 30s."
    exit 1
  fi
done

echo "==> Ensuring pgvector extension is installed..."
docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" \
  -c "CREATE EXTENSION IF NOT EXISTS vector;" >/dev/null

echo "==> Restoring from: $DUMP_FILE"
echo "    (existing tables in '$DB_NAME' will be dropped and recreated)"

# Decompress on the fly and pipe into pg_restore inside the container.
# --clean drops existing objects; --if-exists tolerates a fresh DB.
gunzip -c "$DUMP_FILE" \
  | docker exec -i "$CONTAINER" pg_restore \
      -U "$DB_USER" -d "$DB_NAME" \
      --clean --if-exists \
      --no-owner --no-privileges \
      --exit-on-error

echo "==> Verifying restored counts:"
docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -tAc "
  SELECT format('  sources=%s pages=%s embeddings=%s',
    (SELECT COUNT(*) FROM sources),
    (SELECT COUNT(*) FROM pages),
    (SELECT COUNT(*) FROM embeddings));
"

echo ""
echo "==> Import complete."
echo "    Compare these counts with the source machine; they should match."
