import copy
import json
import unittest
from pathlib import Path

import test_catalogue as fixtures
from articleflow.catalogue import render_catalogue
from articleflow.context_rules import (
    fit_rules, apply_context_rules, extract_indices, transform_plan,
    validate_rule_pack, expand_vertical_styles, apply_indices,
)
from articleflow.docx_engine import DocumentError, compare_content, digest


class ContextRuleTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.CatalogueTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        f = self.f
        self.pack, self.audit = fit_rules(f.template, f.content, f.plan, f.plan["template_sha256"])

    def test_rule_pack_contains_no_article_ids_text_or_span_offsets(self):
        raw = json.dumps(self.pack, ensure_ascii=False)
        self.assertNotIn(self.f.content["blocks"][0]["text"], raw)
        self.assertNotIn("b-000001", raw)
        self.assertNotIn("layout-000001", raw)
        self.assertNotIn('"start"', raw)
        self.assertNotIn('"text"', raw)
        validate_rule_pack(self.pack, self.f.template)

    def test_same_conditions_with_conflicting_styles_create_no_rule(self):
        f = self.f
        # Two image-only paragraphs have the same role/context except neighbors;
        # add repeated body paragraphs to create an identical interior context.
        content = copy.deepcopy(f.content)
        template = f.template
        p = copy.deepcopy(f.plan)
        variants = list(template["styles"]["paragraph"])
        prototype = copy.deepcopy(content["blocks"][0])
        prototype["atoms"] = [{"kind": "text", "text": "Синтетический абзац"}]
        prototype["text"] = "Синтетический абзац"
        content["blocks"] = []
        content["objects"] = []
        content["structure"] = []
        p["blocks"], p["layout"], p["objects"] = [], [], []
        character = template["roles"]["body"]["character_styles"][0]
        for i in range(4):
            b = copy.deepcopy(prototype)
            b["id"] = f"synth-{i}"
            content["blocks"].append(b)
            content["structure"].append({"kind": "paragraph", "id": b["id"]})
            p["blocks"].append({"id": b["id"], "role": "body", "paragraph_style": variants[i % 2], "spans": [{"start": 0, "end": len(b["text"]), "style": character}]})
        pack, audit = fit_rules(template, content, p, p["template_sha256"])
        result, report = apply_context_rules(template, content, p, pack)
        self.assertEqual(audit["ambiguous_observations"], 2)
        self.assertEqual(len(report["unresolved"]), 2)
        self.assertTrue(report["needs_review"])
        self.assertEqual(result["blocks"], p["blocks"])

    def test_rules_reuse_when_article_text_and_all_runtime_ids_change(self):
        f = self.f
        c, p = copy.deepcopy(f.content), copy.deepcopy(f.plan)
        def rename(value):
            if isinstance(value, dict):
                return {k: rename(v) for k, v in value.items()}
            if isinstance(value, list):
                return [rename(v) for v in value]
            if isinstance(value, str) and value.startswith(("b-", "layout-", "obj-")):
                return "new-" + value
            return value
        c, p = rename(c), rename(p)
        # Equal-length substitution also changes the immutable atom text.
        c = json.loads(json.dumps(c, ensure_ascii=False).replace("Первый", "Второй"))
        original, _ = apply_context_rules(f.template, f.content, f.plan, self.pack)
        result, report = apply_context_rules(f.template, c, p, self.pack)
        self.assertEqual([b["paragraph_style"] for b in result["blocks"]], [b["paragraph_style"] for b in original["blocks"]])
        self.assertTrue(report["applied"])

    def test_forbidden_conditions_and_equal_priority_conflicts_rejected(self):
        f = self.f
        pack = copy.deepcopy(self.pack)
        pack["rules"][0]["when"]["block_id"] = "b-000001"
        with self.assertRaisesRegex(DocumentError, "RULE_CONDITION_NOT_ALLOWED"):
            validate_rule_pack(pack, f.template)
        pack = copy.deepcopy(self.pack)
        rule = next(r for r in pack["rules"] if r["kind"] == "paragraph")
        conflict = copy.deepcopy(rule)
        conflict["id"] += "-conflict"
        conflict["set"]["style"] = next(s for s in f.template["roles"]["body"]["paragraph_styles"] if s != rule["set"]["style"])
        pack["rules"].append(conflict)
        with self.assertRaisesRegex(DocumentError, "RULE_CONFLICT"):
            apply_context_rules(f.template, f.content, f.plan, pack)

    def test_indices_restore_scientific_payload_without_source_at_runtime(self):
        f = self.f
        semantics = extract_indices(f.source, f.package / "content/content.json")
        expanded, mapping = expand_vertical_styles(f.template)
        # Deliberately remove the source superscript in the predicted plan.
        plan = copy.deepcopy(f.plan)
        normal = next(s["style"] for s in plan["blocks"][0]["spans"] if "vertAlign" not in str(f.template["styles"]["character"][s["style"]]))
        for s in plan["blocks"][0]["spans"]:
            if "vertAlign" in str(f.template["styles"]["character"][s["style"]]):
                s["style"] = normal
        output = f.root / "transformed"
        source = f.source.read_bytes()
        f.source.unlink()
        (f.package / "oracle-plan.json").unlink()
        report = transform_plan(f.package / "template", f.package / "content", plan, None, semantics, output)
        result = json.loads((output / "plan.json").read_text())
        target = f.root / "candidate.docx"
        render_catalogue(output / "template", f.package / "content", result, target)
        reference = f.root / "reference.docx"
        reference.write_bytes(source)
        self.assertTrue(compare_content(reference, target)["content_exact"])
        self.assertFalse(report["strict_I1_eligible"])
        self.assertEqual(report["new_model_calls"], 0)

    def test_index_payload_hash_and_ranges_are_checked(self):
        f = self.f
        semantics = extract_indices(f.source, f.package / "content/content.json")
        _, mapping = expand_vertical_styles(f.template)
        changed = copy.deepcopy(semantics)
        changed["input_sha256"] = "wrong"
        with self.assertRaisesRegex(DocumentError, "SEMANTICS_INPUT_HASH"):
            apply_indices(f.content, f.plan, changed, mapping)
        changed = copy.deepcopy(semantics)
        first = next(b for b in changed["blocks"] if b["indices"])
        first["indices"][0]["end"] = first["length"] + 1
        with self.assertRaisesRegex(DocumentError, "SEMANTICS_RANGE"):
            apply_indices(f.content, f.plan, changed, mapping)

    def test_unknown_layout_does_not_take_an_unrelated_rule(self):
        f = self.f
        pack = copy.deepcopy(self.pack)
        pack["rules"] = [r for r in pack["rules"] if r["kind"] != "drawing"]
        _, report = apply_context_rules(f.template, f.content, f.plan, pack)
        self.assertEqual(sum(r["kind"] == "drawing" for r in report["unresolved"]), len(f.plan["objects"]))
        self.assertTrue(report["needs_review"])
