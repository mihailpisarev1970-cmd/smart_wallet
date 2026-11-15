# Деплой «Умный кошелёк» на сервер (production)

Инструкция рассчитана на чистый **Ubuntu 22.04 / 24.04** с root-доступом.

## Почему webhook, а не long polling

| | Long polling | **Webhook** |
|---|---|---|
| Тело голосового | ❌ приходит пустым | ✅ полное, с `chat_id` и `user_id` |
| Нагрузка | постоянные запросы 24/7 | только на события |
| Повторная доставка | ⚠️ теряется при падении | ✅ MAX повторяет |
| Robokassa Result URL | нужен отдельный сервер | ✅ тот же процесс |

## Архитектура

```
                    ┌──────────────────────────────────┐
   MAX  ──POST──▶   │  nginx :443 (HTTPS, Let's Encrypt)│
   Robokassa ──▶    │    ├── /webhook/max/<secret>     │
                    │    ├── /robokassa/*              │
                    │    └── /admin/*  (Django)        │
                    └───────────────┬──────────────────┘
                                    ▼
                    ┌──────────────────────────────────┐
                    │  bot.webhook_server (aiohttp)    │
                    │    + Dispatcher, :8080 (local)   │
                    └───────────────┬──────────────────┘
                                    ▼
                              PostgreSQL
```

## 1. Подготовка сервера

```bash
apt update && apt upgrade -y
apt install -y python3.12 python3.12-venv python3-pip \
               postgresql postgresql-contrib nginx \
               certbot python3-certbot-nginx git unzip \
               ffmpeg

useradd -m -s /bin/bash wallet
```

> **`ffmpeg` обязателен.** MAX присылает голосовые в OGG/Opus, а AI Dostup
> принимает в `/audio/transcriptions` **только WAV/PCM** (проверено:
> OGG, MP3, M4A, FLAC, WebM → HTTP 400). Без ffmpeg голосовой ввод не работает.
> Проверка после установки: `ffmpeg -version`.

## 2. База данных

```bash
sudo -u postgres psql <<'SQL'
CREATE USER wallet WITH PASSWORD 'ЗАМЕНИТЕ_НА_СИЛЬНЫЙ_ПАРОЛЬ';
CREATE DATABASE smart_wallet OWNER wallet ENCODING 'UTF8';
GRANT ALL PRIVILEGES ON DATABASE smart_wallet TO wallet;
SQL
```

## 3. Код и зависимости

```bash
sudo -u wallet -H bash
mkdir -p /home/wallet/app && cd /home/wallet/app
# скопируйте проект (git clone или scp/rsync)
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

## 4. Сертификат Минцифры (обязательно для MAX API)

Положите корневой сертификат в `certs/ru_trusted/` — код соберёт CA-бандл
автоматически (`bot/utils/tls.py`).

Скачать: <https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt>

## 5. `.env` для production

```dotenv
APP_ENV=production
LOG_LEVEL=INFO

MAX_BOT_TOKEN=<токен бота>
MAX_UPDATES_MODE=webhook
WEBHOOK_BASE_URL=https://ваш-домен.ru
WEBHOOK_HOST=127.0.0.1
WEBHOOK_PORT=8080
MAX_WEBHOOK_SECRET=<случайная строка 32+ символа>

DATABASE_URL=postgresql://wallet:ПАРОЛЬ@localhost:5432/smart_wallet

DJANGO_SECRET_KEY=<случайная строка 50 символов>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=ваш-домен.ru,www.ваш-домен.ru
OWNER_MAX_USER_ID=<ваш user_id в MAX>

AI_DOSTUP_API_KEY=<ключ>
STT_API_KEY=<ключ AI Dostup>

ROBOKASSA_MERCHANT_LOGIN=gptagent
ROBOKASSA_PASSWORD_1=<пароль 1>
ROBOKASSA_PASSWORD_2=<пароль 2>
ROBOKASSA_IS_TEST=0
ROBOKASSA_RESULT_URL=https://ваш-домен.ru/robokassa/result
ROBOKASSA_SUCCESS_URL=https://ваш-домен.ru/robokassa/success
ROBOKASSA_FAIL_URL=https://ваш-домен.ru/robokassa/fail
AI_SUBSCRIPTION_PRICE_RUB=210
```

Сгенерировать секреты:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # MAX_WEBHOOK_SECRET
python3 -c "import secrets; print(secrets.token_urlsafe(50))"   # DJANGO_SECRET_KEY
chmod 600 .env    # содержит пароли
```

## 6. Миграции и админ

```bash
cd /home/wallet/app/admin_panel
../.venv/bin/python manage.py migrate
../.venv/bin/python manage.py collectstatic --noinput
```

## 7. systemd: сервис webhook-сервера

`/etc/systemd/system/smart-wallet.service`:

```ini
[Unit]
Description=Smart Wallet bot (MAX webhook + Robokassa)
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=wallet
Group=wallet
WorkingDirectory=/home/wallet/app
Environment="PYTHONUTF8=1"
Environment="PYTHONPATH=/home/wallet/app"
ExecStart=/home/wallet/app/.venv/bin/python -m bot.webhook_server
Restart=always
RestartSec=5
StandardOutput=append:/home/wallet/app/logs/service.log
StandardError=append:/home/wallet/app/logs/service.log

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=read-only
ReadWritePaths=/home/wallet/app/logs /home/wallet/app/certs

[Install]
WantedBy=multi-user.target
```

## 8. systemd: Django-админка (gunicorn)

`/etc/systemd/system/smart-wallet-admin.service`:

```ini
[Unit]
Description=Smart Wallet admin panel (Django)
After=network.target postgresql.service

[Service]
Type=simple
User=wallet
Group=wallet
WorkingDirectory=/home/wallet/app/admin_panel
Environment="PYTHONUTF8=1"
Environment="PYTHONPATH=/home/wallet/app"
ExecStart=/home/wallet/app/.venv/bin/gunicorn admin_panel.wsgi:application \
          --bind 127.0.0.1:8000 --workers 2 --timeout 60
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Активация:

```bash
systemctl daemon-reload
systemctl enable --now smart-wallet smart-wallet-admin
systemctl status smart-wallet
```

## 9. nginx

`/etc/nginx/sites-available/smart-wallet`:

```nginx
server {
    listen 80;
    server_name ваш-домен.ru www.ваш-домен.ru;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name ваш-домен.ru www.ваш-домен.ru;

    ssl_certificate     /etc/letsencrypt/live/ваш-домен.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/ваш-домен.ru/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    client_max_body_size 25M;

    location /webhook/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }

    location /robokassa/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location = /healthz {
        proxy_pass http://127.0.0.1:8080;
        access_log off;
    }

    location /admin/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static/ {
        alias /home/wallet/app/admin_panel/staticfiles/;
        expires 30d;
    }
}
```

```bash
ln -s /etc/nginx/sites-available/smart-wallet /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

certbot --nginx -d ваш-домен.ru -d www.ваш-домен.ru
certbot renew --dry-run
```

## 10. Регистрация webhook в MAX

```bash
cd /home/wallet/app
sudo -u wallet .venv/bin/python -m scripts.manage_webhook register
sudo -u wallet .venv/bin/python -m scripts.manage_webhook show
```

Проверка, что эндпоинт живой:

```bash
curl -s https://ваш-домен.ru/healthz
# {"status":"ok","mode":"webhook","db":true,"tasks":0}
```

## 11. Robokassa

В личном кабинете Robokassa → **Настройки магазина**:

| Поле | Значение |
|---|---|
| Result URL | `https://ваш-домен.ru/robokassa/result` |
| Success URL | `https://ваш-домен.ru/robokassa/success` |
| Fail URL | `https://ваш-домен.ru/robokassa/fail` |
| Метод | POST |

Проверка приёма платежей:

```bash
curl -s https://ваш-домен.ru/healthz          # 200
# Тестовый Result с неверной подписью → 400 (это норма, защита работает):
curl -s -X POST https://ваш-домен.ru/robokassa/result \
     -d "OutSum=210.00&InvId=1&SignatureValue=test"
```

## 12. Бэкапы PostgreSQL

`/home/wallet/backup.sh`:

```bash
#!/bin/bash
set -euo pipefail
BACKUP_DIR=/home/wallet/backups
mkdir -p "$BACKUP_DIR"
STAMP=$(date +%F_%H%M)
PGPASSWORD=ПАРОЛЬ pg_dump -U wallet -h localhost smart_wallet \
  | gzip > "$BACKUP_DIR/smart_wallet_$STAMP.sql.gz"
find "$BACKUP_DIR" -name "*.sql.gz" -mtime +14 -delete
```

```bash
chmod +x /home/wallet/backup.sh
echo "30 3 * * * /home/wallet/backup.sh" | crontab -u wallet -
```

Восстановление:

```bash
gunzip -c smart_wallet_2026-11-08_0330.sql.gz | \
  PGPASSWORD=ПАРОЛЬ psql -U wallet -h localhost smart_wallet
```

## 13. Чек-лист после деплоя

- [ ] `systemctl status smart-wallet` — active (running)
- [ ] `curl https://ваш-домен.ru/healthz` — `{"status":"ok",...}`
- [ ] `python -m scripts.manage_webhook show` — подписка есть
- [ ] Текст «Потратил 350 на кофе» → бот ответил
- [ ] **Голосовое** «Потратил 350 на кофе» → бот распознал
      (в логе: `Вебхук MAX: type=message_created, has_message=True`)
- [ ] `/admin/` открывается, вход работает
- [ ] Тестовая оплата Robokassa 210 ₽ → подписка активировалась
- [ ] `tail -f logs/bot.log` — нет ERROR

## 14. Обслуживание

```bash
# Логи
journalctl -u smart-wallet -f
tail -f /home/wallet/app/logs/bot.log

# Обновление
cd /home/wallet/app
sudo -u wallet git pull
sudo -u wallet .venv/bin/pip install -r requirements.txt
cd admin_panel && sudo -u wallet ../.venv/bin/python manage.py migrate
systemctl restart smart-wallet smart-wallet-admin

# Вернуться к long polling (если webhook недоступен)
.venv/bin/python -m scripts.manage_webhook remove
# затем MAX_UPDATES_MODE=polling и systemctl restart smart-wallet
```

## Локальный запуск (разработка)

```powershell
powershell -File scripts\run_bot.ps1       # бот в режиме polling
powershell -File scripts\run_webhook.ps1   # webhook-сервер локально
```

Для проверки webhook локально нужен публичный HTTPS-туннель
(ngrok, cloudpub) — MAX принимает только его.


