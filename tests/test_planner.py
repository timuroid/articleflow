import copy
import json
import unittest
from unittest.mock import patch

import test_catalogue as fixtures
from articleflow.catalogue import render_catalogue
from articleflow.docx_engine import DocumentError, compare_content, load_package, parse_xml, xml_bytes, write_package, NS
from articleflow.planner import aliases, model_view, compact_messages, compile_compact, quote_range, score_choices
from articleflow.planner_research import run_catalogue_trials


def oracle_response(template, content, plan):
    """Test-only encoder; real model never receives source assignments."""
    reverse = {g: {v: k for k, v in values.items()} for g, values in aliases(template).items()}
    blocks = []
    for b, source in zip(plan["blocks"], content["blocks"]):
        base = b["spans"][0]["style"] if b["spans"] else None
        marks = []
        for span in b["spans"]:
            if span["style"] == base:
                continue
            quote = source["text"][span["start"]:span["end"]]
            occurrence = sum(source["text"].startswith(quote, i) for i in range(span["start"] + 1))
            marks.append({"text": quote, "occurrence": occurrence, "style": reverse["character"][span["style"]]})
        blocks.append({"id": b["id"], "role": b["role"], "paragraph": reverse["paragraph"][b["paragraph_style"]], "character": reverse["character"].get(base), "marks": marks})
    return {"blocks": blocks, "layout": [{"id": x["id"], "style": reverse[x["kind"]][x["style"]]} for x in plan["layout"]],
        "objects": [{"id": x["id"], "drawing": reverse["drawing"][x["drawing_style"]], "character": reverse["character"][x["run_style"]]} for x in plan["objects"]],
        "section": reverse["section"][plan["section_style"]]}


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CatalogueTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.response = oracle_response(f.template, f.content, f.plan)

    def compile(self, response=None):
        f = self.fixture
        return compile_compact(f.package / "template", f.package / "content", response or self.response)

    def test_compact_plan_preserves_mixed_text_objects_and_formula(self):
        f = self.fixture
        plan = self.compile()
        target = f.root / "compiled.docx"
        render_catalogue(f.package / "template", f.package / "content", plan, target)
        self.assertTrue(compare_content(f.source, target)["content_exact"])
        scores = score_choices(plan, f.plan, f.content)
        self.assertEqual(scores["paragraph_style_correct"], scores["paragraph_style_total"])
        self.assertEqual(scores["character_style_correct"], scores["character_style_total"])
        self.assertEqual(plan["provenance"], "model_compact")

    def test_prompt_and_compiler_do_not_need_oracle_or_source(self):
        f = self.fixture
        f.source.unlink()
        (f.package / "oracle-plan.json").unlink()
        (f.package / "manifest.json").unlink()
        view = model_view(f.package / "template", f.package / "content")
        self.assertEqual(view["blocks"][0]["text"], f.content["blocks"][0]["text"])
        self.assertNotIn("paragraph_style", json.dumps(view))
        self.assertNotIn("spans", view["blocks"][0])
        self.assertIn("untrusted", compact_messages(view)[0]["content"])
        self.compile()

    def test_aliases_do_not_depend_on_catalogue_insertion_order(self):
        t = copy.deepcopy(self.fixture.template)
        for group in t["styles"]:
            t["styles"][group] = dict(reversed(list(t["styles"][group].items())))
        self.assertEqual(aliases(t), aliases(self.fixture.template))

    def test_same_model_input_can_have_different_source_style_assignments(self):
        f = self.fixture
        parts = load_package(f.source)
        root = parse_xml(parts["word/document.xml"])
        paragraphs = root.findall(".//w:body/w:p", NS)
        a, b = paragraphs[0], paragraphs[2]
        ap, bp = a.find("w:pPr", NS), b.find("w:pPr", NS)
        a.remove(ap)
        b.remove(bp)
        a.insert(0, bp)
        b.insert(0, ap)
        parts["word/document.xml"] = xml_bytes(root)
        alternate = f.root / "alternate.docx"
        write_package(alternate, parts)
        other = f.root / "alternate"
        f.extract(alternate, other)
        self.assertEqual(model_view(f.package / "template", f.package / "content"), model_view(other / "template", other / "content"))
        alternate_plan = json.loads((other / "oracle-plan.json").read_text())
        self.assertNotEqual(f.plan["blocks"][0]["paragraph_style"], alternate_plan["blocks"][0]["paragraph_style"])

    def test_exact_unicode_and_overlapping_quote_occurrences(self):
        self.assertEqual(quote_range("ααα 🙂e\u0301", "αα", 2), (1, 3))
        self.assertEqual(quote_range("ααα 🙂e\u0301", "🙂e\u0301", 1), (4, 7))
        with self.assertRaisesRegex(DocumentError, "QUOTE_NOT_FOUND"):
            quote_range("e\u0301", "é", 1)

    def test_invented_or_overlapping_marks_are_rejected(self):
        r = copy.deepcopy(self.response)
        r["blocks"][0]["marks"][0]["text"] = "Nonexistent replacement text"
        with self.assertRaisesRegex(DocumentError, "QUOTE_NOT_FOUND"):
            self.compile(r)
        r = copy.deepcopy(self.response)
        r["blocks"][0]["marks"] *= 2
        with self.assertRaisesRegex(DocumentError, "QUOTE_OVERLAP"):
            self.compile(r)

    def test_coverage_unknown_styles_and_new_text_are_rejected(self):
        r = copy.deepcopy(self.response)
        r["blocks"].reverse()
        with self.assertRaisesRegex(DocumentError, "COMPACT_BLOCK_ORDER_COVERAGE"):
            self.compile(r)
        r = copy.deepcopy(self.response)
        r["blocks"][0]["paragraph"] = "p999999"
        with self.assertRaisesRegex(DocumentError, "COMPACT_SCHEMA"):
            self.compile(r)
        r = copy.deepcopy(self.response)
        r["blocks"][0]["replacement_text"] = "changed"
        with self.assertRaisesRegex(DocumentError, "COMPACT_SCHEMA"):
            self.compile(r)

    def test_invalid_response_is_not_repaired_or_replaced_by_oracle(self):
        f = self.fixture
        ledger = f.root / "ledger.json"
        ledger.write_text("[]")
        registry, catalogue = f.root / "registry.json", f.root / "models.json"
        registry.write_text(json.dumps({"release_after": "2026-06-30", "models": [{"id": "test/model", "release_date": "2026-08-01", "source_type": "official_release_log", "source": "https://example.org/releases"}]}))
        catalogue.write_text(json.dumps({"data": [{"id": "test/model", "context_length": 1000000, "supported_parameters": ["reasoning", "structured_outputs"], "pricing": {"prompt": "0.000002", "completion": "0.00001"}}]}))
        r = copy.deepcopy(self.response)
        r["blocks"][0]["marks"][0]["text"] = "invented"
        def fake(**kwargs):
            p = kwargs["run_dir"]
            p.mkdir()
            (p / "plan.json").write_text(json.dumps(r))
            return {"status": "schema_valid", "cost_usd": "0", "api_attempts": 1}
        with patch("articleflow.planner_research.one_model_call", side_effect=fake) as call:
            rows = run_catalogue_trials(template_dir=f.package / "template", content_dir=f.package / "content", oracle_path=f.root / "DOES_NOT_EXIST", source=f.source, golden_pdf=f.root / "NO_GOLDEN", model="test/model", catalogue=catalogue, registry=registry, output=f.root / "trials", ledger=ledger, key_file=None)
            original_messages = call.call_args.kwargs["messages"]
            view = model_view(f.package / "template", f.package / "content")
            reordered = dict(reversed(list(view.items())))
            with patch("articleflow.planner_research.model_view", return_value=reordered):
                run_catalogue_trials(template_dir=f.package / "template", content_dir=f.package / "content", oracle_path=f.root / "DOES_NOT_EXIST", source=f.source, golden_pdf=f.root / "NO_GOLDEN", model="test/model", catalogue=catalogue, registry=registry, output=f.root / "trials", ledger=ledger, key_file=None, first=2)
            self.assertEqual(call.call_args.kwargs["messages"], original_messages)
        self.assertEqual(call.call_count, 2)
        self.assertEqual(rows[0]["error_code"], "QUOTE_NOT_FOUND")
        self.assertFalse(rows[0]["artifact_accepted"])
