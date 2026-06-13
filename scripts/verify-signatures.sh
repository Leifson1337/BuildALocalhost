#!/usr/bin/env bash
# Verify container image signatures with cosign (keyless OIDC by default).
# Usage: scripts/verify-signatures.sh [OUTPUT_DIR] [COSIGN_IDENTITY_REGEXP] [COSIGN_ISSUER]
# Example (GitHub-built images):
#   scripts/verify-signatures.sh output '.*' 'https://token.actions.githubusercontent.com'
set -euo pipefail

OUTPUT_DIR="${1:-output}"
IDENTITY="${2:-.*}"
ISSUER="${3:-https://token.actions.githubusercontent.com}"
COMPOSE="$OUTPUT_DIR/docker-compose.yml"
[ -f "$COMPOSE" ] || { echo "No deployment in $OUTPUT_DIR" >&2; exit 1; }

if ! command -v cosign >/dev/null 2>&1; then
  echo "[verify] cosign not installed. Install: https://docs.sigstore.dev/cosign/"
  exit 2
fi

mapfile -t IMAGES < <(cd "$OUTPUT_DIR" && docker compose config --images | sort -u)
echo "[verify] ${#IMAGES[@]} images (identity=$IDENTITY issuer=$ISSUER)"

rc=0
for img in "${IMAGES[@]}"; do
  echo "──── $img ────"
  if cosign verify --certificate-identity-regexp "$IDENTITY" \
        --certificate-oidc-issuer "$ISSUER" "$img" >/dev/null 2>&1; then
    echo "  signed / verified"
  else
    echo "  [warn] no valid signature (unsigned or different issuer/identity)"
    rc=1
  fi
done

[ "$rc" -eq 0 ] && echo "[verify] all verified" || echo "[verify] some images unverified (exit 1)"
exit "$rc"
