#!/usr/bin/env bash
# Export the pgvector knowledge base to a single compressed dump file.
#
# Usage:
#   ./scripts/export_kb.sh                    # writes ./kb_YYYYMMDD_HHMM.dump.gz
#   ./scripts/export_kb.sh /path/to/file.gz   # writes to a specific path
#
# Safe to run while the backend is live: pg_dump takes a transactional
# snapshot and does not lock writes.

set -euo pipefail

CONTAINER="${PGVECTOR_CONTAINER:-infrastructure-pgvector-1}"
DB_USER="${DB_USER:-user}"
DB_NAME="${DB_NAME:-firecrawl_docling_db}"

OUTPUT="${1:-kb_$(date +%Y%m%d_%H%M).dump.gz}"

echo "==> Verifying container '$CONTAINER' is running..."
if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "ERROR: container '$CONTAINER' is not running."
  echo "Start it with: cd infrastructure && docker compose up -d"
  exit 1
fi

echo "==> Snapshot of source DB:"
docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -tAc "
  SELECT format('  sources=%s pages=%s embeddings=%s',
    (SELECT COUNT(*) FROM sources),
    (SELECT COUNT(*) FROM pages),
    (SELECT COUNT(*) FROM embeddings));
"

echo "==> Dumping to: $OUTPUT"
docker exec "$CONTAINER" pg_dump \
  -U "$DB_USER" -d "$DB_NAME" \
  --format=custom \
  --no-owner \
  --no-privileges \
  | gzip -6 > "$OUTPUT"

SIZE=$(du -h "$OUTPUT" | cut -f1)
echo ""
echo "==> Done. File: $OUTPUT ($SIZE)"
echo ""
echo "Next steps:"
echo "  1. Upload '$OUTPUT' to Google Drive (or copy via USB)."
echo "  2. On the laptop, run: ./scripts/import_kb.sh $OUTPUT"
echo "  3. Also copy 'backend/.env' to the laptop separately (it has secrets)."
