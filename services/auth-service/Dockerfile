# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /build
COPY shared/ ./shared/
COPY services/auth-service/ ./services/auth-service/
WORKDIR /build/services/auth-service
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN groupadd -r app && useradd -r -g app app
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY services/auth-service/app /app/app
COPY services/auth-service/alembic.ini /app/alembic.ini
COPY services/auth-service/migrations /app/migrations
USER app
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8001/health')" || exit 1
CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
