"""Controlled three-reference template study with a separate held-out document.

The DOCX files and all model responses stay in an ignored output directory.
Only aggregate counts from the emitted summary may be copied into public docs.
"""

from __future__ import annotations

import argparse
import json
import time
from decimal import Decimal
from pathlib import Path

from articleflow.agent023 import APPLICATION_INTEGRITY_GATES, apply, run
from articleflow.docx_engine import DocumentError, content_fingerprint, digest, dump
from articleflow.format032 import audit
from articleflow.provider023 import call
from articleflow.research import render_pdf
from articleflow.templateagent022 import compare_all


def summarize_attempts(folder: Path) -> dict:
    rows = [json.loads(path.read_text()) for path in folder.rglob("meta.json")]
    return {
        "api_attempts": sum(row.get("api_attempts", 0) for row in rows),
        "known_cost_usd": str(sum((Decimal(str(row["cost_usd"])) for row in rows
                                   if row.get("cost_usd") is not None), Decimal(0))),
        "unknown_cost_attempts": sum(row.get("api_attempts", 0) for row in rows
                                     if row.get("cost_usd") is None),
    }


def study(args: argparse.Namespace) -> dict:
    if len(args.reference) != 3 or len({p.resolve() for p in args.reference}) != 3:
        raise ValueError("EXACTLY_THREE_DISTINCT_REFERENCES_REQUIRED")
    if args.heldout_input is None and args.heldout_golden is not None or \
            args.heldout_input is not None and args.heldout_golden is None:
        raise ValueError("HELDOUT_PAIR_REQUIRED")
    for source in [*args.reference, *([args.heldout_input, args.heldout_golden]
                                  if args.heldout_input else [])]:
        if not source.is_file() or source.suffix.lower() != ".docx":
            raise ValueError("DOCX_INPUT_REQUIRED")
    if args.heldout_input and content_fingerprint(args.heldout_input) != content_fingerprint(args.heldout_golden):
        raise ValueError("HELDOUT_CONTENT_DIFFERS")
    args.output.mkdir(parents=True, exist_ok=False)
    protocol = {
        "schema": "hierarchy-three-reference-037",
        "references_sha256": [digest(p.read_bytes()) for p in args.reference],
        "heldout_input_sha256": digest(args.heldout_input.read_bytes()) if args.heldout_input else None,
        "heldout_golden_sha256": digest(args.heldout_golden.read_bytes()) if args.heldout_golden else None,
        "teacher_model": args.teacher_model,
        "student_model": args.student_model,
        "max_iterations": args.iterations,
        "max_api_calls": args.max_calls,
        "adaptive": True,
        "triage_conflicts": True,
        "span_grammar": args.span_grammar,
        "heldout_attempts": 1 if args.heldout_input else 0,
        "heldout_split": "independent_content",
        "heldout_protocol": args.heldout_protocol if args.heldout_input else None,
        "implementation_hashes": {p.name: digest(p.read_bytes()) for p in
                                  (Path(__file__).resolve().parents[1] / "src/articleflow").glob("*.py")},
        "runner_sha256": digest(Path(__file__).read_bytes()),
    }
    dump(args.output / "protocol.json", protocol)
    shared = {"key_file": str(args.key_file.resolve()),
              "ledger": str(args.ledger.resolve()), "series": args.series}
    calls = 0

    def bounded(*positional, **keyword):
        nonlocal calls
        if calls >= args.max_calls:
            raise DocumentError("AGENT_CALL_LIMIT")
        calls += 1
        return call(*positional, **keyword)

    started = time.monotonic()
    teacher = {**shared, "model": args.teacher_model,
               "reasoning_effort": args.teacher_effort,
               "triage_conflicts": True, "visual_review": False,
               "question_wait_seconds": 0,
               "span_grammar": args.span_grammar}
    student = {**shared, "model": args.student_model,
               "reasoning_effort": "none", "inline_repair_attempts": 0}
    result = run(args.reference, args.output / "learning", teacher, student,
                 max_iterations=args.iterations, caller=bounded, adaptive=True)
    summary = {
        "schema": "hierarchy-three-reference-037-summary",
        "status": result["status"], "code": result.get("code"),
        "reference_verified": result["status"] == "reference_verified",
        "iterations": [{"number": row["number"], "status": row["status"],
                        "training_conflicts": row.get("conflicting_groups"),
                        "student_skipped": row.get("student_skipped"),
                        "applications": [{"status": item.get("status"),
                                          "passed": item.get("passed"),
                                          "pixel_exact": item.get("pixels", {}).get("pixel_exact"),
                                          "property_exact": item.get("format", {}).get("property_exact")}
                                         for item in row.get("applications", [])]}
                       for row in result.get("iterations", [])],
        "heldout": {"status": "not_run", "reason": "template_not_verified"},
        "seconds": round(time.monotonic() - started, 3),
    }
    if result["status"] == "reference_verified" and args.heldout_input:
        source = args.heldout_input
        golden = args.heldout_golden
        try:
            trial = apply(source, Path(result["template"]), args.output / "heldout",
                          student, caller=bounded)
            heldout = {"status": trial["status"],
                       "unresolved_count": len(trial.get("unresolved", [])),
                       "model_invocations": trial.get("model_invocations"),
                       "integrity_gates": {name: trial.get(name) for name in APPLICATION_INTEGRITY_GATES}}
            if trial.get("pdf"):
                target = args.output / "heldout/result.docx"
                heldout["pixels"] = compare_all(render_pdf(golden, args.output / "heldout-golden"),
                                                 Path(trial["pdf"]), args.output / "heldout-diff")
                heldout["property_exact"] = audit(golden, target)["property_exact"]
            summary["heldout"] = {"status": heldout["status"],
                                  "unresolved_count": heldout["unresolved_count"],
                                  "model_invocations": heldout["model_invocations"],
                                  "integrity_gates": heldout["integrity_gates"],
                                  "pixel_exact": heldout.get("pixels", {}).get("pixel_exact"),
                                  "property_exact": heldout.get("property_exact")}
            dump(args.output / "heldout-summary.json", summary["heldout"])
        except DocumentError as exc:
            summary["heldout"] = {"status": "failed", "code": str(exc)}
    summary.update(summarize_attempts(args.output),
                   seconds=round(time.monotonic() - started, 3))
    dump(args.output / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", action="append", required=True, type=Path)
    parser.add_argument("--heldout-input", type=Path)
    parser.add_argument("--heldout-golden", type=Path)
    parser.add_argument("--heldout-protocol", choices=("I1", "I2"), default="I1")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=3, choices=range(1, 9))
    parser.add_argument("--max-calls", type=int, default=8)
    parser.add_argument("--teacher-effort", default="low", choices=("none", "low", "medium", "high"))
    parser.add_argument("--teacher-model", default="openai/gpt-6.1-sol")
    parser.add_argument("--student-model", default="qwen/qwen3.8-27b")
    parser.add_argument("--span-grammar", action="store_true",
                        help="Enable experimental source-independent inline selectors")
    parser.add_argument("--series", default="037-hierarchy-three-reference")
    print(json.dumps(study(parser.parse_args()), ensure_ascii=False))
