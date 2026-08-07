#!/usr/bin/env bash
set -euo pipefail

GATEWAY="${GATEWAY:-http://localhost:8000}"
EMAIL="smoke-$(date +%s)@acme.com"
PASSWORD="smoke-strong-pw"

echo "1. Onboarding"
curl -fsS -X POST "$GATEWAY/api/auth/onboarding" \
  -H "Content-Type: application/json" \
  -d "$(cat <<EOF
{
  "email": "$EMAIL",
  "password": "$PASSWORD",
  "name": "Smoke User",
  "phone": "+14155550100",
  "business_name": "Smoke Co",
  "timezone": "America/Mexico_City",
  "legal_name": "Smoke Co LLC",
  "support_inbox": "support@smoke.com"
}
EOF
)"
echo

echo "2. Wait for tenant.created to propagate (or skip if event consumer stopped)"
sleep 2

echo "3. Login"
COOKIES="$(mktemp)"
LOGIN_JSON="$(curl -fsS -i -X POST "$GATEWAY/api/auth/login" \
  -c "$COOKIES" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")"
ACCESS_TOKEN="$(echo "$LOGIN_JSON" | grep -i x-access || echo "$LOGIN_JSON" | grep '^access_token' || true)"
ACCESS_TOKEN="$(curl -fsS -X POST "$GATEWAY/api/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')"
echo "  access token acquired (length=${#ACCESS_TOKEN})"

echo "4. Validate"
curl -fsS "$GATEWAY/api/auth/validate" -H "Authorization: Bearer $ACCESS_TOKEN"
echo

echo "5. GET /me"
curl -fsS "$GATEWAY/api/auth/me" -H "Authorization: Bearer $ACCESS_TOKEN"
echo

echo "6. PATCH /me"
curl -fsS -X PATCH "$GATEWAY/api/auth/me" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"full_name":"Smoke Updated"}'
echo

echo "7. POST /me/avatar"
echo -n "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=" | base64 -d > /tmp/avatar.png
curl -fsS -X POST "$GATEWAY/api/auth/me/avatar" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -F "file=@/tmp/avatar.png;type=image/png"
echo

echo "8. GET /me/avatar (follow redirect manually to see URL)"
curl -fsS -i "$GATEWAY/api/auth/me/avatar" -H "Authorization: Bearer $ACCESS_TOKEN" | head -10
echo

echo "9. DELETE /me/avatar"
curl -fsS -X DELETE "$GATEWAY/api/auth/me/avatar" -H "Authorization: Bearer $ACCESS_TOKEN"
echo "  done"

echo "10. Logout"
curl -fsS -X POST "$GATEWAY/api/auth/logout" -H "Authorization: Bearer $ACCESS_TOKEN"
echo "  done"

echo "Done."
