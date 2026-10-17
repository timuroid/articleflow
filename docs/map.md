# Карта документации

| Папка / файл | Назначение |
| --- | --- |
| [research/evaluation-018.md](research/evaluation-018.md) | Свежие прогоны Web 017 и сопоставление с прежними метриками |
| [product/map.md](product/map.md) | Продукт, интерфейс, сценарии, критерии приёмки |
| [tech/map.md](tech/map.md) | Архитектура, алгоритмы, данные, API, эксплуатация |
| [research/map.md](research/map.md) | Методы шаблонизации, входные протоколы, бенчмарк и выбор модели |
| [../datasets/map.md](../datasets/map.md) | Доступный синтетический DOCX-корпус и инвентаризация пропавших данных |
| [../agent.md](../agent.md) | Процесс SDD и правила изменений |
| [../README.md](../README.md) | Точка входа в проект |
| [tech/web-017-recovery.md](tech/web-017-recovery.md) | Фактический состав GitHub и карта восстановления прежнего локального Web 017 |
| [tech/deployment.md](tech/deployment.md) | Установка только после получения и проверки релиза |
| [product/structure-017.md](product/structure-017.md) | Порядок смысловых блоков, перенос фрагментов и недостающие поля |
| [research/session-017-recovery.md](research/session-017-recovery.md) | Исторические наблюдения 017 и предел их воспроизводимости |
| [research/session-010-016-recovery.md](research/session-010-016-recovery.md) | Известные результаты пропавших локальных серий и перечень первичных файлов |
| [research/manuscript-reconstructed.md](research/manuscript-reconstructed.md) | Новый научный черновик по сохранившимся первичным сводкам; прежняя рукопись отсутствует |
| [research/dialogue-recovery-2026-10-17.md](research/dialogue-recovery-2026-10-17.md) | Сверка прежнего диалога с локальными файлами, Git и потерянными материалами |
| [tech/web-017-local.md](tech/web-017-local.md) | Новый локальный веб-срез, HTTP и хранение |
| [tech/deployment-observation-017.md](tech/deployment-observation-017.md) | Проверенный первый запуск восстановленного Web 017 |
| [tech/deployment-observation-018.md](tech/deployment-observation-018.md) | Проверенное обновление ZIP-упаковки и независимая копия серии 018 |
| [tech/structure-017-local.md](tech/structure-017-local.md) | Структурная сборка DOCX и границы точности |
| [tech/data-preservation.md](tech/data-preservation.md) | Публикация, закрытые резервные копии и проверка восстановления |

Порядок знакомства: [концепция и схемы](product/concept.md) → исследование → хранение шаблона и DocumentPlan → продукт и интерфейс → сценарии → технические контракты. Нормативное слово «должен» описывает целевое обязательство реализации, а не уже существующую функцию. Текущая спецификация `0.2` от 2026-10-15; старые контракты с явной версией `0.1` сохранены как ограниченные baselines, а ADR отмечают изменения решений.

Исследовательский срез обновлён до `0.7`: [I3 baseline](tech/source-aware.md), [source marks](tech/semantic-marks.md), [исследование 0.7](research/source-aware-007.md). Предыдущий этап 0.6: [правила контекста](tech/context-rules.md), [offline измерения](research/rules-006.md). Предыдущий модельный этап: [компактный планировщик](tech/compact-planner.md), [исследование выбора вариантов](research/planner-005.md). Предыдущий этап: [каталог и сборщик](tech/catalogue-renderer.md), [точное восстановление с oracle](research/renderer-004.md). Сохраняются [прототип 0.3](tech/research-prototype.md), [LLM-пилот](research/pilot-001.md) и [выбор актуальных моделей](research/model-selection.md). Продуктовые контракты v0.2 остаются целевыми и не объявляются реализованными этим срезом.

Требования обозначаются `PRD-*`, сценарии — `SC-*`, архитектурные решения — `ADR-*`. Связи между ними собраны в [приёмке](product/acceptance.md). Неподтверждённые решения и вопросы вынесены в отдельный [реестр](product/open-questions.md).

Дополнительное сравнение на неизменном CLI 0.7.0: [Qwen3.8-27B с medium](research/qwen-008.md) и [отдельная серия без reasoning](research/qwen-009.md). Эти измерения относятся к I3 и не заменяют первоначальное исследование I1/I2.

- [Рабочее восстановление 019 и ограничения](tech/recovery-019.md).

- [Полнота шаблона и визуальный контроль 021](tech/transfer-021.md).

- [Полный визуальный контроль 022](tech/visual-agent-022.md).

- [Агентный контракт 023](tech/agent-023.md).
