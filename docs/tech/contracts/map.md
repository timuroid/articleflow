# Машиночитаемые контракты

| Файл | Назначение | Статус |
| --- | --- | --- |
| [classification.schema.json](classification.schema.json) | JSON Schema ответа классификатора | Baseline v0.1 только для ролей абзацев |
| [classification.example.json](classification.example.json) | Пример ответа, соответствующий схеме | Синтетический пример |
| [template.example.json](template.example.json) | Paragraph, character, semantic, label и object rules v0.2 | Иллюстрация, не полная схема TemplatePackage |
| [article-input.example.json](article-input.example.json) | Синтетический вход I1 с текстом, asset и marker | Без binary asset и target formatting |
| [document-plan.schema.json](document-plan.schema.json) | Ответ student: блоки, spans, figures и labels | Нормативная ограниченная схема v0.2 |
| [document-plan.example.json](document-plan.example.json) | План для связанного входа и шаблона | Проверяемый синтетический пример |
| [report.example.json](report.example.json) | Отчёт успешной обработки с визуальным предупреждением | Иллюстрация, не полная схема отчёта |

Все IDs и hashes вымышлены. JSON Schema проверяет форму ответа, но полнота/уникальность block IDs и их принадлежность входу проверяются backend отдельно. В classification baseline роли заданы enum v0.1; DocumentPlan v0.2 ссылается на vocabulary выбранного TemplatePackage. Изменение ролей требует синхронизации prompts, mapping и сценариев.

Вверх: [техническая карта](../map.md). Полные схемы TemplatePackage, DocumentIR, compiled operations и Report, а также OpenAPI появятся с реализацией. DocumentPlan v0.2 задаёт ограниченный профиль, а дополнительные runtime-инварианты описаны в [контракте](../document-plan.md). Примеры не являются исполняемым конвейером и не доказывают качество модели.
