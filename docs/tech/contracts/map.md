# Машиночитаемые контракты

| Файл | Назначение | Статус |
| --- | --- | --- |
| [classification.schema.json](classification.schema.json) | JSON Schema ответа классификатора | Нормативная ограниченная схема v0.1 |
| [classification.example.json](classification.example.json) | Пример ответа, соответствующий схеме | Синтетический пример |
| [template.example.json](template.example.json) | Представление утверждённых правил | Иллюстрация, не полная схема TemplateSpec |
| [report.example.json](report.example.json) | Отчёт успешной обработки с визуальным предупреждением | Иллюстрация, не полная схема отчёта |

Все IDs и hashes вымышлены. JSON Schema проверяет форму ответа, но полнота/уникальность block IDs и их принадлежность входу проверяются backend отдельно. Допустимые роли в схеме являются vocabulary v0.1; изменение vocabulary требует синхронного изменения prompts, mapping и сценариев.

Вверх: [техническая карта](../map.md). Полные схемы TemplateSpec, DocumentIR, FormattingPlan и Report, а также OpenAPI должны появиться вместе с реализацией соответствующих контрактов. До этого нельзя считать примеры исчерпывающим описанием допустимых данных.
