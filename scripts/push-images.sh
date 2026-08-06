#!/usr/bin/env bash
set -euo pipefail

REPO="carlos0550/lead_os_test"
SHA="$(git rev-parse --short HEAD)"
SERVICES=(api-gateway auth-service tenant-service users-service files-service)

for svc in "${SERVICES[@]}"; do
  tag="${REPO}:${svc}-${SHA}"
  echo ""
  echo "===================================================="
  echo "[${svc}] building -> ${tag}"
  echo "===================================================="
  docker build \
    --file "services/${svc}/Dockerfile" \
    --tag "${tag}" \
    --tag "${REPO}:${svc}-latest" \
    .
done

echo ""
echo "===================================================="
echo "Pushing all tags"
echo "===================================================="
for svc in "${SERVICES[@]}"; do
  docker push "${REPO}:${svc}-${SHA}"
  docker push "${REPO}:${svc}-latest"
done

echo ""
echo "Done. Pushed 10 tags:"
for svc in "${SERVICES[@]}"; do
  echo "  - ${REPO}:${svc}-${SHA}"
  echo "  - ${REPO}:${svc}-latest"
done
