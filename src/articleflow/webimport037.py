"""Verification of an imported semantic candidate before explicit web approval.

This uses the frozen imported package. It makes no teacher call and never
claims held-out transfer from replaying neutralized reference documents.
"""
from __future__ import annotations

import json
from pathlib import Path

from .agent023 import APPLICATION_INTEGRITY_GATES, application_passed, apply
from .docx_engine import DocumentError, digest
from .inline026 import validate as validate_inline
from .semantic023 import expand_groups


def _aligned(original: list[dict], incoming: list[dict]) -> list[dict]:
    """Align removed empty layout paragraphs without content-based guessing."""
    def signature(block):
        return block["text"], [atom["kind"] for atom in block["atoms"] if atom["kind"] != "text"]

    result, cursor = [], 0
    for block in incoming:
        while cursor < len(original) and signature(original[cursor]) != signature(block):
            old = original[cursor]
            if old["text"] or old["atoms"]:
                raise DocumentError("EVALUATION_CONTENT_ALIGNMENT")
            cursor += 1
        if cursor == len(original):
            raise DocumentError("EVALUATION_CONTENT_ALIGNMENT")
        result.append(original[cursor])
        cursor += 1
    if any(block["text"] or block["atoms"] for block in original[cursor:]):
        raise DocumentError("EVALUATION_CONTENT_ALIGNMENT")
    return result


def verify_import(references: list[Path], teacher_json: Path, imported_root: Path,
                  work: Path, student_config: dict, *, progress=None) -> dict:
    """Replay every reference from neutralized DOCX and measure exact gates."""
    from .controls023 import verify as negative_controls
    from .format032 import audit as audit_format
    from .research import render_pdf
    from .roundtrip022 import neutralize
    from .templateagent022 import compare_all

    imported = json.loads((imported_root / "report.json").read_text())
    template = imported_root / "template"
    package = json.loads((template / "semantic.json").read_text())
    if imported["training_conflicts"] or package["unresolved_training_groups"]:
        raise DocumentError("IMPORT_CONFLICTS_UNRESOLVED")
    if len(references) != len(imported["references"]):
        raise DocumentError("IMPORT_REFERENCE_CHANGED")
    hashes = {part: digest((template / part).read_bytes())
              for part in ("rules.json", "semantic.json", "resources.zip")}
    if [digest(path.read_bytes()) for path in references] != [row["sha256"] for row in imported["references"]]:
        raise DocumentError("IMPORT_REFERENCE_CHANGED")
    if digest(teacher_json.read_bytes()) != imported["teacher_json_sha256"]:
        raise DocumentError("IMPORT_TEACHER_CHANGED")

    teacher = json.loads(teacher_json.read_text())
    sources = []
    blocks = []
    for number, _ in enumerate(references, 1):
        content = json.loads((imported_root / f"reference-{number}" / "extracted" / "content" / "content.json").read_text())
        sources.append(content)
        blocks.extend({"id": f"{number-1}:{block['id']}", "text": block["text"]}
                      for block in content["blocks"])
    labels = expand_groups(teacher, blocks)
    marks = validate_inline(teacher, blocks)
    work.mkdir(parents=True, exist_ok=False)
    report = {
        "schema": "external-import-verification-037", "status": "running",
        "provenance": "external_candidate", "input_protocol": "neutralized_reference_docx",
        "source_hashes": [digest(path.read_bytes()) for path in references],
        "teacher_json_sha256": imported["teacher_json_sha256"],
        "package_hashes": hashes, "student_model": student_config["model"],
        "samples": [], "negative_controls": [], "model_invocations": 0,
        "held_out_transfer": "not_measured", "approved": False,
        "certification": {"neutralized_references_exact": False,
                          "format_properties_exact": False,
                          "negative_controls_detected": False,
                          "scope": "neutralized_references_only",
                          "universal_accuracy_proven": False},
    }
    if progress:
        progress(report)
    for number, (reference, original) in enumerate(zip(references, sources), 1):
        sample_root = work / f"sample-{number}"
        sample_root.mkdir()
        golden = render_pdf(reference, sample_root / "reference")
        incoming = sample_root / "neutralized.docx"
        neutralize(reference, incoming)
        row = {"document": number, "status": "running", "passed": False,
               "student_call_attempted": True}
        report["samples"].append(row)
        if progress:
            progress(report)
        try:
            trial = apply(incoming, template, sample_root / "application", student_config)
            report["model_invocations"] += trial.get("model_invocations", 1)
            row.update(status=trial["status"], unresolved=trial.get("unresolved", []),
                       strict_one_pass_eligible=trial.get("strict_one_pass_eligible", False))
            new = json.loads((sample_root / "application" / "input-original.json").read_text())
            aligned = _aligned(original["blocks"], new["blocks"])
            expected_roles = [labels[f"{number-1}:{block['id']}"] for block in aligned]
            predicted_roles = [trial["assignments"][block["id"]] for block in new["blocks"]]
            row["role_total"] = len(expected_roles)
            row["role_correct"] = sum(a == b for a, b in zip(expected_roles, predicted_roles))
            response = json.loads((sample_root / "application" / "effective-student.json").read_text())
            predicted_inline = validate_inline(response, new["blocks"], package.get("inline_roles", {}))
            expected_inline = [marks[f"{number-1}:{block['id']}"] for block in aligned]
            actual_inline = [predicted_inline[block["id"]] for block in new["blocks"]]
            row["inline_total"] = len(expected_inline)
            row["inline_correct"] = sum(a == b for a, b in zip(expected_inline, actual_inline))
            row["inline_exact"] = row["inline_correct"] == row["inline_total"]
            row["integrity_failures"] = [gate for gate in APPLICATION_INTEGRITY_GATES
                                         if trial.get(gate) is not True]
            if trial.get("pdf"):
                row["pixels"] = compare_all(golden, Path(trial["pdf"]), sample_root / "diff")
                row["format"] = audit_format(reference, sample_root / "application" / "result.docx")
            row["passed"] = (not row["unresolved"] and row["inline_exact"] and
                             application_passed(row, trial))
            row["status"] = "passed" if row["passed"] else "needs_review"
        except DocumentError as exc:
            row.update(status="failed", code=str(exc), passed=False)
        if progress:
            progress(report)
        if not row["passed"]:
            report["status"] = "needs_review"
            return report

    controls = []
    for number, reference in enumerate(references, 1):
        sample_root = work / f"sample-{number}"
        control_root = sample_root / "negative-controls"
        control_root.mkdir()
        golden = next((sample_root / "reference").glob("*.pdf"))
        controls.extend({"document": number, **control}
                        for control in negative_controls(reference, golden, control_root))
    report["negative_controls"] = controls
    exact = bool(controls) and all(control.get("detected") is True for control in controls)
    report["certification"].update(
        neutralized_references_exact=True, format_properties_exact=True,
        negative_controls_detected=exact)
    report["status"] = "reference_replay_passed" if exact else "needs_review"
    if progress:
        progress(report)
    return report
