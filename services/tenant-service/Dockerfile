# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /build
COPY shared/ ./shared/
COPY services/tenant-service/ ./services/tenant-service/
WORKDIR /build/services/tenant-service
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN groupadd -r app && useradd -r -g app app
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY services/tenant-service/app /app/app
COPY services/tenant-service/alembic.ini /app/alembic.ini
COPY services/tenant-service/migrations /app/migrations
USER app
EXPOSE 8002
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8002/health')" || exit 1
CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
