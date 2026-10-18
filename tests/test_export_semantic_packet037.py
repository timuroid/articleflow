"""Private, style-free export mirrors the external semantic import numbering."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from articleflow.agent023 import extract_input
from articleflow.docx_engine import DocumentError, digest
from articleflow.import_semantic037 import import_semantic_template
from scripts.export_semantic_packet037 import export_packet


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "datasets" / "span-grammar-v037"


class SemanticPacketExportTests(unittest.TestCase):
    def test_cli_exports_exact_concatenated_blocks_and_imports_in_same_order(self):
        names = ("reference-01", "reference-02")
        sources = [CORPUS / f"{name}.docx" for name in names]
        manifest = json.loads((CORPUS / "manifest.json").read_text())
        truth = json.loads((CORPUS / "ground-truth.json").read_text())
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / "private-packet"
            run = subprocess.run(
                [sys.executable, str(ROOT / "scripts/export_semantic_packet037.py"),
                 str(output), *(str(source) for source in sources)],
                cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout)["model_calls"], 0)
            self.assertEqual({file.name for file in output.iterdir()}, {"packet.json", ".gitignore"})
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            self.assertEqual((output / "packet.json").stat().st_mode & 0o777, 0o600)
            packet = json.loads((output / "packet.json").read_text())
            self.assertEqual(packet["schema"], "external-semantic-packet-037")
            self.assertEqual(packet["paragraphs"], 88)
            self.assertEqual(packet["reference_order"], [str(path.resolve()) for path in sources])
            self.assertEqual(packet["teacher_json_contract"]["keys"],
                             ["roles", "groups", "inline_roles", "inline", "questions"])
            for i, source in enumerate(sources):
                reference = packet["references"][i]
                self.assertEqual(reference["document"], i + 1)
                self.assertEqual(reference["sha256"], digest(source.read_bytes()))
                self.assertEqual((reference["first_paragraph"], reference["last_paragraph"]),
                                 (i * 44 + 1, (i + 1) * 44))
                extracted = extract_input(source, root / f"independent-{i}")
                rows = packet["blocks"][i * 44:(i + 1) * 44]
                self.assertEqual([row["n"] for row in rows], list(range(i * 44 + 1, (i + 1) * 44 + 1)))
                self.assertEqual([row["document"] for row in rows], [i + 1] * 44)
                self.assertEqual([row["content_block"] for row in rows], extracted["blocks"])
                self.assertEqual([row["import_id"] for row in rows],
                                 [f"{i}:{block['id']}" for block in extracted["blocks"]])
                self.assertEqual(reference["content_structure"], extracted["structure"])
                for row in rows:
                    self.assertNotIn("role", row["structure"])
                    self.assertFalse({"paragraph_style", "character_styles", "style_spans", "font", "color"}
                                     & set(row["structure"]))

            # The contract's global n indices are directly consumable by the
            # unmodified importer, including inline paragraph numbers.
            golden_rows = [row for name in names for row in manifest["entries"][name]["rows"]]
            groups = []
            inline = []
            for n, row in enumerate(golden_rows, 1):
                if groups and groups[-1]["role"] == row["role"]:
                    groups[-1]["end"] = n
                else:
                    groups.append({"start": n, "end": n, "role": row["role"]})
                inline.extend({"paragraph": n, **mark} for mark in row["inline"])
            teacher = root / "teacher.json"
            teacher.write_text(json.dumps({
                "roles": {role: role.replace("_", " ") for role in truth["paragraph_roles"]},
                "groups": groups,
                "inline_roles": {role: item["selector"] for role, item in truth["inline_roles"].items()
                                 if role != "plain"},
                "inline": inline, "questions": [],
            }, ensure_ascii=False))
            report = import_semantic_template(sources, teacher, root / "imported", span_grammar=True)
            self.assertEqual(report["paragraphs"], packet["paragraphs"])
            self.assertEqual(report["training_conflicts"], 0)

    def test_role_input_is_unchanged_when_source_typography_is_corrupted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = root / "target"; b = root / "corrupted"
            export_packet([CORPUS / "heldout-target.docx"], a)
            export_packet([CORPUS / "heldout-input-i1.docx"], b)
            target = json.loads((a / "packet.json").read_text())
            corrupted = json.loads((b / "packet.json").read_text())
            self.assertNotEqual(target["references"][0]["sha256"],
                                corrupted["references"][0]["sha256"])
            self.assertEqual(target["blocks"], corrupted["blocks"])
            self.assertEqual(target["references"][0]["content_structure"],
                             corrupted["references"][0]["content_structure"])

    def test_failed_extraction_and_existing_destination_publish_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bad = root / "broken.docx"; bad.write_bytes(b"not a DOCX")
            output = root / "private-packet"
            with self.assertRaisesRegex(DocumentError, "INVALID_DOCX_ZIP"):
                export_packet([CORPUS / "reference-01.docx", bad], output)
            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob(".private-packet.staging-*")), [])
            with self.assertRaisesRegex(DocumentError, "EXPORT_REFERENCE_LIMIT"):
                export_packet([], output)
            with self.assertRaisesRegex(DocumentError, "EXPORT_REFERENCE_LIMIT"):
                export_packet([CORPUS / "reference-01.docx"] * 11, output)
            self.assertFalse(output.exists())
            output.mkdir()
            with self.assertRaisesRegex(DocumentError, "OUTPUT_ALREADY_EXISTS"):
                export_packet([CORPUS / "reference-01.docx"], output)


if __name__ == "__main__":
    unittest.main()
