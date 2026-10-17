"""Output packages must pass the same defensive import checks as inputs."""
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from docx import Document
from articleflow.docx_engine import DocumentError, load_package, write_package


class PackageRoundtripTests(unittest.TestCase):
    def test_highly_compressible_part_roundtrips_without_changing_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            source, target = Path(d) / "source.docx", Path(d) / "target.docx"
            Document().save(source)
            parts = load_package(source)
            parts["word/media/synthetic.bin"] = b"A" * 100000
            write_package(target, parts)
            self.assertEqual(load_package(target), parts)

    def test_import_still_rejects_excessive_compression(self):
        with tempfile.TemporaryDirectory() as d:
            source, target = Path(d) / "source.docx", Path(d) / "target.docx"
            Document().save(source)
            parts = load_package(source)
            parts["word/media/synthetic.bin"] = b"A" * 100000
            with ZipFile(target, "w", ZIP_DEFLATED) as archive:
                for name, data in parts.items():
                    archive.writestr(name, data)
            with self.assertRaisesRegex(DocumentError, "ZIP_RATIO_OR_ENCRYPTION"):
                load_package(target)
