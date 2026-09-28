# Telegram-бот учёта долгов и кассы

Бот ведёт учёт денежных долгов между владельцем и клиентами и кассу владельца в пяти валютах
(KGS, USD, EUR, RUB, KZT): четыре вида записей, возврат в другой валюте по курсу, отмена ошибочных
записей, помощники и пять отчётов в Excel и PDF.

- Полная спецификация: [TZ.md](TZ.md).
- Описание для заказчика с примерами экранов: [docs/client_description.pdf](docs/client_description.pdf).
- Решения по местам, которые ТЗ не описывает: [docs/decisions.md](docs/decisions.md).

Для работы нужен сервер (или компьютер) с Docker и Docker Compose v2. Всё остальное запускается
в контейнерах: бот, PostgreSQL 16 и Redis 7.

## Ветки

- `master` — версия для сервера, откуда Telegram доступен напрямую (например, VPS за пределами
  России). Именно её разворачивают на сервере.
- `ru_version` — то же самое плюс клиент прокси Hysteria2 в `docker-compose.yml`: бот ходит
  в Telegram через прокси. Для запуска внутри России.

Изменения делаются в `master` и затем переносятся в `ru_version`:

```bash
git checkout ru_version && git merge master && git checkout master
```

## 1. Создайте бота у @BotFather

1. Откройте в Телеграме [@BotFather](https://t.me/BotFather) и отправьте `/newbot`.
2. Напишите название бота, например «Учёт долгов».
3. Напишите имя пользователя бота. Оно должно заканчиваться на `bot`, например `my_debts_bot`.
4. BotFather пришлёт токен вида `123456789:AAH...`. Это `BOT_TOKEN`. Никому его не показывайте:
   с токеном можно управлять ботом.
5. Рекомендуется запретить добавлять бота в группы: `/setjoingroups` → выберите бота →
   `Disable`. Бот и так работает только в личных сообщениях.

## 2. Узнайте свой Telegram ID

Это число, по которому бот узнаёт владельца. Проще всего:

- напишите боту [@userinfobot](https://t.me/userinfobot) любое сообщение, он ответит вашим `Id`;
- или откройте в браузере `https://api.telegram.org/bot<ТОКЕН>/getUpdates` после того,
  как напишете своему боту, и найдите `"from":{"id": ...}`.

## 3. Заполните `.env`

```bash
cp .env.example .env
```

Откройте `.env` и укажите:

| Переменная | Что указать |
|---|---|
| `BOT_TOKEN` | токен от @BotFather |
| `OWNER_TELEGRAM_ID` | ваш Telegram ID (число) |
| `DATABASE_URL` | оставьте как есть для запуска через Docker |
| `REDIS_URL` | оставьте как есть; если пусто, состояния диалогов живут только в памяти и теряются при перезапуске |
| `TZ` | часовой пояс для дат и времени записей, отчётов и логов: `Europe/Moscow` (московское время) |
| `LOG_LEVEL` | `INFO` (или `DEBUG` для подробных логов) |
| `PROXY_URL` | обычно пусто; нужен, только если Telegram заблокирован (раздел 8) |

Владелец в боте всегда один: тот, чей ID указан в `OWNER_TELEGRAM_ID`. Если заменить ID на другой
аккаунт, прежний владелец потеряет доступ, а его записи останутся с пометкой «(удалён)».

## 4. Запуск

```bash
docker compose up -d --build
```

При старте контейнер бота сам применяет миграции базы данных, затем запускает бота.
Проверить, что всё работает:

```bash
docker compose ps
docker compose logs -f bot
```

В логах должно появиться `Bot started`. Откройте бота в Телеграме и нажмите «Старт»: появится
главное меню, а под полем ввода — панель с разделами (Выдал в долг, Мне вернули, Взял в долг,
Я вернул, Клиенты, Касса, Отчёты и у владельца Настройки). Панель видна всегда; если она пропала,
отправьте `/start`. Первым делом внесите в кассу деньги, которые есть сейчас: «Касса» →
«Корректировка» → валюта → «Добавить» → сумма → причина «Остаток на начало работы».

Помощники добавляются в «Настройки» → «Помощники» → «Добавить» по никнейму в Телеграме.
Помощник должен открыть бота и нажать «Старт»; у него обязательно должен быть никнейм.

## 5. Обновление

Получите новую версию кода (например, `git pull`) и пересоберите контейнер:

```bash
docker compose up -d --build
```

Миграции базы применяются автоматически при старте. Данные сохраняются.

## 6. Остановка

```bash
docker compose stop        # остановить, всё сохраняется
docker compose start       # запустить снова
docker compose down        # удалить контейнеры; данные в томах сохраняются
```

**Не используйте `docker compose down -v`**: флаг `-v` удаляет тома, то есть всю базу данных.

## 7. Резервная копия базы

Все записи, клиенты и касса хранятся в PostgreSQL. Redis хранит только незавершённые диалоги,
его копировать не нужно.

Сделать копию (файл появится в текущей папке):

```bash
docker compose exec -T db pg_dump -U debtbot -d debtbot -Fc > backup_$(date +%F).dump
```

Копию стоит делать регулярно и хранить на другом компьютере или в облаке. Пример ежедневной
копии в 03:00 через `crontab -e` (замените путь на папку проекта):

```cron
0 3 * * * cd /opt/debt_tracking_bot && docker compose exec -T db pg_dump -U debtbot -d debtbot -Fc > backups/backup_$(date +\%F).dump
```

Восстановить из копии (все текущие данные заменятся данными из файла):

```bash
docker compose stop bot
docker compose exec -T db pg_restore -U debtbot -d debtbot --clean --if-exists < backup_2026-09-27.dump
docker compose start bot
```

## 8. Если Telegram недоступен

Если в логах бота повторяется `Telegram is unreachable` или `Request timeout error`, провайдер
блокирует `api.telegram.org`. Проверка с сервера:

```bash
curl -m 8 -o /dev/null -w "HTTP %{http_code}\n" https://api.telegram.org
```

Тогда укажите в `.env` прокси, через который Telegram доступен (HTTP или SOCKS5):

```
PROXY_URL=socks5://user:password@proxy-host:1080
```

и перезапустите: `docker compose up -d --build`.

Если прокси — сервер Hysteria2, используйте ветку `ru_version`: в ней клиент Hysteria2 уже
подключён в `docker-compose.yml`, настройка описана в её README.

## 9. Для разработчика

Python 3.12. Установка и проверки:

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ruff check . && ruff format --check .
```

Тесты работают с настоящим PostgreSQL. Отдельная одноразовая база для тестов (её данные живут
в памяти контейнера):

```bash
docker compose -f docker-compose.test.yml up -d
export TEST_DATABASE_URL=postgresql+asyncpg://debtbot:debtbot@localhost:55432/debtbot_test
pytest
```

Тесты пересоздают схему через миграции Alembic и запускаются только на базе, в имени которой
есть `test`. Кроме домена и сервисов, тесты проходят через настоящий диспетчер aiogram с
поддельным Telegram (`tests/bot/harness.py`): он проверяет HTML, длину callback-данных и
сообщений так же строго, как Telegram.

Новая миграция: `alembic revision --autogenerate -m "..."`. Проверьте файл вручную: триггеры,
CHECK-ограничения и условия частичных индексов autogenerate не видит. Тест
`tests/test_schema.py::test_models_match_migration` следит, чтобы модели совпадали со схемой.

Зависимости для Docker закреплены в `requirements.lock`. После изменения `pyproject.toml`:

```bash
uv pip compile pyproject.toml --universal --python-version 3.12 --no-header -o requirements.lock
```

### Структура

```
app/
  __main__.py        точка входа: python -m app
  config.py          настройки из .env
  domain/            чистые правила: валюты, суммы, курсы, записи, даты, ошибки
  services/          работа с базой: пользователи, клиенты, записи, касса, отчёты
  bot/               Telegram: тексты, клавиатуры, сценарии, обработчики, middleware
  db/                модели SQLAlchemy
migrations/          Alembic
tests/               тесты (pytest)
```
