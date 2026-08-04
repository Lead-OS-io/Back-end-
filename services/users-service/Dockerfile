# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /build
COPY shared/ ./shared/
COPY services/users-service/ ./services/users-service/
WORKDIR /build/services/users-service
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN groupadd -r app && useradd -r -g app app
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY services/users-service/app /app/app
COPY services/users-service/alembic.ini /app/alembic.ini
COPY services/users-service/migrations /app/migrations
USER app
EXPOSE 8003
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8003/health')" || exit 1
# Migraciones automáticas al arrancar (idempotente; fail-fast si fallan)
CMD ["sh", "-c", "/app/.venv/bin/alembic upgrade head && exec /app/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8003"]
