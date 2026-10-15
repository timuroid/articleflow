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
| `POST /templates` | name, description, sample_document_id, extraction_method, consent_id при внешнем анализе | `202` при E-ONCE/E-LOOP; `201` template_id, draft_version_id для E-MANUAL |
| `GET /templates/{id}/versions/{vid}` | — | `200` spec, revision, questions, status |
| `PATCH /templates/{id}/versions/{vid}` | разрешённые изменения draft; If-Match | `200` spec и новая revision |
| `POST /templates/{id}/versions/{vid}/approve` | expected_revision | `200` approved version/hash; `409` при конфликте |
| `POST /templates/{id}/versions` | based_on_version_id | `201` новый draft |
| `POST /templates/{id}/archive` | — | `200` archived; старые jobs доступны |

Все пути в этой и следующей таблице также имеют префикс `/workspaces/{wid}`. Внешнее извлечение без согласия возвращает `422 PROCESSING_CONSENT_REQUIRED`. E-MANUAL создаёт пустой draft без LLM job; canonical rules загружаются через PATCH с If-Match. Утверждение с вопросами — `422 TEMPLATE_UNRESOLVED`; compile также проверяет runtime package на перенос текста образца. Extraction job завершается draft artifact, не output_docx.

## Задания и артефакты

| Метод и путь | Запрос | Ответ |
| --- | --- | --- |
| `POST /jobs` | document_id, template_version_id, application_profile_id, consent_id, limits | `202` job_id, state=queued, profile snapshot |
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

## Расширения v0.2: профили, batch и exports

Все пути ниже также внутри `/workspaces/{wid}`. `GET /application-profiles` возвращает доступные immutable profiles: method, input protocol, render mode, model config version, call limits и human-readable label. Клиент выбирает ID, но не передаёт произвольные model endpoints. GET job дополнен profile snapshot, counters API attempts/model calls/repair calls, human_edits и strict_eligible.

| Метод и путь | Запрос | Ответ |
| --- | --- | --- |
| `POST /batches` | template_version_id, application_profile_id, items[{client_item_id, filename, declared_size}], limits | `201` batch_id, item IDs, state=draft |
| `POST /batches/{id}/items/{itemId}/upload` | multipart file, Idempotency-Key | `201` upload_id; проверка как у обычного upload |
| `GET /batches/{id}` | — | `200` state, generation, counters, budget, export summaries |
| `GET /batches/{id}/items` | cursor, state, limit | `200` paginated items с upload/job/error |
| `POST /batches/{id}/start` | expected_revision, provider_config_version, grant_processing_consent=true | `202` sealed manifest hash, generation, state |
| `POST /batches/{id}/cancel` | — | `202` cancel_requested; повтор идемпотентен |
| `POST /batches/{id}/retry-failed` | expected_generation, item_ids, mode | `202` новая generation и новый manifest |
| `POST /batches/{id}/resume` | expected_generation, limit amendment в пределах workspace policy | `202`; только paused_budget, расход выше разрешённого не допускается |
| `POST /batches/{id}/exports` | generation, allow_partial, expected_revision | `202` export_id, snapshot hash, partial |
| `GET /batches/{id}/exports/{eid}` | — | `200` state, snapshot counts, artifact_id если готов |
| `GET /batches/{id}/exports/{eid}/download` | — | `200` авторизованный ZIP stream после проверки members |

Все mutating POST поддерживают Idempotency-Key с payload hash. Item uploads ограничены суммарным batch budget по фактическим байтам, а не только declared_size. Start не принимает новые items после seal; rejected uploads остаются в manifest. Для каждого ready документа создаётся consent с точным hash и целью; список предварительно показан пользователю. Несовпавшая provider config даёт `409`, отсутствующее согласие — `422`. Если сам frontend лишь повторяет ранее принятое start, новые согласия/задания не дублируются.

Retry-failed создаёт новые Jobs только выбранных failed/cancelled items с готовым исходником. Rejected uploads исправляются новым draft batch либо повторной загрузкой до первого seal; нельзя заменить bytes документа в sealed generation. Старые поколения и exports неизменяемы. Для удаления применяется обычный document endpoint, каскадно отзывающий включающие его архивы.

При allow_partial=false незавершённый batch даёт `409 BATCH_NOT_FINISHED`. Терминальный completed_with_errors допускает ZIP с manifest всех ошибок, `partial=true`; отсутствие успешных DOCX допускает manifest-only ZIP с понятной маркировкой. При удалённом member существующий export получает `revoked`, download возвращает `410 EXPORT_REVOKED`; чужой ID по-прежнему `404`. Размер, count и queue pressure ограничиваются до запуска.

## Формат ошибок

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
