# LLM: подготовка шаблона и применение

## Два независимых профиля

`template_extractor` — сильная модель, предпочтительно подходящая актуальная OpenAI-модель, либо исследователь с её помощью. Допустимы безопасные inspect/compile/render/check tools и ограниченный feedback loop. `article_planner` — кандидат небольшой модели, который возвращает DocumentPlan новой статьи. У профилей отдельные model/provider IDs, prompts, permissions, budgets и usage. Конкретные model IDs пока не выбраны и не проверены.

Адаптер OpenAI-compatible API допускает прямой API или OpenRouter. Совместимость endpoint не доказывает одинаковую поддержку JSON Schema, vision, reasoning или retention. Фиксируется фактический model snapshot; mutable alias без snapshot — ограничение воспроизводимости.

## Ответ planner

Рекомендуемый кандидат G-PLAN возвращает роли блоков, inline spans, object bindings и label intents по [DocumentPlan](document-plan.md). Научный текст остаётся в исходных блоках, binary/base64 DOCX собирает код. G-FULL с повторной генерацией всего размеченного текста допускается как отдельный research method с тем же content validator. [Classification schema v0.1](contracts/classification.schema.json) остаётся ограниченным baseline ролей абзацев, недостаточным для полного v0.2.

Prompt содержит IDs, текст и признаки выбранного input protocol, compiled template rules и схему. Golden pages, template evidence, секреты и произвольные endpoints не передаются student. Инструкции внутри статьи — данные. Краткое обоснование допустимо, скрытые рассуждения не запрашиваются.

## Режимы

| Profile | Ограничение | Как учитывать |
| --- | --- | --- |
| strict_one_pass | Один API attempt/ответ на целую статью, без repair/tools/chunks | Ошибка или review не являются строгим успехом |
| bounded_loop | До 3 model calls включая исходный и repair; до 4 HTTP attempts суммарно | Считать каждый вызов и причину дополнительного шага |
| chunked | Несколько явно заявленных частей и merge validation | Отдельный метод, не one-pass |
| replay_plan | Ноль вызовов, сохранённый validated plan | Повтор renderer, не fresh trial |

В strict SDK retries выключены. Timeout, 429, invalid JSON и truncation завершают неуспешную попытку. Пользовательский retry создаёт новый job и отдельную строку измерений. Bounded loop допускает transient retries с Retry-After/backoff в общем лимите; auth/capability ошибки не повторяются. Скрытое переключение режима или провайдера запрещено. Reasoning tokens учитываются в стоимости и времени.

## Контекст, images и feedback

До вызова проверить input tokens + output bound + reasoning allowance. Strict не делит статью на chunks: переполнение даёт `CONTEXT_OVERFLOW`. Для chunked фиксируются границы, target IDs, read-only overlap и merge policy. Число calls сохраняется, одинаковые блоки из overlap не получают несколько противоречивых ролей.

Вход I0/I1/I2/I3 определяется [бенчмарком](../research/benchmark.md). Обычно student видит asset markers/metadata, а renderer получает bytes. Мультимодальные страницы образца допустимы extractor при разрешённой обработке и считаются отдельным методом. Нельзя сообщать text-only результат при незаявленном vision input.

Schema validator проверяет форму; application validator — IDs, offsets, coverage, conflicts, assets и labels. Модель не решает, прошла ли content integrity. В G-LOOP ей доступны только ошибки схемы/правил и разрешённый исходник, без golden output тестовой статьи. E-LOOP может смотреть образец; начальный предел 5 model calls на шаблон, денежный cap и остановка при отсутствии улучшения. Его compiled rules проверяются на запоминание экземпляра.

## Бюджет и данные

Перед запросом атомарно резервируется верхняя оценка стоимости по тарифу и token limits. Лимиты действуют на call, job, batch и workspace, включая параллельность и retries. Неизвестный тариф блокирует платный запуск до настройки контроля. Timeout означает usage=unknown; резерв не обнуляется до сверки/консервативного списания.

Template preparation, application, render/validation и review учитываются отдельно. Цена принятого документа включает failed attempts; амортизация шаблона показывается при N=100/200/300. Prompt caching провайдера фиксируется; application response cache выключен в fresh benchmark.

Temperature=0 не гарантирует одинаковый ответ. Replay использует сохранённый plan, fresh trials вызывают модель заново. Cache key включает workspace, input protocol, hashes, prompt/schema/model/settings. Межпространственный cache запрещён. Payloads хранятся защищённо с retention документа; в логи не попадают scientific text и Authorization. API-ключ доступен только backend/gateway.
