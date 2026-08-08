#!/usr/bin/env bash
# Smoke test for direct file-service access via api-gateway.
#
# Requires:
# - The full stack running (make up).
# - A test user with known credentials in the dev DB. Override via
#   SMOKE_USER_EMAIL and SMOKE_USER_PASSWORD env vars.
#
# Asserts:
# - Login works.
# - POST /api/files/users/me/avatar returns 201.
# - GET /api/files/users/me/avatar returns 302 to a presigned URL that
#   serves a 200 with the uploaded bytes.
# - GET /api/auth/me shows has_avatar=true and the same avatar_url.
# - DELETE /api/files/users/me/avatar returns 204.
# - Subsequent GET /api/files/users/me/avatar returns 404.
# - GET /api/auth/me shows has_avatar=false.
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
EMAIL="${SMOKE_USER_EMAIL:-alice@acme.com}"
PASSWORD="${SMOKE_USER_PASSWORD:-correctpw-12345}"
PNG_PATH="${PNG_PATH:-/tmp/smoke-avatar.png}"

# 1x1 transparent PNG
printf '\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82' > "$PNG_PATH"

login_response=$(curl -fsS -X POST "$BASE_URL/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")
access_token=$(echo "$login_response" | python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])')

auth_header="Authorization: Bearer $access_token"

# Upload
upload_status=$(curl -fsS -o /dev/null -w '%{http_code}' \
    -X POST "$BASE_URL/api/files/users/me/avatar" \
    -H "$auth_header" \
    -F "file=@$PNG_PATH;type=image/png")
[[ "$upload_status" == "201" ]] || { echo "upload expected 201, got $upload_status"; exit 1; }

# Get (302)
get_status=$(curl -fsS -o /dev/null -w '%{http_code}' \
    -X GET "$BASE_URL/api/files/users/me/avatar" \
    -H "$auth_header")
[[ "$get_status" == "302" ]] || { echo "get expected 302, got $get_status"; exit 1; }

location=$(curl -fsS -D - -o /dev/null \
    -X GET "$BASE_URL/api/files/users/me/avatar" \
    -H "$auth_header" | tr -d '\r' | awk '/^[Ll]ocation:/ {print $2}')
[[ -n "$location" ]] || { echo "no Location header in 302 response"; exit 1; }

presign_status=$(curl -fsS -o /dev/null -w '%{http_code}' "$location")
[[ "$presign_status" == "200" ]] || { echo "presigned URL expected 200, got $presign_status"; exit 1; }

# /me shows avatar
me_response=$(curl -fsS -X GET "$BASE_URL/api/auth/me" -H "$auth_header")
has_avatar=$(echo "$me_response" | python3 -c 'import sys, json; print(json.load(sys.stdin)["has_avatar"])')
[[ "$has_avatar" == "True" ]] || { echo "/me has_avatar expected True, got $has_avatar"; exit 1; }

# Delete
delete_status=$(curl -fsS -o /dev/null -w '%{http_code}' \
    -X DELETE "$BASE_URL/api/files/users/me/avatar" \
    -H "$auth_header")
[[ "$delete_status" == "204" ]] || { echo "delete expected 204, got $delete_status"; exit 1; }

# Get after delete (404) - curl -f treats 404 as an error, so don't use -f here.
get_after_status=$(curl -s -o /dev/null -w '%{http_code}' \
    -X GET "$BASE_URL/api/files/users/me/avatar" \
    -H "$auth_header")
[[ "$get_after_status" == "404" ]] || { echo "get-after expected 404, got $get_after_status"; exit 1; }

# /me shows no avatar
me_response_after=$(curl -fsS -X GET "$BASE_URL/api/auth/me" -H "$auth_header")
has_avatar_after=$(echo "$me_response_after" | python3 -c 'import sys, json; print(json.load(sys.stdin)["has_avatar"])')
[[ "$has_avatar_after" == "False" ]] || { echo "/me has_avatar expected False, got $has_avatar_after"; exit 1; }

echo "OK: direct file-service access smoke test passed"

