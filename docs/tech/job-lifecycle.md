# Состояния, очередь и восстановление

## Job и stage

State отвечает на вопрос «что можно делать с заданием», stage — «какой алгоритм сейчас выполняется». Их нельзя объединять в десятки конкурирующих статусов. Виды заданий: extract_template и format_article. Этапы первого: preflight, parse, classify, infer_rules, validate_draft. Этапы второго: preflight, parse, classify, plan, render, validate, publish.

| Из | В | Условие |
| --- | --- | --- |
| queued | running | Worker получил lease и зафиксировал attempt |
| running | needs_review | Безопасное продолжение требует конкретных решений |
| needs_review | queued | Все обязательные ответы текущей revision приняты |
| running | queued | Разрешённый инфраструктурный retry, checkpoint сохранён |
| running | completed | Все обязательные проверки пройдены, warnings нет |
| running | completed_with_warnings | Обязательные проверки пройдены, есть warnings |
| queued/running/needs_review | cancel_requested | Принята отмена, отзыв согласия или удаление |
| cancel_requested | cancelled | Worker/координатор подтвердил прекращение и закрыл публикацию |
| queued/running/needs_review | failed | Невосстановимая ошибка или исчерпан срок/лимит |

Терминальные states: completed, completed_with_warnings, failed, cancelled. Из них нет перехода обратно; retry создаёт новый job. `completed` extraction job означает извлечённый черновик, а не approved TemplateVersion.

## Очередь и lease

PostgreSQL — источник истины. В транзакции создания job пишется outbox event; отдельный публикатор доставляет его в Redis. Повторная доставка допустима. Worker получает lease через atomic update по state_version, сохраняет attempt ID и fencing token; сообщение очереди само по себе не разрешает работу.

Начальные операционные настройки: heartbeat 15 s, lease timeout 90 s, до 3 infrastructure attempts. Потеря heartbeat проверяется координатором; requeue выдаёт новый fencing token. Старый worker может закончить внешний HTTP-вызов, но не может публиковать checkpoint или артефакт без актуального token. Не обещать exactly-once LLM billing: provider timeout может означать уже оплаченный запрос.

## Review

Question содержит ID, reason code, target block IDs, варианты действий и blocking flag. Answers хранятся отдельно от исходной классификации. Review revision меняется при изменении вопросов. Частичные ответы сохраняются, но job не ставится в очередь, пока есть обязательные вопросы.

Для роли допустим выбор из vocabulary. Для отсутствующей обязательной части нельзя разрешить «сгенерировать текст»: пользователь загружает исправленный документ или создаёт новую версию шаблона и новый job. Если безопасный ответ внутри текущего запуска невозможен, UI предлагает отмену/новый запуск; нет бесконечного ожидания фиктивного решения.

## Отмена и гонки

Отмена кооперативная: worker проверяет флаг между этапами и после внешнего вызова. Идущий HTTP-запрос не всегда можно остановить и он может быть оплачен. API сразу блокирует новую публикацию, а статус остаётся cancel_requested до подтверждения. Координатор завершает отмену queued/needs_review jobs без ожидания worker.

Publish выполняет compare-and-swap: state=running, актуальные lease/state_version, источник не удалён, нет cancel_requested. Если одновременно приходит cancel/delete, выигрывает один сериализованный переход; после удаления download запрещён даже ранее завершённому job. Неприкреплённые временные артефакты очищаются TTL-задачей.

## Таймауты

Предложение: общий execution deadline 10 минут активной обработки, отдельный timeout LLM 60 s, review expires после 7 суток или срока хранения документа — что наступит раньше. Ожидание человека не входит в execution time, но нельзя удерживать worker/lease на needs_review. Истечение review приводит к failed с `REVIEW_EXPIRED`; пользователь может создать новый запуск при наличии данных.

## Повтор

Replay_plan использует сохранённый validated plan, source/template hashes и совместимый renderer. Reanalyze выполняет новый model run и может отличаться. Если версия движка изменилась, replay проверяет совместимость; иначе возвращает `REPLAY_INCOMPATIBLE`, а не незаметно пересчитывает план. Все новые jobs связаны parent_job_id, имеют отдельные состояния и бюджет.

## Согласование с one-pass и batch

Infrastructure recovery может повторить чистый parser/renderer по checkpoint. Если strict job уже начал внешний вызов и его исход неизвестен, takeover не вызывает модель снова внутри того же trial: состояние завершается с `CALL_OUTCOME_UNKNOWN`. Если сохранён validated ответ, можно продолжить программные этапы без нового вызова. Counter/reservation пишутся до dispatch; crash до/после HTTP не даёт права обещать exactly-once billing.

При review strict trial считается не прошедшим критерий; ручное продолжение сохраняет job history, увеличивает human_edits и снимает strict eligibility. Пользователь может закончить обработку, но она уже не засчитывается как one-pass success. Batch не меняет Job state machine: owns manifests/queue slots и отпускает слот на needs_review. Архив имеет отдельные состояния и не переводит failed job в completed. Полный контракт — [batch-processing](batch-processing.md).
