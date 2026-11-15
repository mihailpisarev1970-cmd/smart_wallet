# «Умный кошелёк»: бот MAX + админка Django в одном контейнере.
#
# В контейнере запускаются два процесса (через supervisord):
#   * bot.webhook_server — aiohttp :8080 (вебхуки MAX и ЮKassa)
#   * gunicorn           — Django admin :8000
#
# ffmpeg обязателен: MAX присылает голосовые в OGG/Opus, а AI Dostup
# принимает в /audio/transcriptions только WAV/PCM.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Europe/Moscow

# ffmpeg — конвертация голосовых; libpq — драйверы PostgreSQL;
# supervisor — запуск двух процессов; curl — healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libpq5 \
        curl \
        ca-certificates \
        supervisor \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Сначала зависимости — слой кэшируется, сборка быстрее
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Код приложения
COPY bot/ ./bot/
COPY admin_panel/ ./admin_panel/
COPY scripts/ ./scripts/ ./

# Российский корневой сертификат (Минцифры) — обязателен для MAX API.
# Python использует системный CA-бандл, поэтому ставим на уровень ОС.
COPY certs/ ./certs/
RUN cp certs/ru_trusted/russian_trusted_root_ca.pem \
        /usr/local/share/ca-certificates/russian_trusted_root_ca.crt \
    && cp certs/ru_trusted/russian_trusted_sub_ca.pem \
        /usr/local/share/ca-certificates/russian_trusted_sub_ca.crt \
    && update-ca-certificates

# Каталоги для логов, сертификатов и статики
RUN mkdir -p /app/logs /app/certs /app/admin_panel/staticfiles

# Конфигурация supervisor
COPY deploy/supervisord.conf /etc/supervisor/conf.d/wallet.conf

# Точка входа: миграции → collectstatic → оба процесса
COPY deploy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080 8000

ENTRYPOINT ["/entrypoint.sh"]
