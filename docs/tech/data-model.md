# Модель данных

## Сущности и связи

Все бизнес-сущности принадлежат workspace. UUID не заменяет проверку доступа. Время UTC, валюта/стоимость — decimal или целые минимальные единицы, не float. Большие бинарные данные и извлечённые тексты хранятся в object storage; в БД — ссылки и hashes.

| Сущность | Основные поля | Инварианты |
| --- | --- | --- |
| Workspace | id, name, retention_policy, provider_config_id | Политика доступа и расходов едина для пространства |
| Membership | workspace_id, user_id, role | Уникальная пара; role admin/editor |
| Upload | id, workspace_id, status, byte_size, sha256, object_key | uploading → validating → ready/rejected; временный объект не доступен как документ |
| Document | id, workspace_id, upload_id, kind, source_hash, inventory_ref, deleted_at | kind sample/article; источник immutable |
| ProcessingConsent | id, workspace_id, actor_id, document_hash, provider_config_version, purpose, granted_at, revoked_at | Разрешение привязано к данным и обработчику |
| Template | id, workspace_id, name, archived_at | Содержит версии, не mutable «активный JSON» |
| TemplateVersion | id, template_id, number, status, revision, source_document_id, spec_ref, compiled_hash | draft/approved/archived; номер уникален внутри template |
| Job | id, workspace_id, kind, document_id, template_version_id, state, stage, state_version, attempt_no | kind extract_template/format_article; версия шаблона обязательна для format_article |
| JobAttempt | id, job_id, ordinal, lease_token, heartbeat_at, deadline_at | Один актуальный lease, старый worker не публикует результат |
| Checkpoint | job_id, stage, dependency_hash, artifact_ref | Повтор использует только совместимый checkpoint |
| Review | id, job_id, revision, questions_ref, status | open/resolved/superseded; ответы относятся к точной revision |
| ReviewDecision | review_id, question_id, actor_id, answer, created_at | Уникальное принятое решение вопроса в revision |
| Artifact | id, workspace_id, job_id, kind, key, sha256, available, expires_at | Результат доступен только после общей валидации |
| UsageLedger | job_id, request_id, status, reserved_cost, actual_cost, token_counts | reserved/settled/unknown; не терять unknown после timeout |
| AuditEvent | id, workspace_id, actor_id, action, entity_id, at, safe_metadata | Без рукописей и секретов |
| OutboxEvent | id, aggregate_id, event_type, payload, published_at | Создаётся в транзакции изменения Job |
| TemplatePackageManifest | template_version_id, schema_version, manifest_hash, resources, compiler_version | Immutable; runtime resources отделены от evidence |
| ApplicationProfile | id, version, method, input_protocol, model_config_version, call_limits, render_mode | Strict не получает скрытых fallback/retries |
| Batch | id, workspace_id, template_version_id, profile_id, state, generation, sealed_manifest_ref, budget | Item set и template hash фиксируются при seal |
| BatchItem | id, batch_id, ordinal, client_item_id, upload_id, document_id, current_job_id, upload_error | Rejected upload остаётся в manifest |
| BatchExport | id, batch_id, generation, revision, snapshot_ref, artifact_id, state, partial | Immutable snapshot; queued/running/completed/failed/revoked |
| ExportMember | export_id, document_id, artifact_id | Индекс зависимостей для отзыва ZIP при удалении |
| ExperimentRun | id, manifest_ref, input/template/model/render hashes, measurements_ref | Fresh trial отдельно от replay; private artifacts вне Git |

Связи: Workspace → Documents/Templates/Jobs; Template → TemplateVersions; Job → Document и (для форматирования) TemplateVersion; Job → Attempts/Reviews/Artifacts/Usage. Все внешние ключи workspace-bound проверяются составными ограничениями или эквивалентной обязательной серверной проверкой. Нельзя сослаться на template version другого пространства.

## Версии и конкуренция

`revision` черновика меняется при каждом PATCH. API требует If-Match текущей revision, иначе `409 REVISION_CONFLICT`. Утверждение создаёт immutable snapshot в той же сущности версии, фиксирует approved_at/approved_by и compiled_hash. Дальнейший draft получает новый version ID/number. Архивирование не меняет утверждённый spec.

Job фиксирует source hash, template version/hash, plan hash и версии tooling. Состояния изменяются compare-and-swap по state_version. Lease token препятствует записи старого worker после takeover. Artifact key включает job ID и attempt ID; публикация выбирает только валидную текущую попытку.

Job v0.2 также фиксирует profile version, input protocol, render mode, counters calls/attempts и optional batch/item/generation. Для batch job действует unique(batch_id, item_id, generation). ExportMember строится по точному snapshot перед выдачей ZIP; tombstone любого member отзывает export независимо от его URL.

## Object storage

Префикс: `workspaces/<workspace_id>/documents/<document_id>/...` и `workspaces/<workspace_id>/jobs/<job_id>/attempts/<attempt_id>/...`. Ключи генерирует сервер; пользовательское имя файла хранится отдельно, не превращается в путь. Сам префикс не является контролем доступа.

Типы артефактов: original_docx, package_inventory, document_ir, template_spec, role_assignments, formatting_plan, output_docx, validation_report. Для output_docx хранится итоговый checksum и verified=true. Общедоступные buckets запрещены.

## Удаление и retention

Удаление сначала помечает Document deleted_at, запрещает выдачу и отменяет jobs. Cleanup удаляет исходники, IR, prompts/results и выходные артефакты, затем снимает доступ к оставшимся ссылкам. Аудит может хранить минимальные технические события без текста согласно политике.

Образец утверждённого шаблона — dependency: его нельзя автоматически удалить как обычную статью, пока evidence нужен версии. При явном полном удалении шаблона удаляются образец и evidence после проверки отсутствия других зависимостей; запуски сохраняют разрешённый минимальный snapshot правил без текста образца. Точные сроки и юридические основания должны быть утверждены до production.
