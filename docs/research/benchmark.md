# Бенчмарк: восстановление и перенос

## Протоколы входа

| ID | Что получает application model/renderer | Что намеренно отсутствует |
| --- | --- | --- |
| I0 text_only | Unicode-текст с фиксированными границами абзацев и IDs; TemplatePackage | Шрифты, inline emphasis, геометрия, изображения, OMML, структура сложных таблиц |
| I1 text_assets | Текст, block IDs, topology таблиц, markers и refs исходных изображений/OMML, исходные aspect ratios | Target formatting, границы жирных/курсивных spans, исходные размеры размещения и page breaks |
| I2 semantic_content | I1 + сохранённые/редакторские semantic spans, например term/emphasis/superscript | Target visual style: кегль, интервалы, поля, жирность термина по шаблону |
| I3 source_docx | Исходная статья, её наблюдаемые стили и объекты | Целевой DOCX новой статьи; профиль нужен для production baseline |

I0 не может восстановить отсутствующий рисунок или произвольное авторское выделение из ничего. Для full-document pixel trial это `not_reconstructible` или фактический fail с причиной; такой случай остаётся в исходном знаменателе корпуса. Нельзя выдать результат I1/I2 за text-only. Для отдельного текстового подкорпуса I0 остаётся полезным тестом. Конвертер обязан записывать discarded feature inventory.

Asset sidecar I1 хранит байты изображения и content ID, а не его исходные x/y, crop/width или готовую картинку страницы. OMML сохраняется как исходный научный объект; это явно дополнительная информация сверх текста. Семантические annotations I2 получаются из явно отмеченного источника; oracle annotation с эталона считается отдельным верхним baseline, не бесплатной автоматической функцией.

## Два независимых набора испытаний

**R: reconstruction.** Оформленная статья является источником шаблона и golden output. После фиксации шаблона из неё создаётся stripped input выбранного протокола. Renderer строит свежий документ (`rebuild_neutral`); никакие исходные pPr/rPr/sectPr и готовые страницы не доступны student/renderer, кроме явно разрешённых правил TemplatePackage. Нельзя просто открыть образец и сохранить его.

**T: transfer.** Новые статьи не использовались при настройке. Их golden outputs создаются редактором по утверждённым правилам. Дубликаты и близкие версии одной статьи остаются в одном split. Шаблон знает правила журнала; runtime examples должны быть синтетическими или из development split. Наличие разрешённых образцов в подготовке шаблона фиксируется, но это не заменяет transfer test.

Предлагаемый пилот: 3 шаблона, ≥20 документов, ≥5 unseen статей; для серьёзной оценки редких конструкций корпус потребуется расширить. Реконструкция одного образца 10 раз — отдельная ступень, даже если перенос пока не начат.

## Защита от утечки

Golden DOCX, pixels, per-document target spans и target field values лежат в evaluator storage. Student имеет доступ только к compiled runtime package и выбранному входу. Evidence образца доступен extractor/редактору, но не включается автоматически в prompt student. Compile audit запрещает article-specific цитаты, координаты/номера блоков образца и таблицу всех выделенных слов.

Исключение: подтверждённые служебные literals («Аннотация», «Рисунок», разделитель) — часть шаблона. Их allowlist видна в manifest. Научный термин «энтропия» из одного образца не становится глобальным словарём обязательных выделений. Glossary допустим только как отдельное подтверждённое общее правило и отдельная экспериментальная переменная.

## Фиксация среды визуализации

Оба DOCX рендерятся одним и тем же движком и его версией: например, согласованный Word в отдельной Windows-среде или отдельно заявленный LibreOffice. Фиксируются ОС, build движка, fonts и их hashes, locale, timezone, бумага, field update policy, hyphenation, printer profile при влиянии и растеризатор PDF. Предложение: PNG RGB, 144 DPI, одинаковый color profile, одинаковые размеры canvas.

Перед LLM-прогонами один golden DOCX рендерится 10 раз в чистых сессиях. Если пиксели отличаются, exact benchmark в этой среде считается unstable и сначала исправляется стенд. Даты/поля фиксируются общей политикой до всех прогонов. Нельзя динамически маскировать разные места только в неудачных результатах.

## Метрики и строгий gate

1. **Валидность:** схема ответа, существующие refs, полное покрытие, отсутствие invented content и успешное открытие DOCX без repair.
2. **Содержание:** текст по блокам, таблицы, OMML, image bytes, anchors, URI, semantic markers. Совпадение общего числа слов недостаточно.
3. **Правила:** paragraph/character styles, inline spans (границы + роль), figure size/alignment, caption associations, служебные labels и field definitions.
4. **Пиксели:** одинаковое число страниц и размеры каждой страницы; exact pixel equality по всем RGB-каналам. `pixel_exact=true` только при нуле отличающихся пикселей на всех страницах.
5. **Диагностика:** ratio differing pixels, MAE, SSIM при необходимости, bbox differences и diff overlays. Никакого автоматического alignment/warp/crop для exact gate. Выровненное сравнение можно публиковать только как отдельную диагностику.
6. **Ресурсы:** model/API attempts, input/output/reasoning tokens, cache usage, actual/unknown cost, stage latency, p50/p95, review time и total batch wall time.

`strict_pass = schema_valid AND content_exact AND rules_pass AND pixel_exact AND api_attempts=1 AND model_calls=1 AND repair_calls=0 AND human_edits=0 AND application_cache_hit=false`.

Для G-RULES/oracle baseline с нулём model calls эта формула не используется как оценка student: отдельно записывается quality_pass по первым четырём проверкам. Нулевое число вызовов не превращает контрольный renderer в победившую «маленькую модель».

Проверка содержания сравнивается с контрактом конкретного протокола. Для I1 научные символы должны совпасть, а новые target spans сравниваются с golden отдельно; нельзя объявлять намеренное добавление term style порчей текста. Исходные semantic spans I2 не могут исчезнуть без разрешённого semantic mapping. Generated labels допускаются только из allowlist с записью provenance, никогда как научный payload.

## Десять повторов и выбор модели

Для каждой ячейки `(document, template hash, extractor, input protocol, application method, model snapshot, renderer profile)` выполняются 10 fresh calls. Каждый run сохраняет artifacts и метрики; failures, timeouts, truncation и context overflow не выкидываются. Application response cache отключён. Retry никогда не заменяет исходную неудачу в таблице.

10/10 строгих совпадений на reconstruction даёт право проверить более дешёвого кандидата и перейти к transfer, но не заявлять универсальную надёжность. Transfer имеет свой заранее замороженный gate; исходный исследовательский запрос — тоже 10/10 strict на каждой проверяемой статье. Если нужен иной практический gate, он фиксируется до просмотра test results и публикуется отдельно.

Если сильная модель не проходит, проверить oracle plan: если он тоже не проходит, менять renderer/template, а не бесконечно перебирать модели. Если oracle проходит, исследовать ошибки входного протокола, выбора roles/spans и output limits. Улучшение prompts на тестовой статье переводит её в development; для честной финальной оценки нужен новый holdout.

## Артефакты испытания

Experiment manifest содержит corpus/version, splits, model/provider IDs, метод, лимиты, seed/settings и render profile. Run хранит stripped input hash, package hash, prompt hash, output plan, call ledger, DOCX, raster pages, diff, metrics и error code. Приватные артефакты вне Git; в [results.csv](results.csv) публикуются только безопасные идентификаторы и метрики. Сейчас таблица пуста намеренно.
