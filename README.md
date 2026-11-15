# 💰 Умный кошелёк — чат-бот учёта личных финансов для мессенджера MAX

**Бот-финансовый помощник в MAX:** доходы и расходы кнопками, текстом и голосом,
баланс, история, статистика, месячные бюджеты с уведомлениями, цели накопления,
экспорт в CSV/Excel и AI-функции (разбор фраз, голосовой ввод, AI-помощник).

Записывайте траты за 5 секунд · Контролируйте бюджет · Копите на цели

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![MAX Bot API](https://img.shields.io/badge/MAX-Bot%20API-6C5CE7)](https://dev.max.ru/docs/)
[![Django](https://img.shields.io/badge/Django-6.1-092E20?logo=django&logoColor=white)](https://www.djangoproject.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%2F17-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/compose/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[Возможности](#-возможности) · [Демо-сценарий](#-как-это-работает) · [Архитектура](#-архитектура) · [Быстрый старт](#-быстрый-старт) · [Деплой](#-деплой-на-vps) · [FAQ](#-faq)

---

## 🔍 Ключевые слова

чат-бот для учёта финансов · учёт личных финансов в мессенджере · бот MAX ·
мессенджер MAX бот · финансовый помощник · семейный бюджет · дневник расходов ·
контроль расходов · учёт доходов и расходов · бюджет на месяц · лимиты по категориям ·
цели накопления · копилка · статистика расходов · экспорт в Excel и CSV ·
распознавание речи Whisper · gpt-4o-transcribe · LLM разбор текста · AI-помощник ·
Django admin · PostgreSQL · asyncpg · aiohttp · Python · Docker · VPS-деплой ·
ЮKassa · подписка на AI · personal finance bot · budget tracker bot · MAX messenger bot

---

## 📖 О проекте

**«Умный кошелёк»** — production-ready бот для **автоматизированного учёта личных
доходов и расходов** внутри мессенджера **MAX**. Пользователю не нужно ставить
отдельное приложение: он пишет боту «Потратил 1250 на продукты» или нажимает
кнопки — и операция уже в базе, с категорией, датой и валютой.

Ключевой принцип монетизации: **базовый учёт финансов бесплатен без ограничений**.
Платным является только AI-функционал (разбор естественного языка и AI-помощник),
потому что он создаёт реальные расходы на токены. Распознавание речи (STT) —
не отдельная платная функция, а ещё один способ ввода: оно использует те же
10 бесплатных AI-запросов.

### Кому подойдёт

---

## ✨ Возможности

| Блок | Что умеет |
|---|---|
| **Запись операций** | расходы и доходы кнопками (сумма → категория → подтверждение), свободным текстом, голосовым сообщением |
| **Категории** | 13 стандартных категорий расходов и 6 доходов, добавление/переименование/удаление своих; удаление не ломает историю |
| **Баланс** | доходы, расходы, текущий баланс и суммы за текущий месяц — считается программно (`Доходы − Расходы`) |
| **История** | за сегодня, вчера, неделю, месяц и произвольный период; редактирование и удаление с подтверждением |
| **Статистика** | расходы по категориям, самая затратная категория, динамика по месяцам, сравнение с предыдущим месяцем, средний расход в день |
| **Бюджеты** | общий лимит на месяц и лимиты по категориям, остаток, уведомления на порогах 50% / 80% / 100% (пороги настраиваются) |
| **Цели накопления** | название, целевая сумма, срок, прогресс и остаток до цели |
| **Настройки** | валюта, часовой пояс, категории, уведомления, удаление аккаунта и всех данных |
| **Экспорт** | выгрузка всех операций в **CSV** и **Excel** — бесплатно и без ограничений |
| **AI-разбор текста** | «Купил продукты на 1250 рублей» → тип, сумма, валюта, категория, дата, комментарий (LLM) |
| **Голосовой ввод** | голосовое сообщение → STT (`gpt-4o-transcribe`) → тот же разбор → подтверждение |
| **AI-помощник** | ответы на вопросы о ваших финансах с контекстом операций |
| **Админ-панель** | Django Admin для владельца: пользователи, операции, AI-логи и стоимость, подписки и выручка, FSM-состояния |
| **Подписка** | оплата AI-подписки внутри MAX через **ЮKassa**, идемпотентная активация на 30 дней |
| **Надёжность** | идемпотентность событий MAX, FSM в БД, rate limit по AI-запросам, структурные логи |

### Главное меню бота (10 кнопок)

`💸 Добавить расход` · `💰 Добавить доход` · `📊 Мой баланс` · `🕘 История` ·
`📈 Статистика` · `🎯 Мой бюджет` · `🏦 Цели накопления` · `🤖 AI-помощник` ·
`⚙️ Настройки` · `❓ Помощь`

### Команды

`/start` · `/menu` · `/balance` · `/expense` · `/income` · `/history` · `/stats` ·
`/budget` · `/goals` · `/settings` · `/help` (регистрируются через `PATCH /me/commands`)

---

## 🎬 Как это работает

```
Пользователь: Потратил 1250 на продукты
Бот:          Расход записан.
              Сумма: 1 250 ₽ · Категория: Продукты · Дата: сегодня
```

```
Пользователь: 🎤 [голосовое сообщение 4 сек]
Бот:          Распознано: «такси до дома 480 рублей»
              Расход записан: 480 ₽ · Транспорт
```

**Способы ввода:**

1. **Кнопки** — предсказуемый сценарий, не требует AI и работает всегда.
2. **Текст** — LLM извлекает сумму, категорию, дату и комментарий, бот показывает
   карточку подтверждения.
3. **Голос** — STT превращает речь в текст, дальше тот же путь, что и у текста.


* людям, которые хотят вести бюджет без сложных приложений и таблиц;
* тем, кто привык к мессенджерам и не хочет открывать ещё один сервис;
* разработчикам — как референс архитектуры production-бота для MAX на Python.

---

## 🏗 Архитектура

```
        ┌──────────────────────┐        ┌──────────────────────────┐
        │  Мессенджер MAX      │◄──────►│  Бот (Python, asyncio)   │
        │  users / chats       │        │  polling | webhook       │
        └──────────────────────┘        └───────────┬──────────────┘
                                                    │ asyncpg
   ┌───────────────┐   ┌──────────────┐   ┌─────────▼──────────────┐
   │ AI Dostup LLM │◄──┤  Сервисы AI  │   │      PostgreSQL        │
   │ STT (audio)   │   │ parser / STT │   │  19 таблиц (общая БД)  │
   └───────────────┘   └──────────────┘   └─────────▲──────────────┘
                                                    │ psycopg
   ┌───────────────┐   ┌──────────────┐   ┌─────────┴──────────────┐
   │    ЮKassa     │──►│  Webhook-    │   │  Django Admin (owner)  │
   │ payment.succeeded  сервер aiohttp │   │ дашборд, логи, подписки│
   └───────────────┘   └──────────────┘   └────────────────────────┘
```

**Архитектурное правило:** Django используется **только как админ-панель для
владельца**. Бот не импортирует Django-модели. Оба процесса подключаются к одной
PostgreSQL: Django — «хозяин схемы» (таблицы создаются через `migrate`), бот пишет
в них напрямую через `asyncpg`.

### Стек

| Слой | Технология |
|---|---|
| Язык | Python 3.11+ (`asyncio`) |
| Платформа | MAX Bot API ([документация](https://dev.max.ru/docs/)) |
| HTTP-клиент | `httpx` |
| Webhook-сервер | `aiohttp` (события MAX + вебхуки платежей) |
| БД бота | PostgreSQL + `asyncpg` (+ пул соединений) |
| БД админки | PostgreSQL + `psycopg[binary]` |
| Админ-панель | Django 6.1 (кастомный дашборд, фильтры, действия) |
| Конфигурация | `pydantic-settings` + `python-dotenv` |
| Планировщик | `APScheduler` (напоминания, обслуживание) |
| LLM | AI Dostup, OpenAI-совместимый API, `deepseek-v4.1-flash-1017` |
| STT | `gpt-4o-transcribe` (AI Dostup) |
| Экспорт | `openpyxl` (Excel), CSV — стандартная библиотека |
| Платежи | ЮKassa API v3 (`yoo_money`, `bank_card`, `sbp`, `sberbank`, …) |
| Инфраструктура | Docker, Docker Compose, nginx, Let's Encrypt |
| Качество | `pytest` + `pytest-asyncio`, `ruff` |

### Структура репозитория

```
.
├── bot/                      # бот: код, независимый от Django
│   ├── api.py                # клиент MAX Bot API
│   ├── webhook_server.py     # aiohttp: события MAX + вебхуки платежей + healthz
│   ├── polling.py            # long polling (локальная разработка)
│   ├── dispatcher.py         # разбор обновлений, идемпотентность
│   ├── router.py             # реестр обработчиков и fallback
│   ├── commands.py           # команды и их регистрация в MAX
│   ├── states.py             # FSM-состояния диалогов
│   ├── config.py             # настройки из .env (pydantic-settings)
│   ├── db/                   # слой доступа к PostgreSQL (asyncpg)
│   ├── handlers/             # сценарии: start, transactions, history, analytics,
│   │                         # бюджеты, goals, settings, export, ai, voice, …
│   ├── services/             # бизнес-логика: баланс, статистика, бюджеты,
│   │                         # цели, AI-парсер, STT, лимиты, платежи, экспорт
│   └── utils/                # деньги, даты, клавиатуры, форматирование
├── admin_panel/              # Django: только админ-панель владельца
│   ├── settings.py           # конфигурация Django
│   ├── urls.py               # /admin/, дашборд
│   └── wallet/               # модели, admin.py, dashboard, миграции
├── scripts/                  # утилиты: проверки, демо-данные, деплой
├── tests/                    # офлайн-тесты (без сети и БД)
├── deploy/                   # Dockerfile, docker-compose, nginx, entrypoint
├── pyproject.toml            # ruff + pytest
├── requirements.txt
├── DEPLOY.md                 # пошаговый деплой на VPS
├── SECURITY.md               # работа с секретами
└── .env.example              # шаблон конфигурации
```


---

## 🚀 Быстрый старт

### 1. Требования

* Python **3.11+**
* PostgreSQL **16/17** (локально удобно через Docker)
* токен бота MAX (создаётся в кабинете чат-ботов)

### 2. Установка

```powershell
git clone https://github.com/mihailpisarev1970-cmd/smart_wallet.git
cd smart_wallet

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Конфигурация

```powershell
Copy-Item .env.example .env
# заполните MAX_BOT_TOKEN, DATABASE_URL, DJANGO_SECRET_KEY
# для AI-функций — AI_DOSTUP_API_KEY, для оплаты — YOOKASSA_*
```

Полный список переменных — в [.env.example](.env.example) и разделе
[Конфигурация](#-конфигурация).

### 4. База данных

```powershell
# вариант через Docker
docker run --name wallet-pg -p 5432:5432 -e POSTGRES_PASSWORD=postgres -d postgres:16
# затем создайте роль и БД smart_wallet, как в DEPLOY.md

# схема создаётся Django-миграциями
python admin_panel/manage.py migrate
```

### 5. Запуск

```powershell
python -m bot.main --check        # проверка окружения: БД, MAX API, ключи
powershell -File scripts\run_bot.ps1        # бот (long polling), фоном
powershell -File scripts\status_bot.ps1     # статус и хвост лога
powershell -File scripts\stop_bot.ps1       # остановка

python -m scripts.create_admin              # один раз: администратор админки
powershell -File scripts\run_admin.ps1      # админка → http://127.0.0.1:8000/admin/
```

> Бот работает в режиме **long polling** — домен и HTTPS локально не нужны.
> Для production используется **webhook** (см. [Деплой](#-деплой-на-vps)).

---

## ⚙️ Конфигурация

Все значения — только через переменные окружения. Файл `.env` в `.gitignore`
и **никогда** не коммитится ([SECURITY.md](SECURITY.md)).

| Переменная | Назначение |
|---|---|
| `APP_ENV` | `local` или `production` |
| `MAX_BOT_TOKEN` | токен бота MAX (Чат-боты → ⋮ → Настройки) |
| `MAX_API_BASE_URL` | `https://platform-api2.max.ru` |
| `MAX_UPDATES_MODE` | `polling` (локально) или `webhook` (сервер) |
| `WEBHOOK_BASE_URL`, `MAX_WEBHOOK_SECRET` | публичный адрес и секрет вебхука |
| `DATABASE_URL` | `postgresql://user:pass@host:5432/smart_wallet` |
| `DB_POOL_MIN_SIZE` / `DB_POOL_MAX_SIZE` | размер пула `asyncpg` |
| `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS` | настройки админки |
| `OWNER_MAX_USER_ID` | `user_id` владельца в MAX |
| `AI_DOSTUP_BASE_URL`, `AI_DOSTUP_API_KEY`, `AI_DOSTUP_MODEL` | LLM для разбора и AI-помощника |
| `STT_API_BASE_URL`, `STT_API_KEY`, `STT_PRIMARY_MODEL` | распознавание речи |
| `AI_FREE_REQUESTS` | бесплатных AI-запросов на пользователя (по умолчанию 10) |
| `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY`, `YOOKASSA_RETURN_URL` | приём оплаты |
| `AI_SUBSCRIPTION_PRICE_RUB` / `AI_SUBSCRIPTION_DAYS` | цена и срок AI-подписки |

---

## 🖥 Админ-панель (Django)

Панель **владельца**: бот и админка — независимые процессы и друг другу не мешают.

| Раздел | Что внутри |
|---|---|
| **Дашборд** | пользователи (всего/новые/активные/с подпиской), операции (доходы, расходы, баланс), AI-запросы (STT/LLM, ошибки, fallback, стоимость), подписки и выручка |
| **Пользователи** | поиск по `max_user_id`, фильтры, активация подписки на 30/90 дней, отключение, сброс счётчика AI |
| **Операции** | фильтры по типу, источнику (button/text/voice), категории, дате, пользователю |
| **AI-логи** | модель, длительность аудио, токены, стоимость, задержка, статус, fallback |
| **Подписки** | статус, срок, сумма, идентификатор платежа, история |
| **Категории / Бюджеты / Цели** | просмотр и редактирование |
| **Служебные** | состояния диалогов (FSM), обработанные события |

Проверка всех страниц без браузера:

```powershell
python -m scripts.check_admin      # 12/12 разделов
```


---

## 🌐 Деплой на VPS

Полная пошаговая инструкция — **[DEPLOY.md](DEPLOY.md)**: PostgreSQL, Python,
systemd/контейнеры, nginx + Let's Encrypt, регистрация вебхука, бэкапы.

Кратко:

1. `.env` на сервере: `APP_ENV=production`, `MAX_UPDATES_MODE=webhook`,
   `WEBHOOK_BASE_URL=https://<домен>`, `MAX_WEBHOOK_SECRET=<секрет>`,
   `WEBHOOK_HOST=127.0.0.1`;
2. единый сервер `python -m bot.webhook_server` принимает события MAX
   (`/webhook/max/<secret>`) и уведомления ЮKassa (`/yookassa/webhook`);
3. nginx проксирует `/webhook/`, `/yookassa/`, `/admin/`, `/static/`;
4. `python admin_panel/manage.py migrate && collectstatic`;
5. сервисы: бот (webhook-сервер) + админка;
6. бэкапы PostgreSQL по cron.

### Почему webhook обязателен в production

MAX в long polling присылает **голосовые сообщения без тела** — только
`timestamp`, без `message`, `chat_id` и `user_id`. `GET /messages` голосовые не
возвращает, поэтому восстановить их невозможно. В webhook событие приходит целиком.

```powershell
python -m scripts.manage_webhook show            # список подписок
python -m scripts.manage_webhook register        # подписаться (url из .env)
python -m scripts.manage_webhook remove          # отписаться
python -m scripts.manage_webhook back-to-polling # вернуть long polling
```

Проверка здоровья: `curl http://127.0.0.1:8080/healthz` → `{"status":"ok"}`

---

## 🧪 Тесты и проверки

```powershell
python -m pytest tests -q            # офлайн-тесты (без сети и БД)
python -m ruff check bot scripts     # линтер
python -m bot.main --check           # окружение: БД, API, ключи
```

Дополнительные диагностические скрипты:

| Скрипт | Что проверяет |
|---|---|
| `python -m scripts.check_db` | таблицы и типы данных |
| `python -m scripts.check_llm_cases` | 10 типичных фраз через LLM |
| `python -m scripts.check_stt` | распознавание речи |
| `python -m scripts.check_voice_flow` | голос → STT → LLM → подтверждение |
| `python -m scripts.check_ai_flow` | текст → LLM → запись |
| `python -m scripts.check_assistant` | AI-помощник с контекстом финансов |
| `python -m scripts.check_services` | расчёты баланса/статистики на данных |
| `python -m scripts.seed_demo` | демо-данные для нового пользователя |

---

## 🔐 Безопасность

* все ключи — только в переменных окружения, `.env` и приватные SSH-ключи в `.gitignore`;
* в репозитории нет реальных токенов, паролей и адресов сервера — см. [SECURITY.md](SECURITY.md);
* в production: `DJANGO_DEBUG=False`, случайный `DJANGO_SECRET_KEY`,
  `WEBHOOK_HOST=127.0.0.1`, HTTPS через nginx;
* данные пользователей изолированы: каждая операция проверяется на принадлежность
  текущему `max_user_id`;
* платёжные вебхуки обрабатываются идемпотентно — повтор не продлевает подписку.

Нашли уязвимость — напишите приватно: <https://t.me/pisarev_pro_digital>.

---

## ❓ FAQ

<details>
<summary><b>Нужен ли домен и HTTPS для локального запуска?</b></summary>

Нет. Бот работает через long polling: достаточно токена и запущенной PostgreSQL.
Домен нужен только для production-webhook (и для голосовых сообщений).
</details>

<details>
<summary><b>Почему голосовые работают только через webhook?</b></summary>

MAX в long polling не передаёт тело голосового сообщения — приходит только
`timestamp`, а `GET /messages` такие сообщения не возвращает. В webhook событие
приходит полностью.
</details>

<details>
<summary><b>Обязателен ли AI?</b></summary>

Нет. Весь учёт финансов работает бесплатно и без ключей AI: кнопки, категории,
баланс, история, статистика, бюджеты, цели, экспорт. AI-ключ нужен только для
разбора свободного текста, голоса и AI-помощника.
</details>

<details>
<summary><b>Какая модель распознавания речи используется?</b></summary>

`gpt-4o-transcribe` — единственная доступная у провайдера AI Dostup.
`whisper-1` провайдер удалил (HTTP 400), поэтому выбор модели в настройках бота убран.
</details>

<details>
<summary><b>Можно ли использовать Robokassa вместо ЮKassa?</b></summary>

В актуальной версии используется **ЮKassa** с оплатой внутри MAX. Устаревшие
скрипты диагностики в репозитории оставлены только как справочные и не содержат ключей.
</details>

<details>
<summary><b>Как удалить свои данные?</b></summary>

В боте: `⚙️ Настройки` → «Удалить аккаунт и все данные». Удаление каскадное —
операции, категории, бюджеты и цели пользователя.
</details>

<details>
<summary><b>Как добавить новую категорию?</b></summary>

`⚙️ Настройки` → «Категории» → «Добавить». Удаление категории не удаляет уже
записанные операции — они сохраняют историческую ссылку.
</details>

---

## 🤝 Contributing

```bash
git checkout -b feature/новая-фича
python -m pytest tests -q && python -m ruff check bot scripts
git commit -m "feat: добавил экспорт бюджетов в Excel"
git push origin feature/новая-фича
```

Стиль коммитов: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`.

---

## 📚 Полезные ссылки

| Что | Ссылка |
|---|---|
| MAX Bot API — документация | <https://dev.max.ru/docs/> |
| MAX — платформа для разработчиков | <https://dev.max.ru/> |
| Django — документация | <https://docs.djangoproject.com/> |
| PostgreSQL — документация | <https://www.postgresql.org/docs/> |
| asyncpg | <https://magicstack.github.io/asyncpg/current/> |
| aiohttp | <https://docs.aiohttp.org/> |
| httpx | <https://www.python-httpx.org/> |
| ЮKassa API v3 | <https://yookassa.ru/developers/api> |
| pydantic-settings | <https://docs.pydantic.dev/latest/concepts/pydantic_settings/> |

---

## 📄 Лицензия

[MIT License](LICENSE) © 2026 Михаил Писарев (SmartAgent)

---

## ⭐ Поддержите проект

Если проект полезен — поставьте звезду, создайте issue с идеей или пришлите pull request.

Сделано для тех, кто хочет знать, куда уходят деньги 💸

[⬆ Наверх](#-умный-кошелёк--чат-бот-учёта-личных-финансов-для-мессенджера-max)

