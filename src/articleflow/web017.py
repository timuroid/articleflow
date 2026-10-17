"""Single-owner Web 017 recovery slice: private FastAPI + SQLite + local files.

The app has no external model calls. Deploy only on loopback behind TLS and
owner authentication at the reverse proxy. Manuscript contents stay in data_dir.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import sqlite3
import subprocess
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
from .structure017 import SLOTS, compile_document, inspect_templates, inventory

MAX_DOCX = 25 * 1024 * 1024
MAX_BATCH = 200
MAX_TEMPLATES = 10
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


def _font_available(family: str) -> bool:
    try:
        result = subprocess.run(["fc-match", "-f", "%{family}\n", family], capture_output=True, text=True, timeout=5, check=True)
    except (FileNotFoundError, subprocess.SubprocessError):
        return False
    actual = result.stdout.splitlines()[0].split(",")[0].strip() if result.stdout else ""
    return actual.casefold() == family.casefold()


def font_audit() -> dict:
    families = {family: _font_available(family) for family in ("Arial", "Times New Roman")}
    return {"families": families, "exact": all(families.values())}


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


async def _save_upload(upload: UploadFile, path: Path):
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
        inventory(path)
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
        report = compile_document(source, output, assignments=json.loads(job["assignments_json"]),
                                  approved=bool(version["approved"]), fonts_ok=font_audit()["exact"],
                                  styles=styles, editorial_output=editorial)
        report["template_id"] = batch["template_id"]
        report["template_version"] = batch["template_version"]
        report["revision"] = revision
        report["font_audit"] = font_audit()
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
            except Exception:
                # The exception is intentionally not logged: parsers may include private text.
                store.execute("UPDATE jobs SET status='error', report_json=? WHERE id=?",
                              (json.dumps({"status": "error", "code": "INTERNAL_ERROR"}), job["id"]))


class Approval(BaseModel):
    selected: dict[str, str] = Field(default_factory=dict)


class Decisions(BaseModel):
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
        return {"status": "ok", "mode": "local_review_only"}

    @app.get("/")
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
                "max_template_files": MAX_TEMPLATES, "llm_enabled": False, "font_audit": font_audit()}

    @app.get("/api/v017/templates")
    def templates():
        return store.all("""SELECT t.id,t.name,t.created_at,v.version,v.approved,v.spec_json
                            FROM templates t JOIN template_versions v ON v.template_id=t.id
                            WHERE v.version=(SELECT MAX(version) FROM template_versions WHERE template_id=t.id)
                            ORDER BY t.created_at DESC""")

    @app.post("/api/v017/templates", dependencies=[Depends(csrf)])
    async def create_template(name: str = Form(...), files: list[UploadFile] = File(...)):
        if not 1 <= len(files) <= MAX_TEMPLATES or not 1 <= len(name.strip()) <= 120:
            raise HTTPException(400, "TEMPLATE_INPUT_INVALID")
        template_id = _uid()
        paths = []
        for index, upload in enumerate(files):
            _safe_name(upload.filename)
            path = store.path("templates", template_id, "samples", f"{index + 1}.docx")
            try:
                await _save_upload(upload, path)
            except DocumentError as exc:
                raise HTTPException(400, str(exc)) from exc
            paths.append(path)
        try:
            spec = inspect_templates(paths)
        except DocumentError as exc:
            raise HTTPException(400, str(exc)) from exc
        with store.connect() as con:
            con.execute("INSERT INTO templates VALUES (?,?,?)", (template_id, name.strip(), _now()))
            con.execute("INSERT INTO template_versions VALUES (?,?,?,?,?)",
                        (template_id, 1, json.dumps(spec, ensure_ascii=False), 0, _now()))
        return {"id": template_id, "version": 1, "spec": spec}

    @app.get("/api/v017/templates/{template_id}")
    def template(template_id: str):
        item = store.one("SELECT * FROM templates WHERE id=?", (template_id,))
        version = _latest(store, template_id)
        return {**item, "version": version["version"], "approved": bool(version["approved"]),
                "spec": json.loads(version["spec_json"])}

    @app.post("/api/v017/templates/{template_id}/approve", dependencies=[Depends(csrf)])
    def approve(template_id: str, body: Approval):
        version = _latest(store, template_id)
        spec = json.loads(version["spec_json"])
        selected = {}
        for role, variants in spec["variants"].items():
            choice = body.selected.get(role) or (next(iter(variants)) if len(variants) == 1 else None)
            if choice not in variants:
                raise HTTPException(409, {"code": "TEMPLATE_VARIANT_REVIEW", "role": role})
            selected[role] = choice
        spec["selected"] = selected
        spec["approved"] = True
        with store.connect() as con:
            con.execute("INSERT INTO template_versions VALUES (?,?,?,?,?)",
                        (template_id, version["version"] + 1, json.dumps(spec, ensure_ascii=False), 1, _now()))
        return {"template_id": template_id, "version": version["version"] + 1, "approved": True}

    @app.post("/api/v017/batches", dependencies=[Depends(csrf)])
    async def create_batch(background: BackgroundTasks, template_id: str = Form(...), files: list[UploadFile] = File(...)):
        version = _latest(store, template_id)
        if not version["approved"]:
            raise HTTPException(409, "TEMPLATE_NOT_APPROVED")
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
            con.execute("INSERT INTO batches VALUES (?,?,?,?)", (batch_id, template_id, version["version"], _now()))
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
        if item["status"] in {"queued", "processing"}:
            raise HTTPException(409, "JOB_IN_PROGRESS")
        if body.expected_revision != item["revision"]:
            raise HTTPException(409, "STALE_REVISION")
        if not set(body.assignments.values()) <= set(SLOTS) | {"editorial"}:
            raise HTTPException(400, "ROLE_ASSIGNMENT_INVALID")
        known = {b["id"] for b in inventory(store.path("jobs", job_id, "source.docx"))["blocks"]}
        if not set(body.assignments) <= known:
            raise HTTPException(400, "BLOCK_ID_INVALID")
        with store.connect() as con:
            updated = con.execute("UPDATE jobs SET revision=revision+1,assignments_json=?,status='queued' WHERE id=? AND revision=?",
                                  (json.dumps(body.assignments), job_id, body.expected_revision))
            if updated.rowcount != 1:
                raise HTTPException(409, "STALE_REVISION")
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
                if job["status"] == "ready":
                    result = store.path("jobs", job["id"], "revisions", str(job["revision"]), "result.docx")
                    archive.write(result, f"results/{job['id']}.docx")
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        os.chmod(path, 0o600)
        store.execute("INSERT INTO exports VALUES (?,?,?)", (export_id, batch_id, manifest["created_at"]))
        return {"id": export_id, "url": f"/api/v017/exports/{export_id}", "manifest": manifest}

    @app.get("/api/v017/exports/{export_id}")
    def export(export_id: str):
        store.one("SELECT id FROM exports WHERE id=?", (export_id,))
        return FileResponse(store.path("exports", f"{export_id}.zip"), filename=f"articleflow-{export_id}.zip")

    return app
