#!/usr/bin/env bash
# Generate a Software Bill of Materials (SBOM) for every image in the deployment.
# Uses Syft (CycloneDX JSON). Output: OUTPUT_DIR/sbom/<image>.cdx.json
# Usage: scripts/generate-sbom.sh [OUTPUT_DIR]
set -euo pipefail

OUTPUT_DIR="${1:-output}"
COMPOSE="$OUTPUT_DIR/docker-compose.yml"
[ -f "$COMPOSE" ] || { echo "No deployment in $OUTPUT_DIR" >&2; exit 1; }

if ! command -v syft >/dev/null 2>&1; then
  echo "[sbom] syft not installed. Install: https://github.com/anchore/syft"
  exit 2
fi

SBOM_DIR="$OUTPUT_DIR/sbom"
mkdir -p "$SBOM_DIR"
mapfile -t IMAGES < <(cd "$OUTPUT_DIR" && docker compose config --images | sort -u)
echo "[sbom] ${#IMAGES[@]} images -> $SBOM_DIR"

for img in "${IMAGES[@]}"; do
  safe="$(echo "$img" | tr '/:@' '___')"
  echo "  $img"
  syft "$img" -o cyclonedx-json="$SBOM_DIR/$safe.cdx.json" >/dev/null
done

echo "[sbom] done. CycloneDX SBOMs in $SBOM_DIR"
