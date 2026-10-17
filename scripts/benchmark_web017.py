"""Offline evaluator 018. Gold labels never enter the application path.

Run from the repository venv. Private artifacts go to a NEW --output directory;
safe numeric results can be copied to docs/research. No API keys or model calls.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import itertools
import json
import platform
import statistics
import subprocess
import time
from collections import Counter
from pathlib import Path
from zipfile import ZipFile, ZIP_STORED

from lxml import etree as ET
from fastapi.testclient import TestClient

from articleflow.docx_engine import NS, W, DocumentError, load_package as application_load, parse_xml, xml_bytes
from articleflow.structure017 import inventory, suggest_roles, inspect_templates, compile_document
from articleflow.web017 import create_app, font_audit

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "datasets/synthetic-v1"
GOLD_ROLES = ["editorial", "title", "authors", "abstract_heading", "abstract_results",
              "abstract_problem", "abstract_practical", "abstract_goal", "keywords", "keywords"] + ["body"] * 11 + ["editorial"]
ABSTRACT_ORDER = ["abstract_problem", "abstract_goal", "abstract_results", "abstract_practical"]
ALLOWED_P = {"spacing", "ind", "jc", "keepNext", "keepLines", "pageBreakBefore", "widowControl"}
ALLOWED_R = {"rFonts", "sz", "szCs", "color"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def load_package(path):
    # Independent parser for known evaluator outputs. Record application import
    # rejection separately; it must not prevent measuring an otherwise valid ZIP.
    with ZipFile(path) as z:
        if sum(i.file_size for i in z.infolist()) > 250 * 1024**2:
            raise ValueError("evaluator ZIP size limit")
        if z.testzip() is not None:
            raise ValueError("evaluator ZIP CRC failure")
        return {name: z.read(name) for name in z.namelist()}


def body_nodes(path):
    parts = load_package(path)
    body = parse_xml(parts["word/document.xml"]).find("w:body", NS)
    return [n for n in body if n.tag != f"{{{W}}}sectPr"]


def canonical(node):
    # Expanded names avoid namespace-prefix artifacts; preserve attrs/text/order.
    return (node.tag, tuple(sorted(node.attrib.items())), node.text or "",
            tuple(canonical(child) for child in node))


def payload(node):
    node = copy.deepcopy(node)
    for pr in node.xpath(".//w:pPr | .//w:rPr", namespaces=NS):
        allowed = ALLOWED_P if ET.QName(pr).localname == "pPr" else ALLOWED_R
        for child in list(pr):
            if ET.QName(child).localname in allowed:
                pr.remove(child)
        if not len(pr) and not pr.attrib and not pr.text:
            pr.getparent().remove(pr)
    return canonical(node)


def conservation(source, output, editorial=None):
    before = body_nodes(source)
    after = body_nodes(output)
    if editorial and editorial.exists():
        after += body_nodes(editorial)
    placeholders = [n for n in after if "".join(n.itertext()).startswith("[ЗАПОЛНИТЬ:")]
    after = [n for n in after if n not in placeholders]
    checks = {"payload_exact": Counter(map(payload, before)) == Counter(map(payload, after))}
    for name in ("tbl", "oMath", "drawing", "hyperlink"):
        def objects(nodes):
            return Counter(canonical(e) for n in nodes for e in n.iter() if ET.QName(e).localname == name)
        checks[name + "_exact"] = objects(before) == objects(after)
    source_parts, out_parts = load_package(source), load_package(output)
    checks["non_document_parts_exact"] = ({k: v for k, v in source_parts.items() if k != "word/document.xml"}
                                            == {k: v for k, v in out_parts.items() if k != "word/document.xml"})
    checks["placeholder_count"] = len(placeholders)
    checks["all_payload_checks"] = all(v for k, v in checks.items() if k.endswith("exact"))
    try:
        application_load(output)
        checks["application_reimport"] = True
        checks["application_reimport_error"] = None
    except DocumentError as exc:
        checks["application_reimport"] = False
        checks["application_reimport_error"] = str(exc)
    return checks


def labels(entry, blocks):
    roles = list(GOLD_ROLES)
    if entry["kind"] == "missing_required":
        roles.pop(6)
        roles.pop(2)
    if len(roles) != len(blocks):
        raise ValueError("gold topology drift: " + entry["id"])
    return dict(zip((b["id"] for b in blocks), roles))


def scores(gold, predicted):
    correct = sum(gold[k] == predicted.get(k) for k in gold)
    return {"role_correct": correct, "role_total": len(gold), "role_accuracy": correct / len(gold),
            "roles_exact": correct == len(gold),
            "confusions": dict(Counter(f"{v}->{predicted.get(k)}" for k, v in gold.items() if predicted.get(k) != v))}


def abstract_order(path, source, gold):
    source_nodes = body_nodes(source)
    inv = inventory(source)
    expected = {payload(source_nodes[b["index"]]): gold[b["id"]] for b in inv["blocks"] if gold[b["id"]] in ABSTRACT_ORDER}
    return [expected[payload(n)] for n in body_nodes(path) if payload(n) in expected]


def percentile(values, quantile):
    values = sorted(values)
    index = (len(values) - 1) * quantile
    lo = int(index)
    return values[lo] + (values[min(lo + 1, len(values) - 1)] - values[lo]) * (index - lo)


def http_batches(folder, source):
    rows = []
    with TestClient(create_app(folder / "http-store")) as client:
        config = client.get("/api/v017/config").json()
        headers = {"X-CSRF-Token": config["csrf_token"]}
        sample = (CORPUS / "train/north-01.docx").read_bytes()
        res = client.post("/api/v017/templates", headers=headers, data={"name": "Benchmark 018"}, files={"files": ("train.docx", sample)})
        res.raise_for_status()
        tid, spec = res.json()["id"], res.json()["spec"]
        selected = {r: sorted(variants, key=lambda k: (-len(variants[k]), k))[0] for r, variants in spec["variants"].items()}
        client.post(f"/api/v017/templates/{tid}/approve", headers=headers, json={"selected": selected}).raise_for_status()
        data = source.read_bytes()
        for count in (1, 20, 200, 201):
            start = time.perf_counter()
            response = client.post("/api/v017/batches", headers=headers, data={"template_id": tid},
                                   files=[("files", (f"input-{i}.docx", data)) for i in range(count)])
            row = {"count": count, "http_status": response.status_code, "wall_seconds": time.perf_counter() - start}
            if response.status_code == 202:
                bid = response.json()["id"]
                jobs = client.get(f"/api/v017/batches/{bid}").json()["jobs"]
                row["statuses"] = dict(Counter(j["status"] for j in jobs))
                row["job_count_exact"] = len(jobs) == count
                row["final_blocked"] = all(client.get(f"/api/v017/jobs/{j['id']}/files/final").status_code == 409 for j in jobs)
                row["draft_zip_valid"] = all(ZipFile(io.BytesIO(client.get(f"/api/v017/jobs/{j['id']}/files/draft").content)).testzip() is None for j in jobs)
                export = client.post(f"/api/v017/batches/{bid}/exports", headers=headers).json()
                with ZipFile(io.BytesIO(client.get(export["url"]).content)) as archive:
                    row["zip_manifest_count"] = len(json.loads(archive.read("manifest.json"))["jobs"])
                    row["zip_results_count"] = sum(n.startswith("results/") for n in archive.namelist())
            rows.append(row)
            print(json.dumps({"phase": "http", **row}), flush=True)
    return rows


def run(output, private_reference=None, render=False, http=False):
    output.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((CORPUS / "manifest.json").read_text())
    for e in manifest["entries"]:
        if sha(CORPUS / e["path"]) != e["sha256"]:
            raise ValueError("corpus hash mismatch")
    summary = {"series": "018", "code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
               "evaluator_sha256": sha(__file__), "protocol_sha256": sha(ROOT / "docs/research/evaluation-018-protocol.md"),
               "corpus_manifest_sha256": sha(CORPUS / "manifest.json"), "python": platform.python_version(),
               "fonts": font_audit(), "model_calls": 0, "cost_usd": 0, "real_transfer": False}
    summary["implementation_sha256"] = {p.name: sha(p) for p in (ROOT / "src/articleflow/structure017.py", ROOT / "src/articleflow/web017.py", ROOT / "src/articleflow/docx_engine.py")}
    styles = {}
    for style in manifest["styles"]:
        spec = inspect_templates([CORPUS / e["path"] for e in manifest["entries"] if e["split"] == "train" and e["style"] == style])
        selected = {r: sorted(v, key=lambda k: (-len(v[k]), k))[0] for r, v in spec["variants"].items()}
        styles[style] = {r: spec["styles"][r][k] for r, k in selected.items()}
        summary.setdefault("template_choices", {})[style] = selected
    save(output / "frozen-config.json", summary)
    entries = [e for e in manifest["entries"] if e["kind"] in ("source", "missing_required")]
    attempts, rows = [], []
    for e in entries:
        source = CORPUS / e["path"]
        blocks = inventory(source)["blocks"]
        gold = labels(e, blocks)
        predictions, _ = suggest_roles(blocks)
        case = output / e["id"]
        case.mkdir()
        row = {"id": e["id"], **scores(gold, predictions)}
        for repeat in range(10):
            result = case / f"result-{repeat + 1}.docx"
            editorial = case / f"editorial-{repeat + 1}.docx"
            start = time.perf_counter()
            report = compile_document(source, result, approved=True, fonts_ok=summary["fonts"]["exact"], styles=styles[e["style"]], editorial_output=editorial)
            elapsed = (time.perf_counter() - start) * 1000
            check = conservation(source, result, editorial)
            attempts.append({"id": e["id"], "repeat": repeat + 1, "latency_ms": elapsed, "status": report["status"], **check})
            if repeat == 0:
                row.update(check)
                row.update({"status": report["status"], "missing": report["missing"], "editorial_blocks": report["editorial_blocks"],
                            "abstract_order": abstract_order(result, source, gold), "question_count": len(report["questions"])})
                row["abstract_order_correct"] = row["abstract_order"] == [r for r in ABSTRACT_ORDER if r in gold.values()]
                row["editorial_separation_exact"] = report["editorial_blocks"] == sum(r == "editorial" for r in gold.values())
        row["p50_ms"] = statistics.median(a["latency_ms"] for a in attempts if a["id"] == e["id"])
        rows.append(row)
    summary["documents"] = rows
    summary["attempts"] = attempts
    summary["aggregate"] = {"documents": len(rows), "payload_exact": sum(r["all_payload_checks"] for r in rows),
                            "roles_exact": sum(r["roles_exact"] for r in rows),
                            "role_correct": sum(r["role_correct"] for r in rows), "role_total": sum(r["role_total"] for r in rows),
                            "abstract_order_correct": sum(r["abstract_order_correct"] for r in rows),
                            "editorial_separation_exact": sum(r["editorial_separation_exact"] for r in rows),
                            "latency_p50_ms": statistics.median(a["latency_ms"] for a in attempts),
                            "latency_p95_ms": percentile([a["latency_ms"] for a in attempts], .95)}
    summary["aggregate"]["role_micro_f1"] = summary["aggregate"]["role_correct"] / summary["aggregate"]["role_total"]
    permutation_results = []
    original = CORPUS / "inputs/north-03.docx"
    parts = load_package(original)
    source_root = parse_xml(parts["word/document.xml"])
    source_body = source_root.find("w:body", NS)
    fragments = [copy.deepcopy(source_body[i]) for i in (4, 5, 6, 7)]
    permutation_dir = output / "permutations"
    permutation_dir.mkdir()
    for index, order in enumerate(itertools.permutations(range(4))):
        root = copy.deepcopy(source_root)
        body = root.find("w:body", NS)
        for offset, fragment in enumerate(order):
            body[4 + offset] = copy.deepcopy(fragments[fragment])
        changed = dict(parts, **{"word/document.xml": xml_bytes(root)})
        src, dst, editorial = (permutation_dir / f"{index}-{kind}.docx" for kind in ("input", "output", "editorial"))
        with ZipFile(src, "w", compression=ZIP_STORED) as archive:
            for name, data in changed.items():
                archive.writestr(name, data)
        blocks = inventory(src)["blocks"]
        perm_roles = list(GOLD_ROLES)
        perm_roles[4:8] = [GOLD_ROLES[4 + i] for i in order]
        gold = dict(zip((b["id"] for b in blocks), perm_roles))
        compile_document(src, dst, editorial_output=editorial)
        permutation_results.append({"permutation": list(order), "order_correct": abstract_order(dst, src, gold) == ABSTRACT_ORDER,
                                    **conservation(src, dst, editorial)})
    summary["permutations"] = permutation_results
    if private_reference:
        if sha(private_reference) != "2a299af6dea621444d6a90c9eb87c339f0a1b6baf1e8579d1ea0338d572f9e7e":
            raise ValueError("private reference hash mismatch")
        target, editorial = output / "private-result.docx", output / "private-editorial.docx"
        report = compile_document(private_reference, target, editorial_output=editorial)
        summary["private_reference"] = {"sha256": sha(private_reference), "status": report["status"],
                                         "source_blocks": report["source_blocks"], "missing": report["missing"],
                                         "question_count": len(report["questions"]), **conservation(private_reference, target, editorial)}
    save(output / "results.json", summary)
    print(json.dumps({"phase": "structure", **summary["aggregate"]}), flush=True)
    if http:
        summary["http_batches"] = http_batches(output, original)
        save(output / "results.json", summary)
    if render:
        # Caller pins PATH to bundled soffice. Existing renderer uses fresh LO profiles.
        from articleflow.research import render_pdf, raster_hashes, compare_pixels, environment_manifest
        summary["render_environment"] = environment_manifest()
        stability = []
        for i in range(10):
            pdf = render_pdf(CORPUS / "evaluation/north-03.docx", output / "stability" / str(i))
            stability.append(raster_hashes(pdf))
            print(json.dumps({"phase": "render_stability", "attempt": i + 1}), flush=True)
        summary["raster_stability"] = {"attempts": 10, "all_equal": all(s == stability[0] for s in stability), "hashes": stability}
        for row, e in zip(rows, entries):
            if "paired_reference" not in e:
                continue
            case = output / e["id"]
            reference = CORPUS / e["paired_reference"]
            result = case / "result-1.docx"
            golden_pdf = render_pdf(reference, case / "golden-pdf")
            result_pdf = render_pdf(result, case / "result-pdf")
            row["pixels"] = compare_pixels(golden_pdf, result_pdf)
            a, b = load_package(reference), load_package(result)
            row["styles_xml_exact"] = a["word/styles.xml"] == b["word/styles.xml"]
            row["section_exact"] = canonical(parse_xml(a["word/document.xml"]).find("w:body/w:sectPr", NS)) == canonical(parse_xml(b["word/document.xml"]).find("w:body/w:sectPr", NS))
            print(json.dumps({"phase": "pixels", "id": e["id"], "metrics": row["pixels"]}), flush=True)
        if private_reference:
            reference_pdf = render_pdf(private_reference, output / "private-golden-pdf")
            result_pdf = render_pdf(output / "private-result.docx", output / "private-result-pdf")
            summary["private_reference"]["pixels"] = compare_pixels(reference_pdf, result_pdf)
        save(output / "results.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--private-reference", type=Path)
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--http", action="store_true")
    args = parser.parse_args()
    run(args.output, args.private_reference, args.render, args.http)
