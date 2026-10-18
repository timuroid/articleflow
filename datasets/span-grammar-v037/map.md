# Карта корпуса 037

- [Описание, протоколы и ограничения](README.md)
- [Декларативный ground truth](ground-truth.json)
- [Манифест с SHA-256 и диапазонами](manifest.json)
- `reference-01.docx`, `reference-02.docx`, `reference-03.docx` — обучающие эталоны.
- `heldout-target.docx` — независимая целевая верстка.
- `heldout-input-i2.docx`, `heldout-input-i1.docx` — два испорченных входа.
- `heldout-hard-target.docx` — второй контроль с 56 абзацами, 4 разделами и 2 рисунками.
- `heldout-hard-input-i1.docx` — его испорченный вход без надёжной исходной типографики.
- `negative-ambiguous.docx` — неоднозначный отрицательный контроль.
- Генератор: [build_span_grammar037.py](../../scripts/build_span_grammar037.py).
- Проверки: [test_span_grammar037.py](../../tests/test_span_grammar037.py).
