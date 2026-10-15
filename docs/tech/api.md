# HTTP API v1

## Общие правила

Базовый путь `/api/v1`. JSON UTF-8; UUID для IDs, RFC 3339 UTC для timestamps. Аутентификация через серверную сессию OIDC, Secure/HttpOnly/SameSite cookie; изменяющие запросы защищены CSRF. Workspace задаётся в пути и проверяется по membership на каждом запросе. Payload validation и object ownership выполняются до обращения к хранилищу/модели.

Списки используют cursor pagination, limit по умолчанию 20, максимум 100. Ответ списка: `items`, `next_cursor`. Все ответы включают request ID. Клиент не передаёт storage keys, API keys, provider base URL или готовые OOXML-операции.

## Загрузка и документы

| Метод и путь после `/workspaces/{wid}` | Запрос | Ответ |
| --- | --- | --- |
| `POST /uploads` | multipart file + kind sample/article | `201` upload_id, status=validating; размер ограничивается потоково |
| `GET /uploads/{id}` | — | `200` status, document_id если ready; error если rejected |
| `GET /documents/{id}` | — | `200` metadata, inventory summary, compatibility |
| `POST /documents/{id}/consents` | provider_config_version, purpose | `201` consent_id, granted_at |
| `DELETE /documents/{id}/consents/{consentId}` | — | `204`; предотвращает новые LLM-вызовы, отменяет зависимую обработку |
| `DELETE /documents/{id}` | подтверждённая команда удаления | `202` deletion_id, status=pending |
| `GET /deletions/{id}` | — | `200` pending/running/completed/failed и retryable |

Загрузка не вызывает модель. Upload worker выполняет только безопасную проверку/инвентаризацию. Выдача Document происходит после ready. Большие прямые multipart-to-S3 upload sessions могут быть добавлены позднее без изменения Document semantics.

## Шаблоны

| Метод и путь | Запрос | Ответ |
| --- | --- | --- |
| `GET /templates` | cursor, limit, status, query | `200` список |
| `POST /templates` | name, description, sample_document_id, consent_id | `202` template_id, draft_version_id, extraction_job_id |
| `GET /templates/{id}/versions/{vid}` | — | `200` spec, revision, questions, status |
| `PATCH /templates/{id}/versions/{vid}` | разрешённые изменения draft; If-Match | `200` spec и новая revision |
| `POST /templates/{id}/versions/{vid}/approve` | expected_revision | `200` approved version/hash; `409` при конфликте |
| `POST /templates/{id}/versions` | based_on_version_id | `201` новый draft |
| `POST /templates/{id}/archive` | — | `200` archived; старые jobs доступны |

Все пути в этой и следующей таблице также имеют префикс `/workspaces/{wid}`. Создание template с отсутствующим согласованием возвращает `422 PROCESSING_CONSENT_REQUIRED`. Утверждение черновика с вопросами — `422 TEMPLATE_UNRESOLVED`. Extraction job завершается с draft version artifact, без output_docx.

## Задания и артефакты

| Метод и путь | Запрос | Ответ |
| --- | --- | --- |
| `POST /jobs` | document_id, template_version_id, consent_id, limits | `202` job_id, state=queued |
| `GET /jobs` | cursor, state, template_id | `200` список |
| `GET /jobs/{id}` | — | `200` state, stage, state_version, review, artifacts, safe error |
| `GET /jobs/{id}/events` | after_sequence | `200` упорядоченный список событий и next_sequence |
| `POST /jobs/{id}/review-decisions` | review_revision, answers[{question_id, option_id}] | `200` оставшиеся вопросы или `202` queued при разрешении всех |
| `POST /jobs/{id}/cancel` | — | `202` cancel_requested; повтор возвращает актуальное состояние |
| `POST /jobs/{id}/retry` | mode replay_plan/reanalyze | `202` новый job_id, parent_job_id |
| `GET /artifacts/{id}/download` | — | `200` авторизованный streaming download |

`limits` может только уменьшать лимит пространства. Retry проверяет доступность исходников, актуальность согласия и выбранный mode; reanalyze может расходовать бюджет. Изменение версии шаблона выполняется новым POST /jobs. Retry не изменяет терминальную запись старого запуска.

Скачивание проходит через API/proxy, который проверяет tombstone при каждом запросе. Если позже используются presigned URLs, они имеют короткий TTL и явно описанный предел отзыва; в MVP прямые bearer URLs для скачивания не нужны. У failed job доступен отчёт, но не output_docx. Отсутствующий/чужой artifact возвращает `404`.

## Идемпотентность и конкуренция

POST, создающие upload/template/job/retry, требуют `Idempotency-Key`. Область уникальности: workspace + actor + route + key. Сервер хранит request hash и ответ минимум 24 часа. Повтор с тем же payload возвращает прежний ресурс и статус; с другим payload — `409 IDEMPOTENCY_CONFLICT`. Для файлов request hash включает потоковый SHA-256. Терминальные записи и unique constraints защищают от дублирования обработки даже после истечения HTTP-cache.

PATCH draft требует `If-Match: "<revision>"`. Review требует review_revision; устаревший ответ — `409 REVIEW_STALE`. Уже завершённый job нельзя возобновить ответом старой формы. Cancel завершённого job возвращает `409 JOB_TERMINAL`, кроме повторного cancel уже cancelled job, который возвращает `200` текущий статус.

## Ошибки

```json
{
  "error": {
    "code": "TEMPLATE_UNRESOLVED",
    "message": "Перед утверждением ответьте на обязательные вопросы",
    "details": {"question_ids": ["q-1"]},
    "retryable": false,
    "request_id": "req-example"
  }
}
```

`400` malformed request; `401` no session; `403` роль не разрешает действие в своём workspace; `404` не найдено/чужое; `409` версия/состояние/идемпотентность; `413` размер; `415` неверный формат; `422` семантическая валидация; `429` rate limit; `503` временно недоступна инфраструктура.

Ошибки асинхронного этапа содержатся в GET job/upload; polling получает `200`, даже если state=failed. Stable codes: `UNSUPPORTED_DOCX`, `LIMIT_EXCEEDED`, `PROCESSING_CONSENT_REQUIRED`, `TEMPLATE_NOT_APPROVED`, `TEMPLATE_UNRESOLVED`, `REVIEW_STALE`, `LLM_UNAVAILABLE`, `LLM_INVALID_OUTPUT`, `BUDGET_EXCEEDED`, `INTEGRITY_VIOLATION`, `SOURCE_DELETED`. OpenAPI будет генерироваться из будущего backend; сейчас этот файл — контракт проектирования.
