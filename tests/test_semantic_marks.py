import copy
import json
import unittest

import test_catalogue as fixtures
from articleflow.catalogue import render_catalogue
from articleflow.context_rules import transform_plan
from articleflow.docx_engine import DocumentError, compare_content
from articleflow.semantic_marks import extract_marks, expand_mark_styles, apply_marks


class SemanticMarkTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.CatalogueTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.payload = extract_marks(self.f.source, self.f.package / "content/content.json")

    def test_preserves_all_flags_after_source_removed_and_model_marks_erased(self):
        f = self.f
        source = f.source.read_bytes()
        plan = copy.deepcopy(f.plan)
        normal = f.template["roles"]["body"]["character_styles"][0]
        for block in plan["blocks"]:
            for span in block["spans"]:
                span["style"] = normal
        f.source.unlink()
        (f.package / "oracle-plan.json").unlink()
        out = f.root / "marks"
        report = transform_plan(f.package / "template", f.package / "content", plan, None, None, out, self.payload)
        candidate = f.root / "candidate.docx"
        render_catalogue(out / "template", f.package / "content", json.loads((out / "plan.json").read_text()), candidate)
        reference = f.root / "reference.docx"
        reference.write_bytes(source)
        metrics = compare_content(reference, candidate)
        self.assertTrue(metrics["content_exact"])
        self.assertTrue(metrics["inline_exact"])
        self.assertTrue(report["source_marks_used"])
        self.assertFalse(report["strict_I1_eligible"])
        self.assertEqual(report["new_model_calls"], 0)

    def test_payload_has_no_fonts_geometry_or_text(self):
        self.assertEqual(set(self.payload), {"schema_version", "protocol", "input_sha256", "source_sha256", "blocks"})
        for block in self.payload["blocks"]:
            self.assertEqual(set(block), {"id", "length", "marks"})
            for mark in block["marks"]:
                self.assertEqual(set(mark), {"start", "end", "flags"})
        self.assertNotIn("Первый", json.dumps(self.payload, ensure_ascii=False))

    def test_wrong_input_duplicate_blocks_overlap_and_invalid_flags_fail(self):
        f = self.f
        _, mapping = expand_mark_styles(f.template)
        mutations = []
        wrong = copy.deepcopy(self.payload); wrong["input_sha256"] = "bad"; mutations.append(wrong)
        wrong = copy.deepcopy(self.payload); wrong["blocks"].append(wrong["blocks"][0]); mutations.append(wrong)
        wrong = copy.deepcopy(self.payload)
        block = next(b for b in wrong["blocks"] if b["marks"])
        block["marks"].append(copy.deepcopy(block["marks"][0])); mutations.append(wrong)
        wrong = copy.deepcopy(self.payload)
        block = next(b for b in wrong["blocks"] if b["marks"])
        block["marks"][0]["flags"][0] = 1; mutations.append(wrong)
        for payload in mutations:
            with self.subTest(payload=mutations.index(payload)), self.assertRaises(DocumentError):
                apply_marks(f.content, f.plan, payload, mapping)

    def test_expansion_changes_only_declared_emphasis_properties(self):
        from articleflow.docx_engine import NS, parse_xml
        f = self.f
        expanded, mapping = expand_mark_styles(f.template)
        def remaining(raw):
            if not raw:
                return []
            node = parse_xml(raw[0].encode())
            for name in ("b", "i", "vertAlign"):
                for child in list(node.findall("w:" + name, NS)):
                    node.remove(child)
            from lxml import etree as E
            return [E.tostring(child) for child in node]
        for style, variants in mapping.items():
            self.assertEqual(len(variants), 12)
            for derived in variants.values():
                self.assertEqual(remaining(f.template["styles"]["character"][style]),
                                 remaining(expanded["styles"]["character"][derived]))

    def test_conflicting_source_payloads_are_rejected_before_writing(self):
        f = self.f
        with self.assertRaisesRegex(DocumentError, "SEMANTIC_PAYLOAD_CONFLICT"):
            transform_plan(f.package / "template", f.package / "content", f.plan, None, {}, f.root / "bad", self.payload)
        self.assertFalse((f.root / "bad").exists())
