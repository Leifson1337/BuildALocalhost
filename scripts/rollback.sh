#!/usr/bin/env bash
# Roll back to a previous image snapshot recorded by update.sh.
# Usage: scripts/rollback.sh [OUTPUT_DIR] [SNAPSHOT_FILE]
set -euo pipefail

OUTPUT_DIR="${1:-output}"
SNAPSHOT="${2:-}"

if [ -z "$SNAPSHOT" ]; then
  SNAPSHOT="$(ls -1t "$OUTPUT_DIR/.image-snapshots"/*.txt 2>/dev/null | head -1 || true)"
fi
[ -n "$SNAPSHOT" ] && [ -f "$SNAPSHOT" ] || { echo "No snapshot file. Pass one explicitly." >&2; exit 1; }

echo "[rollback] using $SNAPSHOT"
echo "[rollback] re-pinning images (digests):"
while read -r ref; do
  [ -z "$ref" ] && continue
  case "$ref" in
    sha256:*) continue;;   # bare digest lines from `images --quiet`
  esac
  echo "  $ref"
  docker pull "$ref" >/dev/null 2>&1 || echo "  [warn] could not pull $ref"
done < "$SNAPSHOT"

echo "[rollback] recreating with previous images"
( cd "$OUTPUT_DIR" && docker compose up -d )

echo "[rollback] health check"
scripts/healthcheck.sh "$OUTPUT_DIR" || echo "[rollback] still unhealthy — investigate logs."
echo "[rollback] done."
