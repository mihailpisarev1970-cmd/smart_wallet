#!/usr/bin/env bash
# Точка входа контейнера wallet.
#
# 1. Миграции Django — создают/обновляют схему PostgreSQL (19 таблиц).
# 2. collectstatic — статика админки.
# 3. supervisor — запускает бота (aiohttp) и админку (gunicorn).
set -euo pipefail

echo "[entrypoint] Ожидание PostgreSQL..."
for attempt in $(seq 1 30); do
  if python -c "
import os, socket, sys
url = os.environ.get('DATABASE_URL', '')
host = url.split('@')[-1].split(':')[0] if '@' in url else 'wallet_PostgreSQL'
try:
    socket.create_connection((host, 5432), timeout=2).close()
    sys.exit(0)
except OSError:
    sys.exit(1)
" 2>/dev/null; then
    echo "[entrypoint] PostgreSQL доступен"
    break
  fi
  echo "[entrypoint] попытка $attempt/30..."
  sleep 2
done

echo "[entrypoint] Миграции Django..."
cd /app/admin_panel
python manage.py migrate --noinput

echo "[entrypoint] Сбор статики..."
# STATIC_ROOT = BASE_DIR/staticfiles, а BASE_DIR = /app → /app/staticfiles
python manage.py collectstatic --noinput 2>&1 | tail -3

echo "[entrypoint] Публикация статики для nginx..."
# nginx читает /opt/wallet/static (том ./static → /app/static)
mkdir -p /app/static
cp -r /app/staticfiles/. /app/static/ 2>/dev/null || true
echo "[entrypoint] файлов статики: $(find /app/static -type f | wc -l)"

cd /app
echo "[entrypoint] Запуск процессов..."
exec supervisord -c /etc/supervisor/supervisord.conf
