#!/usr/bin/env bash
# Resolve every image to an immutable digest and write docker-compose.pinned.yml.
# Uses `crane` if available, else `docker buildx imagetools inspect`, else `docker manifest`.
# Usage: scripts/pin-images.sh [OUTPUT_DIR]
set -euo pipefail

OUTPUT_DIR="${1:-output}"
COMPOSE="$OUTPUT_DIR/docker-compose.yml"
[ -f "$COMPOSE" ] || { echo "No deployment in $OUTPUT_DIR" >&2; exit 1; }

digest_of() {
  local img="$1"
  if command -v crane >/dev/null 2>&1; then
    crane digest "$img" 2>/dev/null && return 0
  fi
  if docker buildx imagetools inspect "$img" >/dev/null 2>&1; then
    docker buildx imagetools inspect "$img" --format '{{.Manifest.Digest}}' 2>/dev/null && return 0
  fi
  docker manifest inspect -v "$img" 2>/dev/null \
    | sed -n 's/.*"digest": *"\(sha256:[a-f0-9]*\)".*/\1/p' | head -1
}

mapfile -t IMAGES < <(cd "$OUTPUT_DIR" && docker compose config --images | sort -u)
echo "[pin] resolving ${#IMAGES[@]} image digests…"

MAP_JSON="{"
first=1
for img in "${IMAGES[@]}"; do
  d="$(digest_of "$img" || true)"
  if [ -n "$d" ]; then
    echo "  $img -> $d"
    [ $first -eq 0 ] && MAP_JSON+=","
    MAP_JSON+="\"$img\":\"$d\""
    first=0
  else
    echo "  [warn] could not resolve digest for $img"
  fi
done
MAP_JSON+="}"

python3 - "$COMPOSE" "$MAP_JSON" "$OUTPUT_DIR/docker-compose.pinned.yml" <<'PY'
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from installer.supply_chain import pin_compose
compose, mapping, dest = sys.argv[1], json.loads(sys.argv[2]), sys.argv[3]
Path(dest).write_text(pin_compose(Path(compose), mapping), encoding="utf-8")
print(f"[pin] wrote {dest}")
PY

echo "[pin] deploy the pinned file: docker compose -f docker-compose.pinned.yml up -d"
