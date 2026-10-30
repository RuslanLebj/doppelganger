# doppelganger

Сервис ежедневных резервных копий PostgreSQL с сохранением дампов в
S3-совместимое хранилище. В Docker Compose входит MinIO.

## Структура

Основные каталоги:

- `bootstrap` — запуск API и scheduler;
- `admin` — собственная админка, шаблоны, локальные CSS/JS и вход по паролю;
- `api/entrypoints/rest` — основной router, healthcheck, `v1/routes` и `v1/deps`;
- `api/security` — проверка `X-API-Key`;
- `api/entrypoints/scheduler/v1/main.py` — запуск исполнителя;
- `app/application` — схемы, сервис управления, расписания и выполнение бэкапов;
- `app/infrastructure/db/models` — отдельный файл для каждой модели;
- `app/infrastructure/backup` — `pg_dump` и управление его процессом;
- `app/infrastructure/s3/minio/adapter.py` — прямые вызовы boto3 и настройка lifecycle;
- `db/postgresql` — engine, session и миграции; `alembic.ini` лежит в `src`;
- `tests/app/unit`, `tests/app/integration`, `tests/app/e2e` — проверки.

Таблицы называются `database_target`, `backup_plan`, `backup_run`.
Статусы запуска: `queued`, `running`, `success`, `failed`, `interrupted`.
Сохранение в S3 отражается в `s3_status`.

## Настройки и запуск

Настройки читаются из корневого `.env` и переменных окружения. Секреты задаются
вручную: `CRYPT_KEY`, `API_KEY`, `POSTGRES_DB_PASSWORD`,
`S3_ACCESS_KEY`, `S3_SECRET_KEY`. Приложение не создаёт и не переписывает `.env`.

```sh
cp docker/app/template.env .env
make install
mkdir -p data/app data/minio secrets
chmod 600 .env
```

Заполните `.env`. Для нового ключа шифрования можно один раз выполнить:

```sh
uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Сохраните результат в `CRYPT_KEY`. Не заменяйте ключ после добавления баз:
он нужен для расшифровки уже сохранённых паролей. Сам `.env` содержит обычный текст;
`SecretStr` скрывает секреты при выводе настроек. Файл исключён из Git и Docker build.

MinIO AIStor Free требует получаемый у MinIO файл лицензии. Сохраните его в
`secrets/minio.license` с правами `0600`;
[инструкция MinIO](https://docs.min.io/aistor/installation/container/install/).

После подготовки:

```sh
make build
make migrate
make storage-init
make up
```

В Compose четыре сервиса: `doppelganger`, `doppelganger-db`, `doppelganger-minio`,
`doppelganger-scheduler`. Команды `migrate` и `storage-init` выполняются в разовом
контейнере образа приложения; отдельных сервисов под них нет.

- `make up` — API, PostgreSQL и MinIO;
- `make up PROFILE=app` или `make api-up` — API и PostgreSQL;
- `make up PROFILE=dbs` — PostgreSQL и MinIO;
- `make scheduler-up` — исполнитель и его зависимости;
- `make down` — остановка, данные PostgreSQL остаются в named volume.

Для API без MinIO достаточно `make build`, `make migrate`, `make api-up`.
Миграции применяйте перед запуском API и после обновлений схемы. Для внешнего
PostgreSQL задайте `POSTGRES_DB_*` в `.env` и используйте `make migrate-local`.

Порты доступны на localhost: API/Swagger — `8010/docs`, PostgreSQL — `55432`,
MinIO API — `9000`, MinIO Console — `9001`. Данные MinIO находятся в `data/minio`.
Исходники подключены в `/opt/app/src`; после изменений перезапустите сервис.

Для удалённого доступа задайте в `.env` `API_BIND_HOST`, равный IP-адресу
сетевого интерфейса сервера, и пересоздайте контейнеры: `make up`.
Админка будет доступна на порту `8010`. PostgreSQL, S3 API и MinIO Console
останутся доступны только на localhost.
Для автоматического запуска после перезагрузки включите автозапуск Docker.
Контейнеры используют `restart: unless-stopped`.

## Админка

Откройте `http://127.0.0.1:8010/admin/`. Для входа задайте в `.env`:

```env
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<ваш пароль>
ADMIN_SESSION_SECRET_KEY=<отдельная длинная случайная строка>
```

Перезапустите API после изменения этих значений. Пустой пароль или незаданный ключ
сессии не разрешают вход. При работе через HTTPS задайте `ADMIN_COOKIE_SECURE=true`.

В админке есть обзор, подключения к базам, ежедневные cron-расписания и история.
Переключатель темы находится справа вверху; выбор сохраняется в браузере.
Пароли баз не отображаются; пустое поле при редактировании сохраняет прежний пароль.
API использует отдельный ключ `X-API-Key`. Интерфейс работает без внешних CDN.

## Работа с бэкапами

В Swagger нажмите Authorize и укажите `API_KEY`: запросы используют заголовок
`X-API-Key`. Добавьте подключение через `POST /api/v1/targets`, затем план через
`POST /api/v1/plans`:

```json
{
  "name": "nightly backup",
  "target_id": 1,
  "cron": "0 2 * * *",
  "timezone": "Asia/Yekaterinburg",
  "enabled": false,
  "max_dump_seconds": 7200,
  "lock_wait_seconds": 5
}
```

Поддерживается один ежедневный запуск по выражению `минута час * * *`.
Для выполнения установите `BACKUP_EXECUTION_ENABLED=true`, перезапустите API и
выполните `make scheduler-up`. План включается через `PUT /api/v1/plans/{id}`.
Пропущенные запуски объединяются в один после запуска исполнителя.

Ручной запуск — `POST /api/v1/plans/{id}/runs`; история — `GET /api/v1/runs`.
После появления истории нельзя перенести план на другую базу: создайте новый план.
Пароли источников шифруются Fernet перед записью в PostgreSQL и не возвращаются API.

`DATA_DIR` — рабочий каталог для временного дампа. После успешной загрузки и
обновления последней копии файл удаляется. При ошибке сохранения он остаётся:
`POST /api/v1/runs/{id}/retry-s3` повторяет загрузку без нового `pg_dump`.
Если временный файл утрачен, нужен новый запуск бэкапа.

## Хранение

Настройки одного хранилища: `S3_ENDPOINT`, `S3_BUCKET`, `S3_REGION`, `S3_PREFIX`,
`S3_ACCESS_KEY`, `S3_SECRET_KEY`. Compose переопределяет адрес на
`http://doppelganger-minio:9000`; при смене хранилища измените и это значение.

Для каждой базы создаются:

```text
postgres-backups/history/production-target-1/2026-10-30_02-00-00+0500_run-3.dump
postgres-backups/latest/production-target-1/database.dump
```

Каталог содержит нормализованное имя подключения и его уникальный ID.
После первой загрузки имя каталога сохраняется при переименовании подключения.
В имени файла истории указаны время начала дампа в часовом поясе плана,
смещение относительно UTC (`+0500`) и ID запуска. Повтор загрузки использует
исходный ключ объекта, включая ключи прежнего формата `target-N/run-M.dump`.

`RETENTION_DAYS=7` удаляет историю старше семи дней через lifecycle. `0` отключает
удаление истории. Последняя успешная копия в `latest/` не имеет срока удаления.
Неудачный новый бэкап не заменяет её; повтор старого запуска не затирает свежую копию.
Незавершённые multipart-загрузки MinIO очищает своим фоновым механизмом.

`make storage-init` создаёт бакет и применяет эти правила. Повторите команду после
изменения срока хранения. Используйте выделенный приватный бакет без versioning;
инициализация сохраняет чужие правила и отклоняет удаление `latest/`.

## Нагрузка и восстановление

В один момент выполняется один `pg_dump -Fc`, без `--jobs`. Пароль передаётся через
временный `PGPASSFILE` с правами `0600`. Начальные блокировки и весь дамп имеют таймауты;
свободное место проверяется во время дампа. Незавершённый дамп не отправляется в S3.
Это не ограничивает CPU/IO мастера: первый бэкап нужно провести под наблюдением.

Образ содержит PostgreSQL-клиент версии `PG_MAJOR` (по умолчанию 18). Клиент должен
поддерживать версию источника. При `sslmode=verify-full` клиенту нужен доверенный CA.
Загрузка в S3 выполняется SDK последовательно; сетевые запросы имеют таймауты,
отмена и общий бюджет времени проверяются между порциями передачи.

Для восстановления скачайте `latest/<имя-подключения>-target-N/database.dump`
из MinIO Console:

```sh
pg_restore --host=<тестовый-сервер> --username=<пользователь> --dbname=<тестовая-база> database.dump
```

Дампы не шифруются приложением. Каждый дамп согласован внутри одной базы;
глобальные роли и служебный PostgreSQL нужно резервировать отдельно.
Политика `latest/` не защищает от потери диска. Оповещения о сбоях пока не реализованы.

## Проверки

`make test` поднимает отдельный PostgreSQL на localhost:55433 и удаляет контейнер
после завершения, включая ошибки. Каждая интеграционная проверка использует свою БД.
Исходные базы не используются. Аргументы: `make test PYTEST_ARGS="-q -k test_name"`.
Unit-тесты запускаются без Docker: `uv run pytest tests/app/unit -q`.
`make lint` проверяет форматирование и линтер. Сам AIStor и фоновое применение
lifecycle нужно проверить с действующей лицензией.
