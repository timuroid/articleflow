# Карта исследования

| Файл | Содержание |
| --- | --- |
| [evaluation-018.md](evaluation-018.md) | Исторические метрики и свежая оценка Web 017, ограничения и исправление ZIP |
| [evaluation-018-protocol.md](evaluation-018-protocol.md) | Зафиксированный до прогона протокол бесплатной оценки |
| [evaluation-018-baseline.json](evaluation-018-baseline.json) | Все измерения исходной версии, включая отказы повторного импорта |
| [evaluation-018-patched.json](evaluation-018-patched.json) | Полный повтор после исправления ZIP, hashes и render environment |
| [evaluation-018-attempts.csv](evaluation-018-attempts.csv) | Все 70 детерминированных повторов после исправления |
| [study.md](study.md) | Вопросы, гипотезы, этапы и границы выводов |
| [manuscript-reconstructed.md](manuscript-reconstructed.md) | Новый черновик научной статьи по сохранившимся сводкам; исходная рукопись не восстановлена |
| [methods.md](methods.md) | Сравнение способов извлечения, хранения и применения |
| [benchmark.md](benchmark.md) | Протокол входа, защита от утечки, 10 повторов и измерение пикселей |
| [experiment-plan.json](experiment-plan.json) | Машиночитаемый план первого эксперимента без выдуманных результатов |
| [results.csv](results.csv) | Числовые результаты реальных запросов, включая все неуспехи |
| [pilot-001.md](pilot-001.md) | Полученный DOCX, извлечённый шаблон, контроль renderer, результаты и следующие гипотезы |
| [pilot-001-summary.json](pilot-001-summary.json) | Машиночитаемые агрегаты, ограничения и фактические расходы |
| [renderer-004.md](renderer-004.md) | Причины расхождений, новый каталог и 10 точных oracle-сборок |
| [renderer-004-summary.json](renderer-004-summary.json) | Метрики 0.4, hashes, render-среда и границы результата |
| [renderer-004-results.csv](renderer-004-results.csv) | Все 10 повторов сборки без вызовов LLM |
| [planner-005.md](planner-005.md) | Выбор вариантов моделью, все попытки, стоимость и контроль неоднозначности |
| [planner-005-summary.json](planner-005-summary.json) | Агрегаты model trials 0.5 и доказательные ограничения |
| [planner-005-results.csv](planner-005-results.csv) | Диагностическая попытка и замороженная серия модели |
| [source-aware-007.md](source-aware-007.md) | Отдельное применение к исходному DOCX, source marks и свежие role-only серии |
| [source-aware-007-summary.json](source-aware-007-summary.json) | Две серии I3 по 10/10, бюджет, ограничения и проверки |
| [source-aware-007-results.csv](source-aware-007-results.csv) | Все 20 свежих попыток, токены, стоимость и exact metrics |
| [rules-006.md](rules-006.md) | Условия выбора, сохранение индексов, абляции и replay без API |
| [rules-006-summary.json](rules-006-summary.json) | Покрытие правил, неоднозначные группы, результаты и бюджет |
| [rules-006-results.csv](rules-006-results.csv) | Все повторные сборки и отдельная запись невалидного исходного плана |
| [model-selection.md](model-selection.md) | Проверка новизны моделей, источники дат, тарифы и ограничение бюджета |
| [models.json](models.json) | Допустимые новые кандидаты с датой выпуска и первичным источником |
| [qwen-008.md](qwen-008.md) | Проверка Qwen3.8-27B на неизменном I3-контракте серии 007 |
| [qwen-008-summary.json](qwen-008-summary.json) | Агрегаты medium, обрезания, HTTP 429, стоимость и неопределённый резерв |
| [qwen-008-results.csv](qwen-008-results.csv) | Все десять попыток Qwen medium, включая неуспехи |
| [qwen-009.md](qwen-009.md) | Отдельная серия Qwen с отключённым reasoning после наблюдения обрезаний |
| [qwen-009-summary.json](qwen-009-summary.json) | Агрегаты без reasoning и сравнение с medium/Sol/Luna |
| [qwen-009-results.csv](qwen-009-results.csv) | Все десять попыток Qwen без reasoning |
| [session-017-recovery.md](session-017-recovery.md) | Исторические результаты структурного Web 017 без доступных здесь первичных артефактов |
| [session-010-016-recovery.md](session-010-016-recovery.md) | Карта промежуточных серий, сведения для восстановления и границы выводов |
| [dialogue-recovery-2026-10-17.md](dialogue-recovery-2026-10-17.md) | Сверка общего диалога с Git, локальными копиями и потерянными первичными файлами |

Вверх: [общая карта](../map.md). Схемы и понимание задачи: [концепция](../product/concept.md). Формат хранения: [TemplatePackage](../tech/template-package.md). Формат ответа модели: [DocumentPlan](../tech/document-plan.md).

Состояние: выполнен диагностический LLM-пилот 0.3 и точный oracle-контроль сборщика 0.4 на одном предоставленном DOCX. В 0.4 все 10 свежих сборок совпали по пикселям; в [0.5](planner-005.md) модельный выбор дал 0/10 полных совпадений. В [0.6](rules-006.md) повторные сборки с правилами и source indices дали content exact 9/9, exact pixels 0/9 без новых вызовов модели. Строгий I1 и независимый transfer не пройдены. Ключи, рукописи, исходные выделения и ответы моделей не хранятся в этой папке. Код и команды: [каталог 0.4](../tech/catalogue-renderer.md), [runner 0.3](../tech/research-prototype.md).

Текущий дополнительный результат: [I3 0.7](source-aware-007.md) дал по 10/10 полных совпадений у Sol и Luna, с исходным оформлением во входе. Это не меняет прежнее непрохождение I1/I2 и не является unseen transfer.

Сравнение Qwen3.8-27B: [008 medium](qwen-008.md) — 6/10, [009 none](qwen-009.md) — 9/10; все девять полученных документов none точны, одна попытка завершилась HTTP 429. Все 20 попыток сохранены. Показатели не заменяются условной точностью только успешных ответов; неопределённые расходы двух HTTP-ошибок остаются зарезервированными в общем бюджете.

- [Новые прогоны, сравнение 018/019 и все модельные попытки](evaluation-019.md).

- [Серверный smoke и состояние бюджета 019](deployment-019-results.json).

- [Замысел рукописи 020](manuscript-020-brief.md), [протокол](transfer-020-protocol.md), [результаты](evaluation-020.md) и [машинная сводка](evaluation-020.json).

- [Повторный перенос и ошибки полноты 021](evaluation-021.md).

- [Оценка 022](evaluation-022.md) — полное извлечение и визуальный цикл.

- [Серверная приёмка 022](deployment-022-results.json) — HTTPS, DOCX, ZIP,
  проверка шрифтов и отказ реальному шаблону по рабочему roundtrip.

- [Серия 023: обучение большой моделью и реальное применение Qwen](evaluation-023.md),
  [измерения](evaluation-023.json), [рукопись с восемью рисунками](manuscript-023.md).
