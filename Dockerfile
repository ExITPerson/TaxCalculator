# syntax=docker/dockerfile:1.6

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Europe/Moscow

WORKDIR /app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# --- Зависимости ---
FROM base AS deps

COPY requirements.txt .
# Важно: psycopg[binary] должен быть в requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

# --- Финальный образ ---
FROM base AS runtime

# Копируем установленные пакеты из deps
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Копируем сертификат (если он нужен для T-Invest)
COPY config/cert.cer /config/cert.cer

# Копируем весь проект
COPY . .

# Создаем папки для данных и логов, а также папку /data для Amvera
RUN mkdir -p /app/data /app/logs /data

# Создаем пользователя и даем ему права на запись во все нужные папки
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app /data /config

USER appuser

# Запускаем через main.py (как у вас в логах)
CMD ["python", "main.py"]