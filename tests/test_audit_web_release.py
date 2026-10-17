import importlib.util
import io
import tarfile
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_web_release.py"
spec = importlib.util.spec_from_file_location("audit_web_release", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class AuditReleaseTests(unittest.TestCase):
    def build_archive(self, names):
        folder = tempfile.TemporaryDirectory()
        target = Path(folder.name) / "release.tar.gz"
        with tarfile.open(target, "w:gz") as bundle:
            for name in names:
                payload = b"ok"
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                bundle.addfile(info, io.BytesIO(payload))
        return folder, target

    def test_counts_private_material_without_listing_its_name(self):
        names = [f"articleflow-web-017/{name}" for name in audit.REQUIRED]
        names.append("articleflow-web-017/private-fixtures/real-article.docx")
        folder, target = self.build_archive(names)
        self.addCleanup(folder.cleanup)
        result = audit.inspect(target)
        self.assertEqual(result["private_or_unclassified_files"], 1)
        self.assertNotIn("real-article", str(result))

    def test_rejects_path_traversal(self):
        names = [f"articleflow-web-017/{name}" for name in audit.REQUIRED]
        names.append("articleflow-web-017/../escape")
        folder, target = self.build_archive(names)
        self.addCleanup(folder.cleanup)
        with self.assertRaisesRegex(audit.ReleaseError, "небезопасный"):
            audit.inspect(target)

    def test_rejects_missing_app(self):
        names = [f"articleflow-web-017/{name}" for name in audit.REQUIRED if name != "src/articleflow/web017.py"]
        folder, target = self.build_archive(names)
        self.addCleanup(folder.cleanup)
        with self.assertRaisesRegex(audit.ReleaseError, "web017.py"):
            audit.inspect(target)


if __name__ == "__main__":
    unittest.main()
