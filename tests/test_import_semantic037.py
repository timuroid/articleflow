"""Offline external semantic import through the real DOCX catalogue pipeline."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from articleflow.agent023 import apply
from articleflow.docx_engine import DocumentError, content_fingerprint
from articleflow.format032 import audit
from articleflow.import_semantic037 import import_semantic_template
from articleflow.research import compare_pixels, render_pdf


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "datasets" / "span-grammar-v037"


def teacher_candidate(names):
    manifest = json.loads((CORPUS / "manifest.json").read_text())
    truth = json.loads((CORPUS / "ground-truth.json").read_text())
    rows = [row for name in names for row in manifest["entries"][name]["rows"]]
    groups = []
    inline = []
    for number, row in enumerate(rows, 1):
        if groups and groups[-1]["role"] == row["role"]:
            groups[-1]["end"] = number
        else:
            groups.append({"start": number, "end": number, "role": row["role"]})
        inline.extend({"paragraph": number, **mark} for mark in row["inline"])
    return {
        "roles": {name: name.replace("_", " ") for name in truth["paragraph_roles"]},
        "groups": groups,
        "inline_roles": {name: item["selector"] for name, item in truth["inline_roles"].items()
                         if name != "plain"},
        "inline": inline,
        "questions": [],
    }


class ExternalSemanticImportTests(unittest.TestCase):
    def test_three_reference_cli_import_is_compiled_but_not_certified(self):
        names = ("reference-01", "reference-02", "reference-03")
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            teacher = directory / "teacher.json"
            teacher.write_text(json.dumps(teacher_candidate(names), ensure_ascii=False))
            output = directory / "imported"
            command = [sys.executable, "-m", "articleflow", "import-semantic-template",
                       str(teacher), str(output), *(str(CORPUS / f"{name}.docx") for name in names),
                       "--span-grammar"]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=120)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            response = json.loads(completed.stdout)
            report = json.loads((output / "report.json").read_text())
            package = json.loads((output / "template" / "semantic.json").read_text())
            self.assertEqual(response["status"], "draft_compiled")
            self.assertEqual(report["provenance"], "external_candidate")
            self.assertEqual(report["model_calls"], 0)
            self.assertEqual(report["paragraphs"], 132)
            self.assertEqual(len(report["references"]), 3)
            self.assertEqual(sum(report["role_counts"].values()), 132)
            self.assertEqual(report["training_conflicts"], 0)
            self.assertEqual(report["conflicts"], [])
            self.assertEqual(report["certification"], "not_evaluated_on_unseen_documents")
            self.assertEqual((output / report["teacher_candidate"]).read_bytes(), teacher.read_bytes())
            self.assertEqual(package["status"], "draft")
            self.assertEqual(package["span_grammar"]["status"], "complete")
            self.assertTrue((output / "template" / "rules.json").is_file())
            self.assertNotIn("ready", json.dumps(report))

            # Replay a held-out DOCX through the imported package. The fixed
            # semantic answer is an oracle fixture, never attributed to an LLM.
            source = CORPUS / "heldout-input-i1.docx"
            golden = CORPUS / "heldout-target.docx"
            heldout = teacher_candidate(("heldout-target",))
            fixed = {key: heldout[key] for key in ("groups", "inline")}
            calls = []
            def fixed_student(config, messages, directory, **kwargs):
                calls.append(1)
                request = json.loads(messages[1]["content"])
                self.assertEqual(request["inline_role_contexts"], {
                    "defined_term": ["definition"],
                    "latin_symbol": ["symbol_explanation"],
                    "caption_label": ["figure_caption"],
                })
                kwargs["validate"](fixed)
                return fixed, {"api_attempts": 0}
            trial = apply(source, output / "template", directory / "heldout-application",
                          {}, caller=fixed_student)
            self.assertEqual(calls, [1])
            self.assertEqual(trial["status"], "rendered_unverified", trial)
            self.assertEqual(trial["model_invocations"], 1)
            result = directory / "heldout-application" / "result.docx"
            self.assertEqual(content_fingerprint(golden), content_fingerprint(result))
            self.assertTrue(audit(golden, result)["property_exact"])
            if shutil.which("soffice"):
                expected_pdf = render_pdf(golden, directory / "heldout-golden")
                self.assertTrue(compare_pixels(expected_pdf, Path(trial["pdf"]))["pixel_exact"])

    def test_ambiguous_document_reports_exact_conflicts_and_never_ready(self):
        source = CORPUS / "negative-ambiguous.docx"
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            teacher = directory / "teacher.json"
            teacher.write_text(json.dumps({"roles": {"body": "Ordinary body paragraph"},
                "groups": [{"start": 1, "end": 4, "role": "body"}],
                "inline_roles": {}, "inline": [], "questions": []}))
            output = directory / "imported"
            report = import_semantic_template([source], teacher, output, span_grammar=True)
            self.assertEqual(report["status"], "needs_review")
            self.assertGreater(report["training_conflicts"], 0)
            self.assertEqual(report["training_conflicts"], len(report["conflicts"]))
            self.assertTrue(all(row["kind"] == "character" for row in report["conflicts"]))
            self.assertEqual(report["model_calls"], 0)
            self.assertEqual(json.loads((output / "template" / "semantic.json").read_text())["status"], "draft")

    def test_invalid_inline_anchor_and_prose_do_not_publish_output(self):
        source = CORPUS / "reference-01.docx"
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            teacher = directory / "teacher.json"
            output = directory / "imported"
            teacher.write_text("This article has a title and body.")
            with self.assertRaisesRegex(DocumentError, "IMPORT_TEACHER_JSON_INVALID"):
                import_semantic_template([source], teacher, output)
            self.assertFalse(output.exists())
            candidate = teacher_candidate(("reference-01",))
            candidate["inline"][0]["quote"] = "not an exact source quote"
            teacher.write_text(json.dumps(candidate, ensure_ascii=False))
            with self.assertRaisesRegex(DocumentError, "INLINE_QUOTE_MISMATCH"):
                import_semantic_template([source], teacher, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
