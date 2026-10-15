# Пакетная обработка сотен статей

## Контракт продукта

Batch группирует независимые format_article jobs одной версии шаблона и application profile. Целевой путь — загрузить 100–300 DOCX, обрабатывать по очереди, получать готовые файлы и архив. Предлагаемый начальный предел — 300 файлов и 2 GiB суммарно, при сохранении ограничения 25 MiB на файл; точные пределы подтверждаются нагрузочным тестом. Входной ZIP не нужен для MVP: браузер загружает файлы по отдельности. Выходной ZIP обязателен.

BatchItem сохраняет client item ID, исходное имя, upload/document ID, ordinal, current job ID и историю retries. Одинаковые имена различаются item IDs; одинаковые hashes не объединяются без явного product rule. Upload failure имеет собственное состояние и остаётся в manifest, даже если Document не создан.

## Создание и согласие

UI регистрирует список элементов, загружает их ограниченно параллельно и показывает результат каждого. Состояние Batch `draft` допускает повтор upload только проблемных элементов. Seal/start фиксирует item set, template hash, application profile, лимиты и явное согласие на внешний анализ каждого готового document hash. Одно UI-подтверждение создаёт отдельные ProcessingConsent records; изменение provider config/добавление документа не наследует разрешение молча.

Невалидные элементы можно оставить в пакете с ошибкой и начать остальные. Для готовых элементов jobs/outbox создаются идемпотентно; при большом пакете материализация идёт порциями по sealed manifest с unique(batch_id,item_id,run_generation), чтобы рестарт не породил дубликаты. Неподготовленный частичный manifest не запускается.

## Очередь и ошибки

Начальная concurrency — 1 активный article job на batch. Job в needs_review освобождает execution slot, очередь переходит к следующему; ожидающий человека документ не тормозит остальные. Для нескольких batch используется fairness между workspace и ограничение общей concurrency. Более высокая concurrency — явная настройка после проверки расходов и памяти.

Failed/cancelled item не отменяет другие. Исчерпание общего бюджета переводит batch в `paused_budget`, новые вызовы не стартуют, уже зарезервированные выполняются в рамках резерва. Таймауты и retries соответствуют application profile; `strict_one_pass` не получает скрытого repair или transport retry. Отмена batch прекращает новые jobs и запрашивает cancel незавершённых; готовые остаются доступными до удаления.

## Состояния batch

| State | Значение |
| --- | --- |
| draft | Список/загрузки ещё формируются |
| running | Есть queued/running/cancel_requested jobs или идёт материализация |
| paused_budget | Новые платные вызовы остановлены общим лимитом |
| needs_review | Нет активных задач, есть нерешённые вопросы |
| completed | Все items имеют успешный DOCX, возможны явно показанные warnings |
| completed_with_errors | Все items терминальны, хотя бы один rejected/failed/cancelled |
| cancel_requested | Отмена принята, завершаются остановки jobs |
| cancelled | Batch отменён; частичные готовые результаты могут существовать |

Счётчики derived из items, не из количества сообщений брокера. Все rejected без jobs — completed_with_errors. Повтор failed items создаёт новую batch run generation; сохраняются прошлый sealed manifest и export versions. Это не меняет терминальные Job records.

## ZIP и manifest

Экспорт — отдельная асинхронная операция, не LLM job. По запросу фиксируется snapshot выбранной run generation: список item states, artifact IDs/hashes и export revision. Во время продолжающегося batch допускается `partial=true`. Позже создаётся новый export; старый файл не переписывается.

Архив содержит `documents/<ordinal>-<safe-stem>.docx`, отчёты для доступных результатов и `manifest.json`/`summary.csv` для всех items. Manifest включает item ID, исходное безопасное имя, статус, output path/hash или reason code, template version, method/profile и timestamps. Failed/unchecked integrity DOCX в архив не включается. Отсутствие файла не выдаётся за успешную обработку.

Пример одинаковых входных имён: `0001-article.docx` и `0002-article.docx`. Имена нормализуются, пути не содержат `..`, absolute paths или опасных separators. Writer потоковый/на диске с bounded memory, включает ZIP64 при необходимости и проверяет checksum каждого читаемого объекта. При сбое assembly экспорт остаётся failed, частичный ZIP не выдаётся.

Download batch export повторно проверяет workspace, retention и tombstones всех включённых документов. Удаление любого включённого source/artifact немедленно отзывает весь такой export и ставит его на cleanup; иначе архив обходил бы индивидуальное удаление. Следующий экспорт исключает удалённые данные и отражает это в manifest.

## Измерения

Считать throughput, queue wait, per-item latency, total wall time, model attempts, cost (включая failures), archive duration/size и долю требующих review. Цель «один вызов на документ» проверяется для каждого item, не делением общего числа вызовов на успешные файлы. Единоразовая стоимость template отдельно амортизируется на 100/200/300 статей.
