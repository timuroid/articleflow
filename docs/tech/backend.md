# Backend

## Организация кода

Будущая структура: `apps/api` для HTTP, `apps/worker` для задач, `packages/document_engine` для OOXML/IR/plans, `packages/contracts` для DTO и схем. Это проектная структура; каталоги ещё не созданы. Выделение packages служит границам зависимостей, а не требует отдельных сервисов.

API routes принимают DTO, вызывают application service и сериализуют результат. Application services проверяют права и бизнес-инварианты, управляют транзакциями. Repositories скрывают SQL/object storage. Чистый document engine не читает окружение, не обращается в БД и не вызывает LLM. Зависимости внедряются через интерфейсы для фикстур и отказоустойчивых тестов.

## Создание задания

1. Проверить сессию, membership, размер запроса и Idempotency-Key.
2. Загрузить source Document, consent и approved TemplateVersion в контексте workspace.
3. Проверить состояние, checksum, budget policy и наличие исходного объекта.
4. В транзакции создать Job с immutable input snapshot, idempotency record и OutboxEvent.
5. Вернуть `202` после commit. Сбой брокера не откатывает принятую команду: outbox повторит доставку.

Не держать транзакцию открытой на время LLM, ZIP-парсинга или скачивания объекта. Для записи результата после внешней работы требуется новая короткая транзакция и проверка fencing token.

## Upload и артефакты

HTTP принимает поток с лимитом; сохраняет карантинный объект с server-generated key. После окончания проверяет checksum, записывает Upload и событие валидации. При сбое DB после записи объекта orphan cleanup удаляет неприкреплённый объект по TTL. При сбое загрузки частичный объект не становится Document.

Результат сначала пишется во временный immutable key, затем validator проверяет конкретный hash. Только после этого DB привязывает Artifact и state. Между S3 и PostgreSQL нет общей транзакции, поэтому порядок записи и сборщик orphan objects обязательны. Пользователь не получает адрес временного ключа.

## Конкуренция и права

Одновременное редактирование template draft защищено revision. Два approve одной revision возвращают один результат либо конфликт без дубликата version number. Все запросы дочерних сущностей фильтруются через workspace; в worker это проверяется снова по snapshot и tombstone.

Административные настройки провайдера меняет только admin. Настройки передаются worker по ID версии; нельзя менять endpoint через параметры job. Tenant isolation покрывается интеграционными тестами с двумя рабочими пространствами.

## Фоновые процессы

Outbox publisher, job worker, lease reaper, retention cleanup и usage reconciler — отдельные процессы/задачи одного приложения. Их метрики и health checks независимы. Cleanup имеет bounded batch size, идемпотентные DELETE и retry для временных сбоев storage. Ошибка cleanup не возвращает доступ к tombstoned документу.

Для parsing/rendering worker subprocess запускается без сетевого доступа с ограничениями CPU/memory/time. LLM-вызов идёт через gateway в процессе, которому разрешён нужный endpoint. Увеличение worker concurrency ограничено памятью DOCX-пакета и бюджетом провайдера, а не только CPU.
