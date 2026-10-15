# Конфигурация и эксплуатация

## Окружения

Development использует локальные PostgreSQL/Redis/S3-compatible storage и mock LLM. Staging использует синтетический/разрешённый корпус и ограниченный бюджет. Production требует утверждённых провайдера, retention, identity provider и поддержки шрифтов. Docker Compose предполагается для локального окружения, но compose-файла и команд запуска пока нет.

## Конфигурация

| Переменная | Назначение | Секрет |
| --- | --- | --- |
| DATABASE_URL | PostgreSQL connection | Да, если содержит пароль |
| REDIS_URL | Очередь | Да, если содержит credentials |
| OBJECT_STORAGE_ENDPOINT / BUCKET | S3-compatible хранилище | Нет |
| OBJECT_STORAGE_ACCESS_KEY / SECRET_KEY | Доступ к хранилищу | Да |
| OIDC_ISSUER / CLIENT_ID | Identity provider | Нет |
| OIDC_CLIENT_SECRET / SESSION_SECRET | OIDC и сессии | Да |
| LLM_BASE_URL / LLM_MODEL | Разрешённый endpoint и модель | Нет |
| EXTRACTOR_MODEL / PLANNER_MODEL | Независимые модели подготовки и применения | Нет |
| EXTRACTOR_CALL_CAP / APPLICATION_PROFILE | Предел шаблонного loop и режим student | Нет |
| LLM_API_KEY | Ключ провайдера | Да |
| MAX_UPLOAD_BYTES | Начально 26214400 | Нет |
| MAX_BATCH_ITEMS / MAX_BATCH_BYTES | Предложение 300 / 2147483648 | Нет |
| BATCH_CONCURRENCY | Начально 1 active article job на batch | Нет |
| JOB_COST_LIMIT / WORKSPACE_DAILY_COST_LIMIT | Денежный предел, валюта задаётся явно | Нет |
| DOCUMENT_RETENTION_DAYS | Предложение 30, требует утверждения | Нет |

При запуске конфигурация проверяется по схеме. Production не стартует с пустым session secret, неизвестной тарифной политикой внешней модели или открытым storage bucket. Значения секретов не выводятся при ошибках. Политики workspace могут снижать общие лимиты, но не повышать их сверх deployment policy.

## Ресурсы и масштабирование

API и workers масштабируются отдельно. Concurrency начинается с 1 DOCX job на worker process и увеличивается после измерений peak memory; распакованный XML многократно дороже сжатого файла. CPU/memory limits применяются к subprocess. LLM gateway ограничивает число параллельных запросов и суммарный денежный резерв.

Начальные deadlines и leases заданы в [жизненном цикле](job-lifecycle.md); это конфигурация для испытаний. После измерений зафиксировать hardware, набор шрифтов, версии parser/renderer и модель. Обновление модели/шрифтов — изменение воспроизводимого окружения, которое требует regression.

## Наблюдаемость

Structured logs: request_id, job_id, workspace pseudonymous ID, attempt, stage, duration, error code и versions. Не логировать текст, имена авторов, пользовательские filenames или headers Authorization. Метрики: queue age/depth, jobs by state, stage latency, review rate, validation blockers, retries, lease expirations, storage cleanup lag, provider failures, actual/reserved/unknown usage.

Alerts: рост integrity blockers, недоступность брокера/storage, outbox backlog, исчерпание бюджета, отсутствие heartbeat, нарушение удаления и необычный рост 401/429 провайдера. Ошибка качества документа отличается от инфраструктурного сбоя.

## Recovery

PostgreSQL backup и object storage versioning согласуются по retention. Restore проверяется на staging, применяет deletion tombstones и не запускает автоматически старые платные задачи. Redis восстанавливать как источник бизнес-состояния не требуется: jobs/outbox позволяют пересоздать доставку.

Перед миграцией — backup и проверка совместимости worker/API. Для изменения схемы использовать expand → migrate → contract. Workers старой версии должны либо работать с совместимым snapshot, либо прекращать claim новых jobs. Rollback рендера не пересобирает уже выданные артефакты без нового запуска.

## Минимальные runbooks

- Провайдер недоступен: остановить новые вызовы circuit breaker, сохранить jobs/checkpoints, показать retryable error, не менять провайдера автоматически.
- Рост integrity failures: остановить публикацию затронутого renderer version, сохранить защищённые диагностические hashes, воспроизвести на corpus и выпустить исправление.
- Компрометация ключа: отозвать у провайдера, ротировать secret, проверить безопасный usage ledger; не копировать старый ключ в тикеты.
- Cleanup отстаёт: сохранить tombstones, проверить доступность storage, повторить bounded batches, уведомить администратора при превышении целевого срока.

## Эксперименты и архивы v0.2

Render environment benchmark имеет immutable manifest engine/OS/fonts/rasterizer/DPI/locale/field policy. Перед pixel trials выполняется повторный рендер golden; нестабильная среда блокирует exact benchmark. Эталонный Word может требовать отдельного Windows executor и лицензии; наличие Linux worker не доказывает доступность Word.

Export workers имеют disk/memory quotas и ZIP64 support; queue/cleanup metrics отделены от LLM usage. Batch budget содержит резервы активных jobs, а paused_budget не инициирует новые calls. Strict profile выключает SDK retry и скрытые provider fallback, насколько это управляется API; неуправляемые особенности провайдера фиксируются как ограничение протокола.
