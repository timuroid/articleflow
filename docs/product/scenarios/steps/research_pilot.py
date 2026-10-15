import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from behave import given, when, then
from docx import Document

from articleflow.docx_engine import (
    NS, compare_content, load_package, lossless_split, lossless_rebuild,
    parse_xml, write_package, xml_bytes,
)
from articleflow.docx_engine import DocumentError
from articleflow.research import one_model_call, plan_schema, finalize_hybrid_trial, validate_model_choice
from articleflow.catalogue import extract_catalogue, render_catalogue
from articleflow.docx_engine import content_fingerprint
from articleflow.planner import aliases, compile_compact


def temporary_workspace(context):
    temp = tempfile.TemporaryDirectory()
    context.add_cleanup(temp.cleanup)
    context.root = Path(temp.name)


@given("синтетический абзац содержит два одинаковых термина")
def repeated_terms(context):
    temporary_workspace(context)
    context.source = context.root / "source.docx"
    doc = Document()
    p = doc.add_paragraph()
    p.add_run("Термин и ")
    p.add_run("Термин").bold = True
    p.add_run(".")
    doc.save(context.source)
    context.package = context.root / "package"
    extract_catalogue(context.source, {"b-000001": "body"}, {"roles": {"body": "Текст"}}, context.package)
    rules = json.loads((context.package / "template/rules.json").read_text())
    oracle = json.loads((context.package / "oracle-plan.json").read_text())
    reverse = {g: {v: k for k, v in items.items()} for g, items in aliases(rules).items()}
    b = oracle["blocks"][0]
    context.response = {"blocks": [{"id": b["id"], "role": "body", "paragraph": reverse["paragraph"][b["paragraph_style"]],
        "character": reverse["character"][b["spans"][0]["style"]],
        "marks": [{"text": "Термин", "occurrence": 2, "style": reverse["character"][b["spans"][1]["style"]]}]}],
        "layout": [], "objects": [], "section": reverse["section"][oracle["section_style"]]}


@when("компактный план выделяет второе вхождение термина")
def compile_repeated_term(context):
    plan = compile_compact(context.package / "template", context.package / "content", context.response)
    context.target = context.root / "candidate.docx"
    render_catalogue(context.package / "template", context.package / "content", plan, context.target)


@then("содержание и выделения собранного документа совпадают")
def repeated_term_matches(context):
    result = compare_content(context.source, context.target)
    assert result["content_exact"] and result["inline_exact"]


@when("компактный план ссылается на отсутствующую цитату")
def compile_missing_quote(context):
    context.response["blocks"][0]["marks"][0]["text"] = "Термин с ошибкой"
    context.error = None
    try:
        compile_compact(context.package / "template", context.package / "content", context.response)
    except DocumentError as exc:
        context.error = str(exc)


@then("компилятор отклоняет цитату без создания документа")
def missing_quote_rejected(context):
    assert context.error == "QUOTE_NOT_FOUND"
    assert not (context.root / "candidate.docx").exists()


@given("создан синтетический DOCX с выделением и верхним индексом")
def source_document(context):
    temporary_workspace(context)
    context.source = context.root / "source.docx"
    doc = Document()
    p = doc.add_paragraph()
    p.add_run("Определение").bold = True
    p.add_run(". Значение 1.25 м")
    p.add_run("2").font.superscript = True
    doc.save(context.source)


@when("исходные свойства разделены и восстановлены без модели")
def reconstruct(context):
    context.manifest = lossless_split(context.source, context.root / "split")
    context.target = context.root / "result.docx"
    lossless_rebuild(context.root / "split", context.target)


@then("содержимое документа совпадает")
def content_matches(context):
    assert compare_content(context.source, context.target)["content_exact"]


@then("контроль не допускается в модельный benchmark")
def not_a_trial(context):
    assert context.manifest["model_calls"] == 0
    assert not context.manifest["eligible_for_model_benchmark"]


@when("из результата удалён верхний индекс без изменения букв")
def remove_superscript(context):
    parts = load_package(context.source)
    tree = parse_xml(parts["word/document.xml"])
    for element in tree.findall(".//w:vertAlign", NS):
        element.getparent().remove(element)
    parts["word/document.xml"] = xml_bytes(tree)
    context.target = context.root / "changed.docx"
    write_package(context.target, parts)


@then("проверка содержимого не проходит")
def content_fails(context):
    result = compare_content(context.source, context.target)
    assert result["checks"]["paragraphs"]
    assert not result["checks"]["protected_vertical"]
    assert not result["content_exact"]


@given("тестовый провайдер возвращает невалидный JSON")
def bad_provider(context):
    temporary_workspace(context)
    context.secret = "synthetic-not-a-real-key"


@when("выполняется одна попытка планирования")
def request_once(context):
    with patch.dict("os.environ", {"OPENROUTER_API_KEY": context.secret}), patch("articleflow.research.httpx.Client") as cls:
        client = cls.return_value.__enter__.return_value
        client.post.return_value.status_code = 200
        client.post.return_value.json.return_value = {"usage": {"cost": 0.01}, "choices": [{"finish_reason": "stop", "message": {"content": "not json"}}]}
        context.meta = one_model_call(model="synthetic", messages=[], schema=plan_schema(["body"]), pricing={"prompt": "0.000001", "completion": "0.000001"}, key_file=None, run_dir=context.root / "run", ledger=context.root / "ledger.json", cap_usd="1")
        context.call_count = client.post.call_count


@then("провайдер вызван ровно один раз без repair")
def no_retry(context):
    assert context.call_count == 1
    assert context.meta["api_attempts"] == 1
    assert context.meta["repair_calls"] == 0
    assert context.meta["status"] == "invalid_model_output"


@then("секрет отсутствует в сохранённых артефактах")
def secret_not_saved(context):
    assert all(context.secret not in path.read_text() for path in context.root.rglob("*.json"))


@given("гибридный renderer сохранил исходную геометрию")
def hybrid(context):
    context.row = {"render_protocol": "I1-text-to-model/I3-object-layout-to-renderer"}


@when("все измеренные проверки совпадения успешны")
def successful_checks(context):
    context.row.update(content_exact=True, inline_exact=True, pixel_exact=True, roles_exact=True)
    finalize_hybrid_trial(context.row)


@then("наблюдаемое совпадение отмечено отдельно")
def observed_match(context):
    assert context.row["observed_full_match"]


@then("строгий I1 не пройден")
def strict_not_passed(context):
    assert not context.row["eligible_for_strict_I1"]
    assert not context.row["strict_I1_pass"]


@given("подтверждён выпуск модели 30 июня 2026 года")
def old_release(context):
    context.registry = {"release_after": "2026-06-30", "models": [{"id": "synthetic", "release_date": "2026-06-30", "source_type": "official_release_log", "source": "https://example.org/releases"}]}


@when("проверяется допуск с границей после июня 2026 года")
def check_release(context):
    context.error = None
    with patch("articleflow.research.httpx.Client") as client:
        try:
            validate_model_choice("synthetic", context.registry)
        except DocumentError as exc:
            context.error = str(exc)
        context.http_client_created = client.called


@then("модель отклоняется до платного запроса")
def old_release_rejected(context):
    assert context.error == "MODEL_TOO_OLD"
    assert not context.http_client_created


@given("извлечены отдельные каталог, содержимое и контрольный план")
def extract_catalogue_fixture(context):
    context.package = context.root / "catalogue"
    extract_catalogue(context.source, {"b-000001": "body"}, {"roles": {"body": "Синтетический абзац"}}, context.package)
    context.plan = json.loads((context.package / "oracle-plan.json").read_text())
    context.expected_payload = content_fingerprint(context.source)


@when("исходный DOCX удалён и документ собран по каталогу")
def assemble_without_source(context):
    context.source.unlink()
    context.target = context.root / "rebuilt.docx"
    context.record = render_catalogue(context.package / "template", context.package / "content", context.plan, context.target)


@then("содержание совпадает с сохранённым отпечатком")
def assembled_payload(context):
    assert content_fingerprint(context.target) == context.expected_payload


@then("сборка не объявляется успехом модели")
def oracle_not_model(context):
    assert context.record["model_calls"] == 0
    assert context.record["plan_provenance"] == "source_oracle"
    assert not context.record["strict_I1_pass"]


@when("исследователь читает правила каталога")
def read_catalogue_rules(context):
    context.rules_text = (context.package / "template/rules.json").read_text()
    context.rules = json.loads(context.rules_text)


@then("в правилах нет текста статьи и идентификаторов её блоков")
def no_specimen_assignments(context):
    assert "Определение" not in context.rules_text
    assert "b-000001" not in context.rules_text
    assert "blocks" not in context.rules


@then("роли содержат только допустимые варианты свойств")
def catalogue_alternatives(context):
    role = context.rules["roles"]["body"]
    assert role["paragraph_styles"]
    assert role["character_styles"]
    assert set(role["paragraph_styles"]) <= set(context.rules["styles"]["paragraph"])


@when("план ссылается на неизвестный вариант абзаца")
def bad_paragraph_variant(context):
    context.plan["blocks"][0]["paragraph_style"] = "not-in-catalogue"
    context.target = context.root / "bad-result.docx"
    context.error = None
    try:
        render_catalogue(context.package / "template", context.package / "content", context.plan, context.target)
    except DocumentError as exc:
        context.error = str(exc)


@then("сборщик отклоняет план до создания DOCX")
def no_invalid_docx(context):
    assert context.error == "PLAN_STYLE_ROLE"
    assert not context.target.exists()
