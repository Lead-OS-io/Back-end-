#!/usr/bin/env bash
set -euo pipefail

ROLE=${SERVICE_ROLE:-web}

echo "Starting service role: $ROLE"

start_service() {
  local service_name="$1"
  local port="$2"
  local app_dir="services/$service_name"

  # Check if service directory exists
  if [ ! -d "$app_dir" ]; then
    echo "Warning: Service directory $app_dir not found, skipping..."
    return 0
  fi

  echo "Starting internal $service_name on 127.0.0.1:$port"
  uvicorn main:app \
    --app-dir "$app_dir" \
    --host 127.0.0.1 \
    --port "$port" \
    --log-level error \
    --no-access-log &
  
  # Optional: Wait briefly/check logic could go here, but doing it for all 8+ services sequentially slows boot too much.
  # We assume they start. Logs are redirected.
}

# Boot all microservices automatically (Monolith of services architecture) only if ROLE is web.
# Set BOOT_INTERNAL_SERVICES=false when the services run as separate containers (docker-compose).
if [ "$ROLE" = "web" ] && [ "${BOOT_INTERNAL_SERVICES:-true}" = "true" ]; then
  # Auth Service
  start_service "auth-service" 8001

  # Tenant Service (Essential for DB routing)
  start_service "tenant-service" 8002

  # Cases Service (cases, drafts, book-of-business, medical reference data)
  start_service "cases-service" 8004

  # Users Service
  start_service "users-service" 8005

  # News Service (Admin Alerts)
  start_service "news-service" 8006

  # Files Service
  start_service "files-service" 8011

  echo "All internal microservices initiated."
  # Grace period: allow internal services time to bind ports before starting the main web process
  sleep 2
fi

case "$ROLE" in
  web)
    echo "Starting Uvicorn on PORT=${PORT:-8000}"
    exec uvicorn main:app --host=0.0.0.0 --port="${PORT:-8000}"
    ;;
  *)
    echo "Unknown SERVICE_ROLE: $ROLE" >&2
    exit 1
    ;;
esac


