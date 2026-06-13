#!/usr/bin/env bash
# Scan all images in a generated deployment for vulnerabilities.
# Prefers Trivy, falls back to Grype. Gracefully reports if neither is installed.
# Usage: scripts/scan-images.sh [OUTPUT_DIR] [SEVERITY]
set -euo pipefail

OUTPUT_DIR="${1:-output}"
SEVERITY="${2:-HIGH,CRITICAL}"
COMPOSE="$OUTPUT_DIR/docker-compose.yml"
[ -f "$COMPOSE" ] || { echo "No deployment in $OUTPUT_DIR" >&2; exit 1; }

mapfile -t IMAGES < <(cd "$OUTPUT_DIR" && docker compose config --images | sort -u)
echo "[scan] ${#IMAGES[@]} images (severity: $SEVERITY)"

SCANNER=""
if command -v trivy >/dev/null 2>&1; then SCANNER="trivy"
elif command -v grype >/dev/null 2>&1; then SCANNER="grype"
else
  echo "[scan] Neither trivy nor grype installed."
  echo "       Install Trivy: https://aquasecurity.github.io/trivy/  (or grype)."
  printf '  - %s\n' "${IMAGES[@]}"
  exit 2
fi
echo "[scan] using $SCANNER"

rc=0
for img in "${IMAGES[@]}"; do
  echo "──── $img ────"
  if [ "$SCANNER" = "trivy" ]; then
    trivy image --quiet --severity "$SEVERITY" --exit-code 1 "$img" || rc=1
  else
    grype "$img" --fail-on "$(echo "$SEVERITY" | cut -d, -f1 | tr '[:upper:]' '[:lower:]')" || rc=1
  fi
done

[ "$rc" -eq 0 ] && echo "[scan] no findings at $SEVERITY" || echo "[scan] vulnerabilities found (exit 1)"
exit "$rc"
