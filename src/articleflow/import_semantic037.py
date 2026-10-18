"""Offline import of an externally authored, structured semantic candidate.

The imported JSON supplies labels and inline annotations, never executable
style-selection code.  Compilation uses the same validators and catalogue as
the managed teacher loop.  This entry point does not certify transfer quality.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections import Counter
from pathlib import Path

from .agent023 import build_package, extract_input
from .docx_engine import DocumentError, digest, dump
from .inline026 import overlay, validate as validate_inline
from .rules023 import semantic_spans
from .semantic023 import expand_groups


TEACHER_KEYS = frozenset({"roles", "groups", "inline_roles", "inline", "questions"})


def import_semantic_template(
    references: list[Path], teacher_json: Path, output: Path, *, span_grammar: bool = False
) -> dict:
    """Compile one to ten reference DOCX files and an exact teacher JSON plan.

    ``groups`` and ``inline.paragraph`` address the concatenated paragraph
    sequence in the supplied reference order.  An import with zero conflicts
    is still a draft: neither an unseen document nor a student has been tested.
    """
    if not 1 <= len(references) <= 10:
        raise DocumentError("IMPORT_REFERENCE_LIMIT")
    if type(span_grammar) is not bool:
        raise DocumentError("SPAN_GRAMMAR_MODE")
    references = [Path(path) for path in references]
    teacher_json, output = Path(teacher_json), Path(output)
    if output.exists() or output.is_symlink():
        raise DocumentError("OUTPUT_ALREADY_EXISTS")
    for source in references:
        if source.suffix.lower() != ".docx" or not source.is_file():
            raise DocumentError("IMPORT_REFERENCE_INVALID")
    if not teacher_json.is_file():
        raise DocumentError("IMPORT_TEACHER_JSON_MISSING")
    raw = teacher_json.read_bytes()
    try:
        candidate = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError):
        raise DocumentError("IMPORT_TEACHER_JSON_INVALID") from None
    if not isinstance(candidate, dict) or set(candidate) != TEACHER_KEYS:
        raise DocumentError("IMPORT_TEACHER_SCHEMA")

    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
    published = False
    try:
        samples = []
        blocks = []
        for index, source in enumerate(references):
            extracted = stage / f"reference-{index + 1}" / "extracted"
            content = extract_input(source, extracted)
            samples.append({"source": source, "extracted": extracted, "content": content})
            blocks.extend({"id": f"{index}:{block['id']}", "text": block["text"]}
                          for block in content["blocks"])
        # Both validators are deliberately the same ones used by agent023.run.
        assignments = expand_groups(candidate, blocks)
        inline = validate_inline(candidate, blocks)
        labels = []
        role_counts = Counter()
        inline_counts = Counter()
        per_reference = []
        for index, sample in enumerate(samples):
            content = sample["content"]
            local_labels = {block["id"]: assignments[f"{index}:{block['id']}"]
                            for block in content["blocks"]}
            marks = {block["id"]: inline[f"{index}:{block['id']}"]
                     for block in content["blocks"]}
            semantics = semantic_spans(sample["source"])
            sample["semantics"] = overlay(semantics, marks) if candidate["inline_roles"] else semantics
            labels.append(local_labels)
            counts = Counter(local_labels.values())
            role_counts.update(counts)
            inline_counts.update(mark["role"] for spans in marks.values() for mark in spans)
            per_reference.append({"sha256": digest(sample["source"].read_bytes()),
                                  "paragraphs": len(content["blocks"]),
                                  "role_counts": dict(sorted(counts.items()))})

        package, conflicts = build_package(
            samples, labels, candidate["roles"], stage / "template",
            candidate["inline_roles"], span_grammar=span_grammar,
        )
        if package["status"] != "draft" or package["unresolved_training_groups"] != len(conflicts):
            raise DocumentError("IMPORT_PACKAGE_INVARIANT")
        report = {
            "schema": "external-semantic-import-037",
            "provenance": "external_candidate",
            "status": "needs_review" if conflicts else "draft_compiled",
            "certification": "not_evaluated_on_unseen_documents",
            "model_calls": 0,
            "teacher_json_sha256": digest(raw),
            "teacher_candidate": "teacher.json",
            "references": per_reference,
            "paragraphs": len(blocks),
            "role_counts": dict(sorted(role_counts.items())),
            "inline_role_counts": dict(sorted(inline_counts.items())),
            "questions": candidate["questions"],
            "span_grammar": span_grammar,
            "template_dir": "template",
            "training_conflicts": len(conflicts),
            "conflict_counts": dict(sorted(Counter(row["kind"] for row in conflicts).items())),
            "conflicts": conflicts,
        }
        # Preserve the exact external candidate so a later reviewer can replay
        # the import without treating its prose fields as executable rules.
        (stage / "teacher.json").write_bytes(raw)
        dump(stage / "report.json", report)
        if output.exists() or output.is_symlink():
            raise DocumentError("OUTPUT_ALREADY_EXISTS")
        os.rename(stage, output)
        published = True
        return report
    finally:
        if not published:
            shutil.rmtree(stage, ignore_errors=True)
