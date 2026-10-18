"""Single-owner Web 017 recovery slice: private FastAPI + SQLite + local files.

External model calls require private configuration and per-operation consent. Deploy only on loopback behind TLS and
owner authentication at the reverse proxy. Manuscript contents stay in data_dir.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import shutil
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from .docx_engine import DocumentError
from .structure017 import SLOTS, REQUIRED, compile_document, inspect_templates, inventory

MAX_DOCX = 25 * 1024 * 1024
MAX_BATCH = 200
MAX_TEMPLATES = 10
MAX_SEMANTIC_JSON = 2 * 1024 * 1024
STATIC = Path(__file__).with_name("web_static017")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return uuid.uuid4().hex


def _safe_name(value: str | None) -> str:
    name = Path(value or "document.docx").name
    if not re.fullmatch(r"[\w .()\-]{1,160}\.docx", name, re.I | re.U):
        raise HTTPException(400, "DOCX_FILENAME_REQUIRED")
    return name


def font_audit(families=("Arial", "Times New Roman")) -> dict:
    from .fonts019 import audit
    return audit(tuple(families))


def model_config():
    path = os.environ.get("ARTICLEFLOW_MODEL_CONFIG")
    if not path:
        return None
    try:
        config = json.loads(Path(path).read_text())
        if not all(Path(config[k]).is_file() for k in ("key_file", "prompt", "ledger")):
            return None
        return config
    except (OSError, KeyError, ValueError):
        return None


class Store:
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self.db_path = self.root / "articleflow.sqlite3"
        self.batch_lock = threading.Lock()
        self.csrf_path = self.root / "csrf-token"
        if not self.csrf_path.exists():
            fd = os.open(self.csrf_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w") as stream:
                stream.write(secrets.token_urlsafe(32))
        self.csrf = self.csrf_path.read_text().strip()
        self._initialize()

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.db_path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        try:
            with con:
                yield con
        finally:
            con.close()

    def _initialize(self):
        with self.connect() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS templates (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS template_versions (
                    template_id TEXT NOT NULL, version INTEGER NOT NULL, spec_json TEXT NOT NULL,
                    approved INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
                    PRIMARY KEY(template_id,version),
                    FOREIGN KEY(template_id) REFERENCES templates(id));
                CREATE TABLE IF NOT EXISTS template_runs (
                    id TEXT PRIMARY KEY, template_id TEXT NOT NULL, base_version INTEGER NOT NULL,
                    status TEXT NOT NULL, report_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
                    FOREIGN KEY(template_id) REFERENCES templates(id));
                CREATE TABLE IF NOT EXISTS batches (
                    id TEXT PRIMARY KEY, template_id TEXT NOT NULL, template_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL, FOREIGN KEY(template_id) REFERENCES templates(id));
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, source_name TEXT NOT NULL,
                    status TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
                    assignments_json TEXT NOT NULL DEFAULT '{}', report_json TEXT,
                    created_at TEXT NOT NULL, FOREIGN KEY(batch_id) REFERENCES batches(id));
                CREATE TABLE IF NOT EXISTS exports (
                    id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, created_at TEXT NOT NULL,
                    FOREIGN KEY(batch_id) REFERENCES batches(id));
            """)
            for table, column, declaration in (("jobs", "supplied_json", "TEXT NOT NULL DEFAULT '{}'"),
                                                ("batches", "use_llm", "INTEGER NOT NULL DEFAULT 0")):
                if column not in {r[1] for r in con.execute(f"PRAGMA table_info({table})")}:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
            con.execute("UPDATE template_runs SET status='interrupted' WHERE status IN ('queued','running')")
            con.execute("UPDATE jobs SET status='interrupted' WHERE status IN ('queued','processing')")
        os.chmod(self.db_path, 0o600)

    def one(self, query: str, args=()):
        with self.connect() as con:
            row = con.execute(query, args).fetchone()
        if row is None:
            raise HTTPException(404, "NOT_FOUND")
        return dict(row)

    def all(self, query: str, args=()):
        with self.connect() as con:
            return [dict(row) for row in con.execute(query, args).fetchall()]

    def execute(self, query: str, args=()):
        with self.connect() as con:
            con.execute(query, args)

    def path(self, *pieces: str) -> Path:
        path = self.root.joinpath(*pieces)
        if not path.resolve().is_relative_to(self.root):
            raise HTTPException(400, "INVALID_PATH")
        return path


async def _save_upload(upload: UploadFile, path: Path, *, container_only=False):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    size = 0
    try:
        with path.open("xb") as stream:
            os.chmod(path, 0o600)
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_DOCX:
                    raise HTTPException(413, "DOCX_TOO_LARGE")
                stream.write(chunk)
        if size == 0:
            raise HTTPException(400, "EMPTY_DOCX")
        if container_only:
            from .docx_engine import load_package
            load_package(path,allow_unsupported=True)
        else:inventory(path)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


async def _save_semantic_json(upload: UploadFile, path: Path):
    if not upload.filename or Path(upload.filename).suffix.lower() != ".json":
        raise HTTPException(400, "TEACHER_JSON_FILENAME_REQUIRED")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    size = 0
    try:
        with path.open("xb") as stream:
            os.chmod(path, 0o600)
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_SEMANTIC_JSON:
                    raise HTTPException(413, "TEACHER_JSON_TOO_LARGE")
                stream.write(chunk)
        if not size:
            raise HTTPException(400, "EMPTY_TEACHER_JSON")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


def _latest(store: Store, template_id: str) -> dict:
    return store.one("SELECT * FROM template_versions WHERE template_id=? ORDER BY version DESC LIMIT 1", (template_id,))


def _process_job(store: Store, job_id: str):
    job = store.one("SELECT * FROM jobs WHERE id=?", (job_id,))
    batch = store.one("SELECT * FROM batches WHERE id=?", (job["batch_id"],))
    version = store.one("SELECT * FROM template_versions WHERE template_id=? AND version=?", (batch["template_id"], batch["template_version"]))
    spec = json.loads(version["spec_json"])
    if spec.get('agent023'):
        from .webagent023 import process_job
        store.execute("UPDATE jobs SET status='processing' WHERE id=?", (job_id,))
        process_job(store,job,batch,version,spec)
        return
    choices = spec.get("selected", {})
    styles = {role: spec["styles"][role][key] for role, key in choices.items() if role in spec["styles"] and key in spec["styles"][role]}
    source = store.path("jobs", job_id, "source.docx")
    revision = job["revision"]
    folder = store.path("jobs", job_id, "revisions", str(revision))
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    output = folder / "result.docx"
    editorial = folder / "editorial.docx"
    store.execute("UPDATE jobs SET status='processing' WHERE id=?", (job_id,))
    try:
        from .fonts019 import required_fonts
        assignments = json.loads(job["assignments_json"])
        contexts, model_meta = {}, None
        if batch.get("use_llm") and not assignments:
            from .model019 import plan_document
            config = model_config()
            if config is None:
                raise DocumentError("MODEL_NOT_PROVISIONED")
            assignments, contexts, model_meta = plan_document(inventory(source)["blocks"], styles, config, folder / "model")
        fonts = font_audit(required_fonts(styles))
        report = compile_document(source, output, assignments=assignments, contexts=contexts,
                                  approved=bool(version["approved"]), fonts_ok=fonts["exact"],
                                  styles=styles, editorial_output=editorial,
                                  required=spec.get("structure", {}).get("required", list(REQUIRED)),
                                  supplied=json.loads(job["supplied_json"]), model_assigned=model_meta is not None)
        from .documentcheck022 import check as check_document
        try:
            visual = check_document(output, folder / "visual", repair=True)
        except Exception as exc:
            visual = {"status": "unavailable", "error_type": type(exc).__name__}
        report["visual_validation"] = visual
        if visual["status"] != "passed":
            report["status"] = "draft"
            report["questions"].append("Проверка всех страниц требует внимания; откройте PDF и отчёт")
        # A complete extraction catalogue does not certify coarse role transfer.
        extraction = spec.get("extraction_validation", {})
        if extraction.get("status") != "passed" or extraction.get("acceptance_contract") != "production-roundtrip-022-v1":
            report["status"] = "draft"
            report["questions"].append("У этой версии шаблона нет полной проверки 022; запустите проверку и утвердите новую версию")
        from .docx_engine import digest
        report["output_sha256"] = digest(output.read_bytes())
        report["model"] = model_meta
        report["template_id"] = batch["template_id"]
        report["template_version"] = batch["template_version"]
        report["revision"] = revision
        report["font_audit"] = fonts
        (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        store.execute("UPDATE jobs SET status=?, report_json=? WHERE id=?", (report["status"], json.dumps(report, ensure_ascii=False), job_id))
    except DocumentError as exc:
        report = {"status": "error", "code": str(exc), "revision": revision}
        (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False))
        store.execute("UPDATE jobs SET status='error', report_json=? WHERE id=?", (json.dumps(report, ensure_ascii=False), job_id))


def _process_batch(store: Store, batch_id: str):
    with store.batch_lock:
        for job in store.all("SELECT id FROM jobs WHERE batch_id=? ORDER BY created_at,id", (batch_id,)):
            try:
                _process_job(store, job["id"])
            except Exception as exc:
                # The exception is intentionally not logged: parsers may include private text.
                store.execute("UPDATE jobs SET status='error', report_json=? WHERE id=?",
                              (json.dumps({"status": "error", "code": str(exc) if isinstance(exc,DocumentError) else "INTERNAL_ERROR"}), job["id"]))


class Approval(BaseModel):
    required: list[str] | None = None
    selected: dict[str, str] = Field(default_factory=dict)


class ImportApproval(BaseModel):
    run_id: str
    required_roles: list[str] = Field(default_factory=list)
    answers: dict[str, bool] = Field(default_factory=dict)


class ModelConsent(BaseModel):
    consent_external: bool = False


class Decisions(BaseModel):
    supplied: dict[str, str] = Field(default_factory=dict)
    expected_revision: int
    assignments: dict[str, str] = Field(default_factory=dict)


def create_app(data_dir: Path | None = None) -> FastAPI:
    root = data_dir or Path(os.environ.get("ARTICLEFLOW_DATA_DIR", "./var"))
    store = Store(root)
    app = FastAPI(title="ArticleFlow Web 017", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store

    def csrf(x_csrf_token: str | None = Header(default=None)):
        if not x_csrf_token or not hmac.compare_digest(x_csrf_token, store.csrf):
            raise HTTPException(403, "CSRF_REQUIRED")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "web_version":"023", "release":os.environ.get("ARTICLEFLOW_RELEASE", "development"), "mode": "model_available" if model_config() else "local_review_only"}

    @app.get("/")
    @app.get("/templates")
    def index():
        return HTMLResponse((STATIC / "index.html").read_text())

    @app.get("/app.js")
    def javascript():
        return FileResponse(STATIC / "app.js", media_type="text/javascript")

    @app.get("/style.css")
    def css():
        return FileResponse(STATIC / "style.css", media_type="text/css")

    @app.get("/api/v017/config")
    def config():
        return {"csrf_token": store.csrf, "max_docx_bytes": MAX_DOCX, "max_batch_files": MAX_BATCH,
                "max_template_files": MAX_TEMPLATES, "llm_enabled": model_config() is not None, "font_audit": font_audit()}

    @app.get("/api/v017/templates")
    def templates():
        return store.all("""SELECT t.id,t.name,t.created_at,v.version,v.approved,v.spec_json
                            FROM templates t JOIN template_versions v ON v.template_id=t.id
                            WHERE v.version=(SELECT MAX(version) FROM template_versions WHERE template_id=t.id)
                            ORDER BY t.created_at DESC""")

    @app.post("/api/v017/templates", dependencies=[Depends(csrf)])
    async def create_template(background: BackgroundTasks, name: str = Form(...), files: list[UploadFile] = File(...), agentic: bool = Form(False)):
        if not 1 <= len(files) <= MAX_TEMPLATES or not 1 <= len(name.strip()) <= 120:
            raise HTTPException(400, "TEMPLATE_INPUT_INVALID")
        from .docx_engine import digest
        template_id = _uid()
        paths = []
        for index, upload in enumerate(files):
            _safe_name(upload.filename)
            path = store.path("templates", template_id, "samples", f"{index + 1}.docx")
            try:
                await _save_upload(upload, path,container_only=agentic)
            except DocumentError as exc:
                raise HTTPException(400, str(exc)) from exc
            paths.append(path)
        try:
            spec = ({'samples':[{'sha256':digest(p.read_bytes())} for p in paths],'styles':{},'variants':{},'structure':{},'pending_agent':True} if agentic else inspect_templates(paths))
        except DocumentError as exc:
            raise HTTPException(400, str(exc)) from exc
        with store.connect() as con:
            con.execute("INSERT INTO templates VALUES (?,?,?)", (template_id, name.strip(), _now()))
            con.execute("INSERT INTO template_versions VALUES (?,?,?,?,?)",
                        (template_id, 1, json.dumps(spec, ensure_ascii=False), 0, _now()))
        if agentic:return {'id':template_id,'version':1,'spec':spec,'extraction_run_id':None}
        run_id=_uid()
        store.execute("INSERT INTO template_runs VALUES (?,?,?,?,?,?)", (run_id,template_id,1,"queued","{}",_now()))
        background.add_task(run_extraction,run_id)
        return {"id": template_id, "version": 1, "spec": spec, "extraction_run_id":run_id}

    @app.post("/api/v017/templates/import-semantic", dependencies=[Depends(csrf)])
    async def import_semantic(name: str = Form(...), files: list[UploadFile] = File(...),
                              teacher_json: UploadFile = File(...), span_grammar: bool = Form(False)):
        """Import an external candidate offline; publication still needs validation."""
        if not 1 <= len(files) <= MAX_TEMPLATES or not 1 <= len(name.strip()) <= 120:
            raise HTTPException(400, "TEMPLATE_INPUT_INVALID")
        from .docx_engine import digest
        from .import_semantic037 import import_semantic_template
        template_id, run_id = _uid(), _uid()
        template_root = store.path("templates", template_id)
        run_root = store.path("template-runs", run_id)
        references = []
        try:
            for index, upload in enumerate(files, 1):
                _safe_name(upload.filename)
                source = template_root / "samples" / f"{index}.docx"
                await _save_upload(upload, source, container_only=True)
                references.append(source)
            candidate = template_root / "teacher.json"
            await _save_semantic_json(teacher_json, candidate)
            report = import_semantic_template(references, candidate, run_root / "import",
                                              span_grammar=span_grammar)
            package_root = run_root / "import" / "template"
            spec = {
                "samples": [{"sha256": digest(source.read_bytes())} for source in references],
                "styles": {}, "variants": {}, "structure": {}, "pending_agent": True,
                "external_import": {
                    "run_id": run_id, "status": report["status"],
                    "training_conflicts": report["training_conflicts"],
                    "certification": report["certification"],
                    "package_hashes": {part: digest((package_root / part).read_bytes())
                                       for part in ("rules.json", "semantic.json", "resources.zip")},
                },
            }
            with store.connect() as con:
                con.execute("INSERT INTO templates VALUES (?,?,?)", (template_id, name.strip(), _now()))
                con.execute("INSERT INTO template_versions VALUES (?,?,?,?,?)",
                            (template_id, 1, json.dumps(spec, ensure_ascii=False), 0, _now()))
                con.execute("INSERT INTO template_runs VALUES (?,?,?,?,?,?)",
                            (run_id, template_id, 1, "needs_review",
                             json.dumps(report, ensure_ascii=False), _now()))
        except Exception as exc:
            shutil.rmtree(template_root, ignore_errors=True)
            shutil.rmtree(run_root, ignore_errors=True)
            if isinstance(exc, DocumentError):
                raise HTTPException(400, str(exc)) from exc
            raise
        return {"id": template_id, "version": 1, "approved": False,
                "import_run_id": run_id, "report": report}

    def run_import_test(run_id: str):
        from .agent023 import apply
        from .docx_engine import digest
        from .documentcheck022 import audit_pdf
        from .webagent023 import learning_model_configs
        with store.batch_lock:
            row = store.one("SELECT * FROM template_runs WHERE id=?", (run_id,))
            report = json.loads(row["report_json"])
            report["status"] = "running"
            store.execute("UPDATE template_runs SET status=?,report_json=? WHERE id=?",
                          ("running", json.dumps(report, ensure_ascii=False), run_id))
            try:
                version = store.one("SELECT * FROM template_versions WHERE template_id=? AND version=?",
                                    (row["template_id"], row["base_version"]))
                spec = json.loads(version["spec_json"])
                import_info = spec.get("external_import", {})
                package_root = store.path("template-runs", import_info["run_id"], "import", "template")
                expected = import_info["package_hashes"]
                if set(expected) != {"rules.json", "semantic.json", "resources.zip"} or any(
                    digest((package_root / part).read_bytes()) != sha for part, sha in expected.items()
                ):
                    raise DocumentError("IMPORTED_PACKAGE_CHANGED")
                config = model_config()
                if config is None:
                    raise DocumentError("MODEL_NOT_PROVISIONED")
                _, student = learning_model_configs(config)
                # A preview spends at most one student call. A failed inline
                # response remains an explicit error instead of a hidden retry.
                student["inline_repair_attempts"] = 0
                run_root = store.path("template-runs", run_id)
                source = run_root / "source.docx"
                application = run_root / "application"
                report["student_call_attempted"] = True
                result = apply(source, package_root, application, student)
                report.update(application_status=result["status"],
                              unresolved=result.get("unresolved", []),
                              model_invocations=result.get("model_invocations", 1),
                              strict_one_pass_eligible=result.get("strict_one_pass_eligible", False),
                              structure_moves=result.get("structure_moves", []))
                output = application / "result.docx"
                pdf = Path(result["pdf"]) if result.get("pdf") else None
                if result["status"] == "rendered_unverified" and output.is_file() and pdf and pdf.is_file() and pdf.resolve().is_relative_to(application.resolve()):
                    report["result_available"] = True
                    report["pdf_relative"] = str(pdf.resolve().relative_to(run_root.resolve()))
                    try:
                        report["visual_diagnostics"] = audit_pdf(pdf, output)
                    except Exception:
                        report["visual_diagnostics"] = {"status": "unavailable", "code": "VISUAL_CHECK_UNAVAILABLE"}
                else:
                    report["result_available"] = False
                report["status"] = "needs_review"
                report["certification"] = "single_preview_not_certification"
            except Exception as exc:
                report.update(status="failed", result_available=False,
                              code=str(exc) if isinstance(exc, DocumentError) else "IMPORT_TEST_UNAVAILABLE")
            store.execute("UPDATE template_runs SET status=?,report_json=? WHERE id=?",
                          (report["status"], json.dumps(report, ensure_ascii=False), run_id))

    @app.post("/api/v017/templates/{template_id}/test-import", dependencies=[Depends(csrf)])
    async def test_import(template_id: str, background: BackgroundTasks,
                          file: UploadFile = File(...), consent_external: bool = Form(False)):
        if not consent_external or model_config() is None:
            raise HTTPException(400, "MODEL_CONSENT_OR_CONFIG_REQUIRED")
        version = _latest(store, template_id)
        spec = json.loads(version["spec_json"])
        info = spec.get("external_import")
        if not info or version["approved"]:
            raise HTTPException(409, "EXTERNAL_IMPORT_DRAFT_REQUIRED")
        if info["training_conflicts"]:
            raise HTTPException(409, "IMPORT_CONFLICTS_UNRESOLVED")
        if store.all("SELECT id FROM template_runs WHERE template_id=? AND status IN ('queued','running')", (template_id,)):
            raise HTTPException(409, "TEMPLATE_RUN_IN_PROGRESS")
        _safe_name(file.filename)
        run_id = _uid()
        source = store.path("template-runs", run_id, "source.docx")
        await _save_upload(file, source, container_only=True)
        report = {"schema": "external-import-test-037", "status": "queued",
                  "provenance": "external_candidate", "import_run_id": info["run_id"],
                  "certification": "single_preview_not_certification",
                  "result_available": False, "model_invocations": 0}
        store.execute("INSERT INTO template_runs VALUES (?,?,?,?,?,?)",
                      (run_id, template_id, version["version"], "queued",
                       json.dumps(report, ensure_ascii=False), _now()))
        background.add_task(run_import_test, run_id)
        return {"id": run_id, "status": "queued", "approved": False}

    @app.get("/api/v017/import-tests/{run_id}/files/{kind}")
    def import_test_file(run_id: str, kind: str):
        row = store.one("SELECT report_json FROM template_runs WHERE id=?", (run_id,))
        report = json.loads(row["report_json"])
        if report.get("schema") != "external-import-test-037" or not report.get("result_available"):
            raise HTTPException(404, "IMPORT_TEST_FILE_UNAVAILABLE")
        run_root = store.path("template-runs", run_id)
        if kind == "docx":
            path = run_root / "application" / "result.docx"
            media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            name = "articleflow-import-preview.docx"
        elif kind == "pdf":
            path = store.path("template-runs", run_id, report["pdf_relative"])
            media, name = "application/pdf", "articleflow-import-preview.pdf"
        else:
            raise HTTPException(404, "IMPORT_TEST_FILE_UNAVAILABLE")
        if not path.is_file():
            raise HTTPException(404, "IMPORT_TEST_FILE_UNAVAILABLE")
        return FileResponse(path, media_type=media, filename=name)

    def run_import_verification(run_id: str):
        from .docx_engine import digest
        from .webagent023 import learning_model_configs
        from .webimport037 import verify_import
        with store.batch_lock:
            row = store.one("SELECT * FROM template_runs WHERE id=?", (run_id,))
            initial = json.loads(row["report_json"])
            def progress(value):
                value = {**value, "import_run_id": initial["import_run_id"]}
                store.execute("UPDATE template_runs SET status=?,report_json=? WHERE id=?",
                              (value["status"], json.dumps(value, ensure_ascii=False), run_id))
            progress({**initial, "status": "running"})
            try:
                version = store.one("SELECT * FROM template_versions WHERE template_id=? AND version=?",
                                    (row["template_id"], row["base_version"]))
                spec = json.loads(version["spec_json"])
                info = spec["external_import"]
                if info["training_conflicts"]:
                    raise DocumentError("IMPORT_CONFLICTS_UNRESOLVED")
                references = [store.path("templates", row["template_id"], "samples", f"{index}.docx")
                              for index in range(1, len(spec["samples"]) + 1)]
                imported_root = store.path("template-runs", info["run_id"], "import")
                expected = info["package_hashes"]
                if (set(expected) != {"rules.json", "semantic.json", "resources.zip"}
                    or any(digest((imported_root / "template" / part).read_bytes()) != sha
                           for part, sha in expected.items())):
                    raise DocumentError("IMPORTED_PACKAGE_CHANGED")
                config = model_config()
                if config is None:
                    raise DocumentError("MODEL_NOT_PROVISIONED")
                _, student = learning_model_configs(config)
                student["inline_repair_attempts"] = 0
                result = verify_import(references,
                                       store.path("templates", row["template_id"], "teacher.json"),
                                       imported_root,
                                       store.path("template-runs", run_id, "verification"),
                                       student, progress=progress)
                progress(result)
            except Exception as exc:
                progress({**initial, "status": "needs_review",
                          "code": str(exc) if isinstance(exc, DocumentError)
                          else "IMPORT_VERIFICATION_UNAVAILABLE"})

    @app.post("/api/v017/templates/{template_id}/verify-import", dependencies=[Depends(csrf)])
    def start_import_verification(template_id: str, body: ModelConsent,
                                  background: BackgroundTasks):
        if not body.consent_external or model_config() is None:
            raise HTTPException(400, "MODEL_CONSENT_OR_CONFIG_REQUIRED")
        version = _latest(store, template_id)
        spec = json.loads(version["spec_json"])
        info = spec.get("external_import")
        if not info or version["approved"]:
            raise HTTPException(409, "EXTERNAL_IMPORT_DRAFT_REQUIRED")
        if info["training_conflicts"]:
            raise HTTPException(409, "IMPORT_CONFLICTS_UNRESOLVED")
        if store.all("SELECT id FROM template_runs WHERE template_id=? AND status IN ('queued','running')", (template_id,)):
            raise HTTPException(409, "TEMPLATE_RUN_IN_PROGRESS")
        run_id = _uid()
        report = {"schema": "external-import-verification-037", "status": "queued",
                  "import_run_id": info["run_id"], "approved": False,
                  "held_out_transfer": "not_measured", "model_invocations": 0}
        store.execute("INSERT INTO template_runs VALUES (?,?,?,?,?,?)",
                      (run_id, template_id, version["version"], "queued",
                       json.dumps(report, ensure_ascii=False), _now()))
        background.add_task(run_import_verification, run_id)
        return {"id": run_id, "status": "queued", "approved": False}

    @app.post("/api/v017/templates/{template_id}/approve-import", dependencies=[Depends(csrf)])
    def approve_import(template_id: str, body: ImportApproval):
        from .docx_engine import digest
        version = _latest(store, template_id)
        spec = json.loads(version["spec_json"])
        info = spec.get("external_import")
        if not info or version["approved"] or info["training_conflicts"]:
            raise HTTPException(409, "EXTERNAL_IMPORT_DRAFT_REQUIRED")
        row = store.one("SELECT * FROM template_runs WHERE id=? AND template_id=?",
                        (body.run_id, template_id))
        report = json.loads(row["report_json"])
        flags = report.get("certification", {})
        if (row["base_version"] != version["version"] or row["status"] != "reference_replay_passed"
            or report.get("schema") != "external-import-verification-037"
            or report.get("import_run_id") != info["run_id"]
            or report.get("held_out_transfer") != "not_measured"
            or not all(flags.get(name) is True for name in (
                "neutralized_references_exact", "format_properties_exact",
                "negative_controls_detected"))
            or len(report.get("samples", [])) != len(spec["samples"])
            or not all(sample.get("passed") is True and
                sample.get("inline_exact") is True and
                sample.get("role_correct") == sample.get("role_total") and
                sample.get("role_total", 0) > 0 for sample in report["samples"])
            or not report.get("negative_controls") or not all(
                control.get("detected") is True for control in report["negative_controls"])
            or any(not {"font", "page_geometry", "scientific_content_change"} <=
                   {control.get("kind") for control in report["negative_controls"]
                    if control.get("document") == number}
                   for number in range(1, len(spec["samples"]) + 1))):
            raise HTTPException(409, "IMPORT_VERIFICATION_REQUIRED")
        references = [store.path("templates", template_id, "samples", f"{index}.docx")
                      for index in range(1, len(spec["samples"]) + 1)]
        candidate = store.path("templates", template_id, "teacher.json")
        package_root = store.path("template-runs", info["run_id"], "import", "template")
        if ([digest(path.read_bytes()) for path in references] != report.get("source_hashes")
            or [digest(path.read_bytes()) for path in references] !=
                [sample["sha256"] for sample in spec["samples"]]
            or digest(candidate.read_bytes()) != report.get("teacher_json_sha256")
            or any(digest((package_root / part).read_bytes()) != sha
                   for part, sha in info["package_hashes"].items())
            or info["package_hashes"] != report.get("package_hashes")):
            raise HTTPException(409, "IMPORT_EVIDENCE_CHANGED")
        package = json.loads((package_root / "semantic.json").read_text())
        roles = set(package["roles"])
        questions = json.loads(candidate.read_text())["questions"]
        if not set(body.required_roles) <= roles or not set(body.answers) <= roles:
            raise HTTPException(400, "REQUIRED_ROLE_INVALID")
        if any(question["role"] not in body.answers for question in questions):
            raise HTTPException(409, "IMPORT_QUESTIONS_UNANSWERED")
        required = sorted((set(body.required_roles) |
                           {role for role, value in body.answers.items() if value}) -
                          {role for role, value in body.answers.items() if not value})
        spec["agent023"] = {
            "run_id": info["run_id"], "iteration": 0, "contract": "external-import-037",
            "engine_profile": None, "mode": "assisted", "package_hashes": info["package_hashes"],
            "required_roles": required, "answers": body.answers, "roles": package["roles"],
            "student_model": report["student_model"], "verification": "reference_verified",
            "held_out_transfer": "not_measured", "verification_run_id": body.run_id,
        }
        with store.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            current = con.execute("SELECT MAX(version) FROM template_versions WHERE template_id=?",
                                  (template_id,)).fetchone()[0]
            if current != version["version"]:
                raise HTTPException(409, "TEMPLATE_VERSION_CHANGED")
            con.execute("INSERT INTO template_versions VALUES (?,?,?,?,?)",
                        (template_id, current + 1, json.dumps(spec, ensure_ascii=False), 1, _now()))
        return {"template_id": template_id, "version": version["version"] + 1,
                "approved": True, "held_out_transfer": "not_measured"}

    @app.get("/api/v017/templates/{template_id}")
    def template(template_id: str):
        item = store.one("SELECT * FROM templates WHERE id=?", (template_id,))
        version = _latest(store, template_id)
        return {**item, "version": version["version"], "approved": bool(version["approved"]),
                "spec": json.loads(version["spec_json"])}

    @app.post("/api/v017/templates/{template_id}/analyze", dependencies=[Depends(csrf)])
    def analyze_template(template_id: str, body: ModelConsent):
        config = model_config()
        if not body.consent_external or config is None:
            raise HTTPException(400, "MODEL_CONSENT_OR_CONFIG_REQUIRED")
        from .model019 import plan_document
        config = dict(config)
        config["model"] = config.get("extractor_model", config["model"])
        config["reasoning_effort"] = config.get("extractor_reasoning_effort", config.get("reasoning_effort", "none"))
        with store.batch_lock:
            version = _latest(store, template_id)
            paths = sorted(store.path("templates", template_id, "samples").glob("*.docx"))
            preliminary = inspect_templates(paths)
            plans = {}
            run = store.path("templates", template_id, "analysis", _uid())
            try:
                for index, path in enumerate(paths):
                    inv = inventory(path)
                    roles, contexts, meta = plan_document(inv["blocks"], preliminary["styles"], config, run / str(index))
                    plans[inv["source_sha256"]] = {"assignments": roles, "contexts": contexts}
                spec = inspect_templates(paths, plans)
            except DocumentError as exc:
                raise HTTPException(409, str(exc)) from exc
            store.execute("INSERT INTO template_versions VALUES (?,?,?,?,?)",
                          (template_id, version["version"] + 1, json.dumps(spec, ensure_ascii=False), 0, _now()))
        return {"id": template_id, "version": version["version"] + 1, "spec": spec}

    def run_extraction(run_id, selected=None, required=None):
        with store.batch_lock:
            row = store.one("SELECT * FROM template_runs WHERE id=?", (run_id,))
            version = store.one("SELECT * FROM template_versions WHERE template_id=? AND version=?", (row["template_id"], row["base_version"]))
            paths = sorted(store.path("templates", row["template_id"], "samples").glob("*.docx"))
            from .templateagent022 import run
            def progress(report):
                store.execute("UPDATE template_runs SET status=?,report_json=? WHERE id=?",
                              (report["status"], json.dumps(report, ensure_ascii=False), run_id))
            try:
                spec = json.loads(version["spec_json"])
                if required is not None: spec.setdefault("structure", {})["required"] = required
                report = run(paths, spec, store.path("template-runs", run_id), progress, **({"selected": selected} if selected is not None else {}))
                progress(report)
            except Exception as exc:
                progress({"status":"unavailable", "error_type":type(exc).__name__})

    @app.post("/api/v017/templates/{template_id}/refine", dependencies=[Depends(csrf)])
    def refine_template(template_id: str, background: BackgroundTasks):
        version = _latest(store, template_id)
        old_spec = json.loads(version["spec_json"])
        if old_spec.get("extractor_revision") != "022-v1":
            # Re-read source evidence with the new extractor, retaining semantic
            # annotations. Re-running an old cached spec would miss new fields.
            from .structure017 import suggest_roles
            paths=sorted(store.path("templates",template_id,"samples").glob("*.docx"))
            plans={}
            for path in paths:
                inv=inventory(path);roles,_=suggest_roles(inv["blocks"])
                sample=next(s for s in old_spec["samples"] if s["sha256"]==inv["source_sha256"])
                contexts={o["block_id"]:o["role"] for o in sample["observations"]}
                roles.update({bid:key.split('.')[0] for bid,key in contexts.items()})
                plans[inv["source_sha256"]]={"assignments":roles,"contexts":contexts}
            fresh=inspect_templates(paths,plans)
            fresh["role_evidence"]=old_spec.get("role_evidence","heuristic")
            fresh["structure"]["required"]=old_spec.get("structure",{}).get("required",fresh["structure"]["required"])
            store.execute("INSERT INTO template_versions VALUES (?,?,?,?,?)",(template_id,version["version"]+1,json.dumps(fresh,ensure_ascii=False),0,_now()))
            version=_latest(store,template_id)
        pending = store.all("SELECT id FROM template_runs WHERE template_id=? AND base_version=? AND status IN ('queued','running')", (template_id, version["version"]))
        if pending: return {"id":pending[0]["id"], "status":"running"}
        run_id = _uid()
        store.execute("INSERT INTO template_runs VALUES (?,?,?,?,?,?)", (run_id,template_id,version["version"],"queued","{}",_now()))
        background.add_task(run_extraction,run_id)
        return {"id":run_id,"status":"queued"}

    @app.get("/api/v017/templates/{template_id}/runs")
    def template_runs(template_id: str):
        store.one("SELECT id FROM templates WHERE id=?", (template_id,))
        return store.all("SELECT * FROM template_runs WHERE template_id=? ORDER BY created_at DESC", (template_id,))

    @app.get("/api/v017/template-runs/{run_id}")
    def template_run(run_id: str):
        row = store.one("SELECT * FROM template_runs WHERE id=?", (run_id,))
        row["report"] = json.loads(row.pop("report_json"))
        return row

    @app.get("/api/v017/template-runs/{run_id}/preview/{sample_index}")
    def template_preview(run_id: str, sample_index: int):
        row = store.one("SELECT * FROM template_runs WHERE id=?", (run_id,))
        report = json.loads(row["report_json"])
        if not 1 <= sample_index <= len(report.get("samples", [])): raise HTTPException(404,"NOT_FOUND")
        path=store.path("template-runs",run_id,f"sample-{sample_index}","reconstructed","reconstructed.pdf")
        if not path.is_file(): raise HTTPException(404,"NOT_FOUND")
        return FileResponse(path,media_type="application/pdf")

    @app.get("/api/v017/template-runs/{run_id}/comparison/{sample_index}/{mode}")
    def template_comparison(run_id: str, sample_index: int, mode: str):
        row=store.one("SELECT * FROM template_runs WHERE id=?",(run_id,))
        report=json.loads(row["report_json"])
        if not 1<=sample_index<=len(report.get("samples",[])) or mode not in {"reference","original","neutralized"}:
            raise HTTPException(404,"NOT_FOUND")
        folder=store.path("template-runs",run_id,f"sample-{sample_index}")
        candidates=list((folder/"reference").glob("*.pdf")) if mode=="reference" else [folder/"production"/mode/f"{mode}-formatted.pdf"]
        if len(candidates)!=1 or not candidates[0].is_file():raise HTTPException(404,"NOT_FOUND")
        return FileResponse(candidates[0],media_type="application/pdf")

    @app.get("/api/v017/template-runs/{run_id}/catalogue")
    def template_catalogue(run_id: str):
        row = store.one("SELECT * FROM template_runs WHERE id=?", (run_id,))
        report = json.loads(row["report_json"])
        if row["status"] != "passed": raise HTTPException(409,"CATALOGUE_NOT_VERIFIED")
        path=store.path("template-runs",run_id,"runtime-catalogues.zip")
        if path.is_file(): return FileResponse(path,filename="articleflow-runtime-catalogues.zip")
        temporary=path.with_name(_uid()+".zip")
        with ZipFile(temporary,"w",ZIP_DEFLATED) as archive:
            for index,sample in enumerate(report["samples"],1):
                for name in ("rules.json","resources.zip"):
                    source=store.path("template-runs",run_id,f"sample-{index}","catalogue","template",name)
                    archive.write(source,f"sample-{index}/{name}")
            archive.writestr("manifest.json",json.dumps({"schema":"catalogues-022","samples":[{**s["runtime_catalogue"],"path":f"sample-{i+1}"} for i,s in enumerate(report["samples"])],"transfer_validation":"not_measured"}))
        os.chmod(temporary,0o600)
        temporary.replace(path)
        return FileResponse(path,filename="articleflow-runtime-catalogues.zip")

    @app.post("/api/v017/templates/{template_id}/approve", dependencies=[Depends(csrf)])
    def approve(template_id: str, body: Approval):
        version = _latest(store, template_id)
        spec = json.loads(version["spec_json"])
        if spec.get("external_import") and not spec.get("agent023"):
            raise HTTPException(409, "EXTERNAL_IMPORT_REQUIRES_VALIDATION")
        selected = {}
        for role, variants in spec["variants"].items():
            choice = body.selected.get(role) or (next(iter(variants)) if len(variants) == 1 else None)
            if choice not in variants:
                raise HTTPException(409, {"code": "TEMPLATE_VARIANT_REVIEW", "role": role})
            selected[role] = choice
        if body.required is not None:
            if not set(body.required) <= set(SLOTS):
                raise HTTPException(400, "REQUIRED_SLOT_INVALID")
            spec.setdefault("structure", {})["required"] = body.required
        from .templatecheck021 import validate_samples
        profiles = {role: spec["styles"][role][key] for role, key in selected.items()}
        paths = sorted(store.path("templates", template_id, "samples").glob("*.docx"))
        try:
            check = validate_samples(paths, spec, profiles, store.path("templates", template_id, "layout-checks", _uid()))
        except Exception as exc:
            raise HTTPException(409, {"code": "TEMPLATE_LAYOUT_CHECK_UNAVAILABLE"}) from exc
        if check["status"] == "failed":
            raise HTTPException(409, {"code": "TEMPLATE_LAYOUT_MISMATCH", "validation": check})
        # The selected production profiles, not a different oracle renderer,
        # must pass. Never reuse evidence for another selection/required slots.
        run_id = _uid()
        store.execute("INSERT INTO template_runs VALUES (?,?,?,?,?,?)", (run_id,template_id,version["version"],"queued","{}",_now()))
        run_extraction(run_id, selected, spec.get("structure", {}).get("required", []))
        row = store.one("SELECT * FROM template_runs WHERE id=?", (run_id,))
        evidence = json.loads(row["report_json"])
        if row["status"] != "passed" or evidence.get("acceptance_contract") != "production-roundtrip-022-v1":
            raise HTTPException(409,{"code":"FULL_DOCUMENT_CHECK_FAILED", "run_id":run_id})
        spec["extraction_validation"] = evidence
        spec["extraction_run_id"] = run_id
        spec["layout_validation"] = check
        spec["selected"] = selected
        spec["approved"] = True
        with store.connect() as con:
            current=con.execute("SELECT MAX(version) FROM template_versions WHERE template_id=?",(template_id,)).fetchone()[0]
            if current != version["version"]: raise HTTPException(409,"TEMPLATE_VERSION_CHANGED")
            con.execute("INSERT INTO template_versions VALUES (?,?,?,?,?)",
                        (template_id, version["version"] + 1, json.dumps(spec, ensure_ascii=False), 1, _now()))
        return {"template_id": template_id, "version": version["version"] + 1, "approved": True}

    @app.get("/api/v017/batches")
    def list_batches():
        return store.all("""SELECT b.id,b.created_at,t.name AS template_name,COUNT(j.id) AS job_count
                            FROM batches b JOIN templates t ON t.id=b.template_id
                            LEFT JOIN jobs j ON j.batch_id=b.id GROUP BY b.id
                            ORDER BY b.created_at DESC,b.id DESC LIMIT 50""")

    @app.post("/api/v017/batches", dependencies=[Depends(csrf)])
    async def create_batch(background: BackgroundTasks, template_id: str = Form(...), files: list[UploadFile] = File(...), use_llm: bool = Form(False), consent_external: bool = Form(False)):
        if use_llm and (not consent_external or model_config() is None):
            raise HTTPException(400, "MODEL_CONSENT_OR_CONFIG_REQUIRED")
        version = _latest(store, template_id)
        if not version["approved"]:
            raise HTTPException(409, "TEMPLATE_NOT_APPROVED")
        if json.loads(version['spec_json']).get('agent023') and not use_llm:
            raise HTTPException(400,'AGENT_REQUIRES_MODEL_CONSENT')
        if not 1 <= len(files) <= MAX_BATCH:
            raise HTTPException(400, "BATCH_LIMIT")
        batch_id = _uid()
        jobs = []
        for upload in files:
            name = _safe_name(upload.filename)
            job_id = _uid()
            path = store.path("jobs", job_id, "source.docx")
            try:
                await _save_upload(upload, path)
            except DocumentError as exc:
                raise HTTPException(400, str(exc)) from exc
            jobs.append((job_id, name))
        with store.connect() as con:
            con.execute("INSERT INTO batches (id,template_id,template_version,created_at,use_llm) VALUES (?,?,?,?,?)", (batch_id, template_id, version["version"], _now(), int(use_llm)))
            for job_id, name in jobs:
                con.execute("INSERT INTO jobs (id,batch_id,source_name,status,created_at) VALUES (?,?,?,?,?)",
                            (job_id, batch_id, name, "queued", _now()))
        background.add_task(_process_batch, store, batch_id)
        return JSONResponse({"id": batch_id, "jobs": [jid for jid, _ in jobs]}, status_code=202)

    @app.get("/api/v017/batches/{batch_id}")
    def batch(batch_id: str):
        item = store.one("SELECT * FROM batches WHERE id=?", (batch_id,))
        item["jobs"] = store.all("SELECT id,source_name,status,revision,report_json FROM jobs WHERE batch_id=? ORDER BY created_at,id", (batch_id,))
        for job in item["jobs"]:
            job["report"] = json.loads(job.pop("report_json") or "null")
        return item

    @app.get("/api/v017/jobs/{job_id}")
    def job(job_id: str):
        item = store.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        item["report"] = json.loads(item.pop("report_json") or "null")
        item["assignments"] = json.loads(item.pop("assignments_json"))
        item["blocks"] = inventory(store.path("jobs", job_id, "source.docx"))["blocks"]
        return item

    @app.patch("/api/v017/jobs/{job_id}/decisions", dependencies=[Depends(csrf)])
    def decisions(job_id: str, body: Decisions):
        item = store.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        batch = store.one("SELECT * FROM batches WHERE id=?", (item['batch_id'],))
        version = store.one("SELECT * FROM template_versions WHERE template_id=? AND version=?", (batch['template_id'],batch['template_version']))
        if json.loads(version['spec_json']).get('agent023'):
            raise HTTPException(409, "AGENT_EDIT_SOURCE_OR_REQUIREMENTS")
        if item["status"] in {"queued", "processing"}:
            raise HTTPException(409, "JOB_IN_PROGRESS")
        if body.expected_revision != item["revision"]:
            raise HTTPException(409, "STALE_REVISION")
        if not set(body.assignments.values()) <= set(SLOTS) | {"editorial"}:
            raise HTTPException(400, "ROLE_ASSIGNMENT_INVALID")
        known = {b["id"] for b in inventory(store.path("jobs", job_id, "source.docx"))["blocks"]}
        if not set(body.assignments) <= known:
            raise HTTPException(400, "BLOCK_ID_INVALID")
        if any(k not in SLOTS or not isinstance(v,str) or not v.strip() or len(v)>10000 for k,v in body.supplied.items()):
            raise HTTPException(400, "SUPPLIED_DATA_INVALID")
        with store.connect() as con:
            updated = con.execute("UPDATE jobs SET revision=revision+1,assignments_json=?,supplied_json=?,status='queued' WHERE id=? AND revision=?",
                                  (json.dumps(body.assignments), json.dumps(body.supplied), job_id, body.expected_revision))
            if updated.rowcount != 1:
                raise HTTPException(409, "STALE_REVISION")
        with store.batch_lock:
            _process_job(store, job_id)
        return {"id": job_id, "revision": body.expected_revision + 1}

    @app.get("/api/v017/jobs/{job_id}/files/{kind}")
    def job_file(job_id: str, kind: str):
        item = store.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if kind == "source":
            path = store.path("jobs", job_id, "source.docx")
        elif kind in {"draft", "final", "report", "editorial"}:
            if kind == "final" and item["status"] != "ready":
                raise HTTPException(409, "NOT_READY")
            filename = "report.json" if kind == "report" else "editorial.docx" if kind == "editorial" else "result.docx"
            path = store.path("jobs", job_id, "revisions", str(item["revision"]), filename)
        else:
            raise HTTPException(404, "NOT_FOUND")
        if not path.is_file():
            raise HTTPException(404, "NOT_FOUND")
        return FileResponse(path, filename=f"{job_id}-{path.name}")

    @app.post("/api/v017/batches/{batch_id}/exports", dependencies=[Depends(csrf)])
    def create_export(batch_id: str):
        with store.batch_lock:
            store.one("SELECT id FROM batches WHERE id=?", (batch_id,))
            jobs = store.all("SELECT * FROM jobs WHERE batch_id=? ORDER BY created_at,id", (batch_id,))
            export_id = _uid()
            path = store.path("exports", f"{export_id}.zip")
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            manifest = {"batch_id": batch_id, "created_at": _now(), "jobs": []}
            with ZipFile(path, "w", ZIP_DEFLATED) as archive:
                for job in jobs:
                    manifest["jobs"].append({"id": job["id"], "source_name": job["source_name"],
                                             "status": job["status"], "revision": job["revision"]})
                    report = store.path("jobs", job["id"], "revisions", str(job["revision"]), "report.json")
                    if report.is_file():
                        archive.write(report, f"reports/{job['id']}.json")
                    else:
                        archive.writestr(f"reports/{job['id']}.json", json.dumps({"status": job["status"], "revision": job["revision"]}))
                    if job["status"] == "ready":
                        result = store.path("jobs", job["id"], "revisions", str(job["revision"]), "result.docx")
                        archive.write(result, f"results/{job['id']}.docx")
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            os.chmod(path, 0o600)
            store.execute("INSERT INTO exports VALUES (?,?,?)", (export_id, batch_id, manifest["created_at"]))
            return {"id": export_id, "url": f"/api/v017/exports/{export_id}", "manifest": manifest}

    @app.get("/api/v017/jobs/{job_id}/preview")
    def job_preview(job_id: str):
        job=store.one("SELECT * FROM jobs WHERE id=?",(job_id,))
        path=store.path("jobs",job_id,"revisions",str(job["revision"]),"visual","preview.pdf")
        if not path.is_file(): raise HTTPException(404,"PREVIEW_UNAVAILABLE")
        return FileResponse(path,media_type="application/pdf")

    @app.get("/api/v017/exports/{export_id}")
    def export(export_id: str):
        store.one("SELECT id FROM exports WHERE id=?", (export_id,))
        return FileResponse(store.path("exports", f"{export_id}.zip"), filename=f"articleflow-{export_id}.zip")

    from .webagent023 import mount
    mount(app,store,csrf)
    return app
