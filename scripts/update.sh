#!/usr/bin/env bash
# Safe update: back up, record current image digests, pull, recreate, health-check.
# On failure the operator can run rollback.sh with the saved digest file.
# Usage: scripts/update.sh [OUTPUT_DIR]
set -euo pipefail

OUTPUT_DIR="${1:-output}"
[ -f "$OUTPUT_DIR/docker-compose.yml" ] || { echo "No deployment in $OUTPUT_DIR" >&2; exit 1; }

STAMP="$(date +%Y%m%d-%H%M%S)"
SNAP="$OUTPUT_DIR/.image-snapshots"
mkdir -p "$SNAP"

echo "[update] 1/5 backup"
scripts/backup.sh "$OUTPUT_DIR" "backups" || echo "[warn] backup step had warnings"

echo "[update] 2/5 record current image digests -> $SNAP/$STAMP.txt"
( cd "$OUTPUT_DIR" && docker compose images --quiet | sort -u ) > "$SNAP/$STAMP.txt" || true
( cd "$OUTPUT_DIR" && docker compose config --images | sort -u ) >> "$SNAP/$STAMP.txt" || true

echo "[update] 3/5 pull new images"
( cd "$OUTPUT_DIR" && docker compose pull )

echo "[update] 4/5 recreate"
( cd "$OUTPUT_DIR" && docker compose up -d )

echo "[update] 5/5 health check"
if scripts/healthcheck.sh "$OUTPUT_DIR"; then
  echo "[update] success. Snapshot kept at $SNAP/$STAMP.txt for rollback."
else
  echo "[update] HEALTH CHECK FAILED. Roll back with:"
  echo "          scripts/rollback.sh $OUTPUT_DIR $SNAP/$STAMP.txt"
  exit 1
fi
