#!/usr/bin/env bash
# Backup a generated stack: Postgres dump, named volumes, configs and .env.
# Usage: scripts/backup.sh [OUTPUT_DIR] [BACKUP_DIR]
set -euo pipefail

OUTPUT_DIR="${1:-output}"
BACKUP_ROOT="${2:-backups}"
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="$BACKUP_ROOT/$STAMP"
mkdir -p "$DEST/volumes"

[ -f "$OUTPUT_DIR/docker-compose.yml" ] || { echo "No deployment in $OUTPUT_DIR" >&2; exit 1; }

echo "[backup] -> $DEST"

# 1) Postgres logical dump (captures LiteLLM keys/budgets, app data).
echo "[backup] postgres dump"
( cd "$OUTPUT_DIR" && docker compose exec -T postgres \
    pg_dump -U ai_stack ai_stack ) > "$DEST/postgres.sql" || \
  echo "[warn] postgres dump failed (is the stack running?)"

# 2) Named volumes -> tarballs (model caches optionally skipped; they are large).
PROJECT="$(cd "$OUTPUT_DIR" && docker compose config --format json 2>/dev/null \
  | sed -n 's/.*"name": *"\([^"]*\)".*/\1/p' | head -1)"
echo "[backup] volumes (project: ${PROJECT:-unknown})"
for vol in $(docker volume ls --format '{{.Name}}' | grep -E "^${PROJECT}_" || true); do
  case "$vol" in
    *hf_cache*|*model_cache*) echo "  skip large cache: $vol"; continue;;
  esac
  echo "  $vol"
  docker run --rm -v "$vol":/data -v "$(pwd)/$DEST/volumes":/out alpine \
    tar czf "/out/${vol}.tar.gz" -C /data . 2>/dev/null || echo "  [warn] $vol failed"
done

# 3) Configs + env (contains secrets — protect this backup!).
echo "[backup] configs + .env"
cp -r "$OUTPUT_DIR/configs" "$DEST/configs" 2>/dev/null || true
cp "$OUTPUT_DIR/.env" "$DEST/env.backup" 2>/dev/null || true
cp "$OUTPUT_DIR/docker-compose.yml" "$DEST/" 2>/dev/null || true

echo "[backup] done. NOTE: $DEST contains secrets (.env). Store encrypted."
