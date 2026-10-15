# Проверка реализации

## Что проверяем сейчас и позже

На этапе документации проверяются ссылки, карты, уникальность требований/сценариев, синтаксис Gherkin и JSON. Это не доказывает работу приложения. При реализации сценарии связываются со step definitions, а инварианты DOCX — с реальными пакетами.

## Уровни тестирования

| Уровень | Содержание |
| --- | --- |
| Unit | Разрешение наследования стилей, единицы, role mapping, компилятор правил, state transitions |
| Package fixtures | Чтение/изменение DOCX с таблицами, OMML, изображениями, notes и relationships |
| Property / mutation | Вставить/удалить символ, изменить число, media byte, URI или ячейку и убедиться, что validator блокирует |
| Integration | PostgreSQL + storage + очередь, outbox, повтор сообщения, lease takeover, отмена во время publish |
| API contract | Авторизация, idempotency, revision conflict, upload limits, errors и download restrictions |
| Frontend / E2E | Образец → approval → статья → review → скачивание, восстановление страницы и клавиатура |
| LLM offline | Записанные синтетические ответы, invalid JSON, неизвестные IDs, provider failures и injection |
| LLM live | Отдельный разрешённый прогон с бюджетом, актуальной моделью и corpus без приватных данных |
| Visual manual | Открытие в согласованной версии Word, проверка формул, переносов, таблиц и полей |

Не писать snapshot-тесты всего ZIP как основной oracle: они ломаются от timestamps и не объясняют семантический дефект. Для replay сравнивать payload fingerprints и effective formatting. Отдельно можно проверять reproducible packaging при фиксированных метаданных, но это не продуктовая гарантия.

## Фикстуры

Каждая fixture имеет manifest: ID, права использования, исходный checksum, constructs, ожидаемые роли, expected warnings/blockers и reference template version. Синтетические DOCX предпочтительны в Git; текущий `.gitignore` исключает DOCX по умолчанию. Разрешённую синтетическую fixture добавляют точечным исключением вместе с manifest и объяснением, не снимая глобальную защиту для uploads.

Негативный корпус: поддельный extension, DOCM, ZIP traversal, excessive compression, DTD, broken rId, tracked changes, Strict namespaces, floating objects, missing font, внешняя гиперссылка и prompt injection. Проверка должна завершаться ограниченно по ресурсам и не обращаться по URL из файла.

## Gherkin

Feature-файлы находятся в [product/scenarios](../product/scenarios/map.md). Используются English keywords и русский доменный текст. Теги `@SC-*` уникальны на Scenario/Scenario Outline, `@PRD-*` связывают требования. Scenario Outline разворачивается в несколько тест-кейсов. При реализации можно использовать pytest-bdd или Cucumber; выбор runner не должен менять бизнес-смысл.

## CI и выпуск

Предлагаемый CI: проверка документации/схем → type/lint → unit/contract → package corpus → integration → минимальный E2E. Live LLM не запускается на каждый commit. Реальные документы и model payloads не выгружаются в публичные CI artifacts. На изменение renderer/parser/validator выполняется весь regression corpus, на изменение UI — соответствующие пользовательские пути.

Выпуск требует критериев [приёмки](../product/acceptance.md). Если новый редкий объект нельзя сохранить, тест фиксирует отказ или review, а не безусловный success. Улучшение процентной автоматизации не оправдывает ослабление проверки содержания.

## Исследовательский и пакетный контур v0.2

Проверять связность синтетических input/template/DocumentPlan, Unicode offsets (включая emoji/combining marks), overlapping spans, неоднозначный emphasis, caption binding и повторную вставку label. Изменённый scientific text в G-FULL обязан блокироваться независимо от визуального сходства.

Strict tests измеряют реальные SDK/API attempts: invalid response, timeout и context overflow не запускают repair/chunks. Recovery после неопределённого внешнего вызова не производит скрытый повтор. Golden leakage проверяется запретом target styles/pages/offsets в student resources и отдельным rebuild adapter.

Pixel benchmark запускается по [протоколу](../research/benchmark.md) только в зафиксированной render-среде; parser проверка Mermaid/JSON не считается испытанием DOCX. Для batch нужны 100/200/300-item tests с rejected uploads, review, одинаковыми именами, потерей worker, budget pause, частичным ZIP, cleanup и отзывом архивов. Сначала mock нагрузка; платное качество оценивается отдельно с разрешённым бюджетом.
