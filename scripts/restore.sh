#!/usr/bin/env bash
# Restore a stack from a backup created by backup.sh.
# Usage: scripts/restore.sh BACKUP_DIR [OUTPUT_DIR]
set -euo pipefail

BACKUP_DIR="${1:?Usage: restore.sh BACKUP_DIR [OUTPUT_DIR]}"
OUTPUT_DIR="${2:-output}"

[ -d "$BACKUP_DIR" ] || { echo "Backup dir not found: $BACKUP_DIR" >&2; exit 1; }

echo "[restore] from $BACKUP_DIR -> $OUTPUT_DIR"

# 1) Configs + env + compose.
cp -r "$BACKUP_DIR/configs" "$OUTPUT_DIR/configs" 2>/dev/null || true
cp "$BACKUP_DIR/env.backup" "$OUTPUT_DIR/.env" 2>/dev/null || true
cp "$BACKUP_DIR/docker-compose.yml" "$OUTPUT_DIR/" 2>/dev/null || true

# 2) Volumes.
PROJECT="$(cd "$OUTPUT_DIR" && docker compose config --format json 2>/dev/null \
  | sed -n 's/.*"name": *"\([^"]*\)".*/\1/p' | head -1)"
for tarball in "$BACKUP_DIR"/volumes/*.tar.gz; do
  [ -e "$tarball" ] || continue
  vol="$(basename "$tarball" .tar.gz)"
  echo "[restore] volume $vol"
  docker volume create "$vol" >/dev/null
  docker run --rm -v "$vol":/data -v "$(cd "$(dirname "$tarball")" && pwd)":/in alpine \
    sh -c "rm -rf /data/* && tar xzf /in/$(basename "$tarball") -C /data" || \
    echo "  [warn] $vol restore failed"
done

# 3) Bring up DB, then load the SQL dump.
if [ -f "$BACKUP_DIR/postgres.sql" ]; then
  echo "[restore] starting postgres + loading dump"
  ( cd "$OUTPUT_DIR" && docker compose up -d postgres )
  sleep 5
  ( cd "$OUTPUT_DIR" && docker compose exec -T postgres \
      psql -U ai_stack -d ai_stack ) < "$BACKUP_DIR/postgres.sql" || \
    echo "[warn] postgres restore failed"
fi

echo "[restore] done. Start the full stack with: cd $OUTPUT_DIR && docker compose up -d"
