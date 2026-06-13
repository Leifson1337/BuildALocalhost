#!/usr/bin/env bash
# Build / import an air-gapped bundle: all container images + the generated deployment.
# Model weights are NOT bundled by default (huge); pre-seed the hf_cache volume separately
# or pass --with-models to copy a local HF cache dir.
#
# Usage:
#   scripts/offline-bundle.sh create [OUTPUT_DIR] [BUNDLE_FILE]
#   scripts/offline-bundle.sh import BUNDLE_FILE
set -euo pipefail

CMD="${1:?Usage: offline-bundle.sh create|import ...}"

create() {
  local OUTPUT_DIR="${1:-output}" BUNDLE="${2:-ai-stack-bundle.tar}"
  [ -f "$OUTPUT_DIR/docker-compose.yml" ] || { echo "No deployment in $OUTPUT_DIR" >&2; exit 1; }
  local WORK; WORK="$(mktemp -d)"
  echo "[bundle] collecting image list"
  ( cd "$OUTPUT_DIR" && docker compose config --images | sort -u ) > "$WORK/images.txt"
  echo "[bundle] pulling images"
  while read -r img; do [ -n "$img" ] && docker pull "$img" || true; done < "$WORK/images.txt"
  echo "[bundle] saving images (this is large)"
  # shellcheck disable=SC2046
  docker save $(tr '\n' ' ' < "$WORK/images.txt") -o "$WORK/images.docker.tar"
  echo "[bundle] copying deployment"
  cp -r "$OUTPUT_DIR" "$WORK/deployment"
  tar cf "$BUNDLE" -C "$WORK" images.docker.tar images.txt deployment
  rm -rf "$WORK"
  echo "[bundle] created $BUNDLE"
}

import() {
  local BUNDLE="${1:?import needs BUNDLE_FILE}"
  local WORK; WORK="$(mktemp -d)"
  echo "[bundle] extracting"
  tar xf "$BUNDLE" -C "$WORK"
  echo "[bundle] loading images"
  docker load -i "$WORK/images.docker.tar"
  echo "[bundle] deployment available at: $WORK/deployment"
  echo "          cd $WORK/deployment && docker compose up -d"
}

case "$CMD" in
  create) shift; create "$@";;
  import) shift; import "$@";;
  *) echo "Unknown command: $CMD (use create|import)" >&2; exit 1;;
esac
