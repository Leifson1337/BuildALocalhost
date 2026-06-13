#!/usr/bin/env bash
# Post-deploy health checks. Run from the output/ directory (or pass OUTPUT_DIR).
# Verifies the gateway answers /v1/models and a tiny chat completion.
set -euo pipefail

OUTPUT_DIR="${1:-.}"
ENV_FILE="$OUTPUT_DIR/.env"

[ -f "$ENV_FILE" ] || { echo "No .env in $OUTPUT_DIR" >&2; exit 1; }

# Load key vars without exporting the whole file.
API_KEY="$(grep -E '^LITELLM_MASTER_KEY=' "$ENV_FILE" | cut -d= -f2-)"
API_DOMAIN="$(grep -E '^API_DOMAIN=' "$ENV_FILE" | cut -d= -f2- || true)"
LITELLM_PORT="$(grep -E '^.*litellm_port' "$ENV_FILE" | head -1 | grep -oE '[0-9]+' || true)"

if [ -n "${API_DOMAIN:-}" ]; then
  BASE="https://${API_DOMAIN}"
else
  BASE="http://127.0.0.1:${LITELLM_PORT:-4000}"
fi

echo "[health] Gateway base: $BASE"

echo "[health] GET /v1/models"
curl -fsS "${BASE}/v1/models" -H "Authorization: Bearer ${API_KEY}" >/dev/null \
  && echo "  ok" || { echo "  FAILED"; exit 1; }

echo "[health] POST /v1/chat/completions (smoke test)"
curl -fsS "${BASE}/v1/chat/completions" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"model":"main-chat","messages":[{"role":"user","content":"Sag kurz Hallo."}],"max_tokens":16}' \
  >/dev/null && echo "  ok" || { echo "  FAILED (engine may still be loading the model)"; exit 1; }

echo "[health] All checks passed."
