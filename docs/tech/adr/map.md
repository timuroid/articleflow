# Карта архитектурных решений

| ADR | Решение | Статус |
| --- | --- | --- |
| [001-document-engine.md](001-document-engine.md) | LLM-классификация и детерминированное изменение исходного OOXML | Предложено |
| [002-versioned-jobs.md](002-versioned-jobs.md) | Неизменяемые версии шаблонов и асинхронные задания | Предложено |
| [003-template-research.md](003-template-research.md) | TemplatePackage, one-pass исследование, batch и ZIP | Направление подтверждено; методы исследуются |
| [004-diagnostic-pilot.md](004-diagnostic-pilot.md) | Три контроля, явный hybrid и актуальные модели с бюджетом | Принято для исследовательского прототипа 0.3 |
| [005-explicit-format-variants.md](005-explicit-format-variants.md) | Полные варианты свойств, отдельные назначения и сборка нового body | Принято для oracle-контроля 0.4; выбор вариантов моделью не измерен |
| [006-compact-catalogue-plan.md](006-compact-catalogue-plan.md) | Модель выбирает варианты и точные цитаты; compiler сохраняет текст | Принято для исследовательского профиля 0.5 |
| [007-context-rules-and-indices.md](007-context-rules-and-indices.md) | Условия выбора, явные неоднозначности и source indices как payload | Принято для исследования 0.6; наблюдаемые правила требуют проверки переноса |
| [008-source-aware-application.md](008-source-aware-application.md) | Сохранение выделений и отдельное применение к исходному DOCX | Исследовательский I3 baseline; исходный gate не заменён |

Вверх: [техническая карта](../map.md). При утверждении решения указать дату и основание пилота; при замене добавить новый ADR со ссылкой, не удаляя историю.
