Feature: Честное исследование методов и небольших моделей

  @SC-039 @PRD-014
  Scenario: Некорректный ответ не исправляется скрытым вызовом
    Given выбран профиль "strict_one_pass"
    When единственный ответ модели не проходит JSON Schema
    Then прогон считается неуспешным
    And repair и повтор SDK не выполняются
    And фактический один API attempt записывается в результат

  @SC-040 @PRD-014
  Scenario: Большой документ не разбивается скрыто
    Given выбран профиль "strict_one_pass"
    And статья с шаблоном и запасом ответа превышает context limit
    When выполняется preflight токенов
    Then регистрируется код "CONTEXT_OVERFLOW"
    And модель не вызывается
    And прогон не исключается из отчёта

  @SC-041 @PRD-014
  Scenario: Успех после исправлений имеет отдельный режим
    Given выбран профиль "bounded_loop"
    And первый ответ модели невалиден
    When второй ответ исправляет ошибку и проходит проверки
    Then отчёт содержит два model calls и их общую стоимость
    And результат не называется strict one-pass success

  @SC-042 @PRD-015
  Scenario: Исходное оформление недоступно в reconstruction trial
    Given подготовлены golden DOCX и нейтральный вход I1
    When запускается G-PLAN с renderer "rebuild_neutral"
    Then student не получает golden pixels и target spans
    And renderer не читает pPr, rPr и sectPr исходного golden
    And доступны только разрешённые rules и asset sidecar

  @SC-043 @PRD-015
  Scenario: Десять прогонов не заменяются кэшированным ответом
    Given конфигурация эксперимента заморожена
    When выполняются 10 trials применения
    Then application response cache выключен
    And отчёт содержит все 10 исходов включая ошибки
    And успех 10 из 10 подписан как результат данной конфигурации
    And не заявляется гарантированная точность на любых статьях

  @SC-044 @PRD-015
  Scenario: Небольшое визуальное различие не считается pixel exact
    Given среда рендера стабильна и размеры страниц совпадают
    And результат отличается от golden хотя бы одним пикселем
    When evaluator сравнивает страницы
    Then "pixel_exact" равно false
    And высокий SSIM не меняет strict_pass на true

  @SC-045 @PRD-015
  Scenario: Новая статья проверяется по независимому эталону
    Given статья не использовалась при настройке шаблона и prompt
    And редактор подготовил её целевой DOCX независимо
    When выполняется transfer trial
    Then evaluator сравнивает результат с целевым DOCX этой статьи
    And golden не передаётся application loop
    And результат записывается отдельно от reconstruction

  @SC-053 @PRD-017
  Scenario: Методы извлечения сравниваются при одинаковом применении
    Given подготовлены пакеты методами "E-MANUAL" и "E-LOOP"
    And input protocol, application method, model и renderer зафиксированы
    When исследователь запускает сравнение
    Then каждый пакет имеет отдельный hash и provenance
    And стоимость подготовки учитывается отдельно от применения
    And недостающий результат не заменяется предполагаемым успехом
