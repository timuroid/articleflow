# Карта технической документации

- [semantic-marks.md](semantic-marks.md) — явное сохранение исходных выделений и границ диапазонов.
- [source-aware.md](source-aware.md) — отдельный I3 baseline с сохранением допустимых исходных вариантов.

| Файл | Область |
| --- | --- |
| [architecture.md](architecture.md) | Компоненты, границы ответственности и предложенный стек |
| [document-pipeline.md](document-pipeline.md) | Сквозные алгоритмы образца и статьи |
| [docx-compatibility.md](docx-compatibility.md) | OOXML, поддержка объектов и лимиты |
| [template-extraction.md](template-extraction.md) | Извлечение наблюдений и утверждение правил |
| [template-package.md](template-package.md) | Хранение шаблона, inline-правила, labels, captions и assets |
| [document-plan.md](document-plan.md) | Контракт ответа student, диапазоны символов и bindings |
| [batch-processing.md](batch-processing.md) | Сотни статей, очередь, частичные результаты и ZIP |
| [formatting.md](formatting.md) | План преобразований и сборка DOCX |
| [validation.md](validation.md) | Проверки целостности, оформления и отчёт |
| [llm.md](llm.md) | Адаптер модели, prompts, JSON, бюджет и защита от инструкций в статьях |
| [data-model.md](data-model.md) | Сущности, связи, версии и хранение |
| [api.md](api.md) | HTTP-контракты и ошибки |
| [job-lifecycle.md](job-lifecycle.md) | Состояния, очередь, повтор, отмена и review |
| [backend.md](backend.md) | Модули сервера, транзакции и фоновые задачи |
| [frontend.md](frontend.md) | Устройство клиента, формы и восстановление состояния |
| [security.md](security.md) | Доступ, секреты, недоверенные DOCX и удаление |
| [testing.md](testing.md) | Стратегия тестирования и корпус |
| [research-prototype.md](research-prototype.md) | Реализованный CLI 0.3, формат диагностического шаблона, запуск и ограничения |
| [context-rules.md](context-rules.md) | Контекстные правила 0.6, неоднозначность и сохранение научных индексов |
| [compact-planner.md](compact-planner.md) | План 0.5: выбор моделью полных вариантов, точные цитаты и bounded trials |
| [catalogue-renderer.md](catalogue-renderer.md) | Каталог 0.4, полные варианты оформления, новый body и точный oracle-контроль |
| [operations.md](operations.md) | Конфигурация, окружения и наблюдаемость |
| [deployment.md](deployment.md) | Предусловия релиза, серверная установка, HTTPS, проверка и откат |
| [web-017-recovery.md](web-017-recovery.md) | Карта прежнего локального Web 017 и отсутствующих в GitHub файлов |
| [roadmap.md](roadmap.md) | Порядок реализации и критерии выхода |
| [contracts/map.md](contracts/map.md) | Машиночитаемые примеры и схемы |
| [adr/map.md](adr/map.md) | Архитектурные решения |

Вверх: [документация](../map.md). Требования: [продукт](../product/product.md). Текущая предлагаемая реализация — v0.2; backend ещё не создан. [Исследование](../research/map.md) определяет выбор методов и моделей; описанный стек не означает измеренное качество.
