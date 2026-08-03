FROM python:3.12-slim

# Instalar dependencias del sistema necesarias para ctypes, multiprocessing y psycopg2
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       gcc \
       libpq-dev \
       python3-dev \
       libc6 \
       libffi-dev \
       curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt

COPY . .
RUN mkdir -p services/mailing-service/app/static/welcome

# Entrypoint unificado para web/worker/beat controlado por SERVICE_ROLE
RUN sed -i 's/\r$//' ./entrypoint.sh \
    && chmod +x ./entrypoint.sh
ENTRYPOINT ["/bin/bash", "./entrypoint.sh"]


