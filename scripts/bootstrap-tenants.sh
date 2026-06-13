#!/usr/bin/env bash
# Create LiteLLM teams + virtual keys from the generated policy.yaml.
# Reads OUTPUT_DIR/configs/policy/policy.yaml and OUTPUT_DIR/.env.
# Usage: scripts/bootstrap-tenants.sh [OUTPUT_DIR]
set -euo pipefail

OUTPUT_DIR="${1:-output}"
POLICY="$OUTPUT_DIR/configs/policy/policy.yaml"
ENV_FILE="$OUTPUT_DIR/.env"

[ -f "$POLICY" ] || { echo "No policy at $POLICY (is this a multi_tenant deployment?)" >&2; exit 1; }
[ -f "$ENV_FILE" ] || { echo "No .env in $OUTPUT_DIR" >&2; exit 1; }

MASTER_KEY="$(grep -E '^LITELLM_MASTER_KEY=' "$ENV_FILE" | cut -d= -f2-)"
API_DOMAIN="$(grep -E '^API_DOMAIN=' "$ENV_FILE" | cut -d= -f2- || true)"
if [ -n "${API_DOMAIN:-}" ]; then BASE="https://${API_DOMAIN}"; else BASE="http://127.0.0.1:4000"; fi

echo "[tenants] gateway: $BASE"

# Emit one JSON object per tenant using Python (PyYAML available in the venv / on the host).
python3 - "$POLICY" <<'PY' | while IFS= read -r tenant_json; do
import sys, yaml, json
doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
for t in doc.get("tenants", []) or []:
    print(json.dumps(t))
PY
  tid=$(printf '%s' "$tenant_json" | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
  models=$(printf '%s' "$tenant_json" | python3 -c 'import sys,json;print(",".join(json.load(sys.stdin)["allow_models"]))')
  budget=$(printf '%s' "$tenant_json" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("budget_usd") or 0)')
  rpm=$(printf '%s' "$tenant_json" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("rate_limit_per_minute") or 60)')

  echo "[tenants] team=$tid models=$models budget=$budget rpm=$rpm"

  team_resp=$(curl -fsS "$BASE/team/new" \
    -H "Authorization: Bearer $MASTER_KEY" -H "Content-Type: application/json" \
    -d "{\"team_alias\":\"$tid\",\"models\":[\"${models//,/\",\"}\"],\"max_budget\":$budget,\"rpm_limit\":$rpm}" \
    || echo '{}')
  team_id=$(printf '%s' "$team_resp" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("team_id",""))' 2>/dev/null || true)

  key_resp=$(curl -fsS "$BASE/key/generate" \
    -H "Authorization: Bearer $MASTER_KEY" -H "Content-Type: application/json" \
    -d "{\"team_id\":\"$team_id\",\"key_alias\":\"$tid-key\",\"models\":[\"${models//,/\",\"}\"],\"max_budget\":$budget,\"rpm_limit\":$rpm}" \
    || echo '{}')
  key=$(printf '%s' "$key_resp" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("key",""))' 2>/dev/null || true)
  echo "  -> team_id=$team_id  key=${key:-<failed>}"
done

echo "[tenants] done. Store the printed keys securely; they are not shown again."
