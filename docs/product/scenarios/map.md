# Карта сценариев Given / When / Then

Формат — Gherkin, UTF-8, English keywords, русский текст шагов. Каждый сценарий имеет уникальный тег `@SC-*` и тег требования `@PRD-*`. SC-054–SC-063 исполняются через behave; для SC-001–SC-053 step definitions ещё отсутствуют. Наличие спецификации не означает пройденный тест.

| Файл | Сценарии | Область |
| --- | --- | --- |
| [templates.feature](templates.feature) | SC-001–SC-008 | Ввод, извлечение и версии шаблона |
| [formatting.feature](formatting.feature) | SC-009–SC-017 | Оформление, сохранность и вопросы |
| [results.feature](results.feature) | SC-018–SC-020, SC-030 | Валидация, скачивание и объяснения |
| [jobs.feature](jobs.feature) | SC-021–SC-024, SC-031–SC-034 | Очередь, отмена, лимиты и replay |
| [security.feature](security.feature) | SC-025–SC-029 | Изоляция, разрешение обработки, injection и удаление |
| [template-plans.feature](template-plans.feature) | SC-035–SC-038 | Inline spans, literals, object bindings |
| [research.feature](research.feature) | SC-039–SC-045, SC-053 | One-pass, бенчмарк и сравнение методов |
| [research-pilot.feature](research-pilot.feature) | SC-054–SC-063 | Исполняемые проверки текущего исследовательского среза |
| [steps/map.md](steps/map.md) | SC-054–SC-063 | Реальные step definitions без платных вызовов |
| [batches.feature](batches.feature) | SC-046–SC-052 | Очередь, частичные ZIP, бюджет и удаление |

Общие fixtures: авторизованный редактор своего workspace, синтетические source documents, mock provider, версия шаблона с подтверждёнными правилами. Для сценариев успешного оформления setup включает готовую статью, разрешение анализа и бюджет; негативный сценарий явно заменяет соответствующую предпосылку. «Поддерживаемый DOCX» означает пакет, соответствующий [матрице](../../tech/docx-compatibility.md), с известным payload baseline. Все состояния и error codes соответствуют [API](../../tech/api.md).

Вверх: [продуктовая карта](../map.md). Трассировка: [приёмка](../acceptance.md).
