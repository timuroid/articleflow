# Планирование и применение оформления

## Document IR

Внутреннее представление (`DocumentIR`) не заменяет исходный OOXML. Оно индексирует parts и ordered blocks: paragraph, table, image anchor, formula, note, field. Блок содержит ID, part/path, raw subtree reference, content fingerprint, run spans, effective style, role candidates и dependencies. Вложенность таблиц/ячеек и диапазоны bookmarks/comments сохраняются, а не превращаются в плоский текст.

Слой scientific payload включает последовательности Unicode-символов, текст таблиц и заметок, OMML, media bytes, hyperlink targets, field instructions и семантические inline-маркеры. Свойства, влияющие на смысл (super/subscript, strike, скрытый текст), нельзя сбрасывать вместе с косметическим оформлением.

## Mapping и план

`RoleAssignment` сопоставляет существующий block ID с одним role ID, evidence и происхождением решения. Неизвестные IDs и роли отклоняются. Один блок не должен получать несовместимые роли; составной абзац, например «Ключевые слова: …», при необходимости размечается span-ами без изменения текста.

Операция `FormattingOperation` включает `operation_id`, allowlisted `kind`, `target_block_ids`, `rule_id`, `expected_before_hash`, `properties`, `requires_confirmation`. План хранит source hash, template hash, mapping hash и renderer version. Перед исполнением проверяются все hashes и зависимости.

Разрешённые виды v0.2: `set_paragraph_style`, `set_paragraph_properties`, `set_run_font_defaults`, `set_character_style_span`, `bind_caption`, `insert_approved_label`, `set_section_geometry`, `set_table_properties`, `resize_inline_image`. Они компилируются из [DocumentPlan](document-plan.md) и [TemplatePackage](template-package.md). `reorder_blocks` включается после реализации проверки ссылок и явного решения редактора; иначе review. Вставка научного текста, произвольное удаление, исполнение кода и загрузка URL запрещены. Label вставляется только из allowlist с provenance.

## OOXML-преобразования

1. Создать независимую рабочую копию source package.
2. Сформировать namespace стилей приложения, например `AF_<version>_<role>`. При совпадении style ID сравнить содержимое; конфликт решать новым ID и mapping, а не перезаписью чужого стиля.
3. Сначала обновить definitions стилей, затем ссылки на них в параграфах. Стили рисунков/таблиц не создавать как обычные paragraph styles.
4. Удалять только те direct properties, которые перекрывают конкретное целевое правило и не несут семантики. Например, менять кегль по правилу можно, удалять `w:vertAlign` у индекса нельзя.
5. Сохранить runs и их текст без слияния, способного повредить пробелы, xml:space, bookmarks, fields и ссылочные диапазоны.
6. Применить геометрию секции с учётом ширины содержимого. Не переносить sectPr вслепую из образца: там могут быть relationships на его колонтитулы.
7. Сохранить существующие части и relationships. Если добавление требуется, выделить уникальный rId в пределах owning part и обновить все зависимые записи.
8. Пересобрать ZIP в новый артефакт с корректными content types. Проверить его независимым чтением.

По умолчанию номера списков, подписи «Рисунок 1» и инструкции REF/SEQ не переписываются. Обновление cached field results зависит от Word, поэтому несогласованность или невозможность проверить актуальность оформляется как warning либо blocker по типу зависимости.

## Ограничения

Научный текст и медиа образца не участвуют в рендеринге статьи. Шаблон поставляет правила и подтверждённые служебные literals, например «Ключевые слова:». Сборка «открыть образец и заменить весь текст» не допускается. В `patch_source` копируется новая исходная статья, в benchmark `rebuild_neutral` создаётся свежий пакет без target formatting.

Операции применяются атомарно на уровне нового пакета. При ошибке частично собранный DOCX остаётся временным диагностическим объектом, не пользовательским результатом. Повтор с тем же планом должен дать одинаковые fingerprints научного содержания и эффективного оформления. ZIP timestamps и generated metadata исключаются из такого сравнения.
