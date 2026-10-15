from __future__ import annotations

import argparse
import json
from pathlib import Path

from .docx_engine import inspect_document, lossless_split, lossless_rebuild, compare_content, render_roles, build_template
from .research import run_trials, render_pdf, compare_pixels, environment_manifest
from .catalogue import extract_catalogue, render_catalogue, placement_fingerprint
from .planner import model_view, compile_compact
from .planner_research import run_catalogue_trials


def main():
    parser = argparse.ArgumentParser(description="ArticleFlow research prototype; private data stays in the supplied output directory")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ["inspect", "lossless-split", "lossless-rebuild"]:
        cmd = commands.add_parser(name)
        cmd.add_argument("source", type=Path)
        cmd.add_argument("output", type=Path)
    render = commands.add_parser("render")
    render.add_argument("content_dir", type=Path)
    render.add_argument("template", type=Path)
    render.add_argument("plan", type=Path)
    render.add_argument("output", type=Path)
    template = commands.add_parser("build-template")
    for name in ["evidence_dir", "annotations", "definitions", "output"]:
        template.add_argument(name, type=Path)
    catalogue = commands.add_parser("extract-catalogue")
    for name in ["source", "annotations", "definitions", "output"]:
        catalogue.add_argument(name, type=Path)
    rebuild = commands.add_parser("render-catalogue")
    for name in ["template_dir", "content_dir", "plan", "output"]:
        rebuild.add_argument(name, type=Path)
    view = commands.add_parser("planner-input")
    for name in ["template_dir", "content_dir", "output"]:
        view.add_argument(name, type=Path)
    compile_ = commands.add_parser("compile-plan")
    for name in ["template_dir", "content_dir", "response", "output"]:
        compile_.add_argument(name, type=Path)
    planner_trials = commands.add_parser("catalogue-trials")
    for name in ["template_dir", "content_dir", "oracle_path", "source", "golden_pdf", "catalogue", "registry", "output", "ledger"]:
        planner_trials.add_argument(name, type=Path)
    planner_trials.add_argument("--model", default="openai/gpt-6.1-sol")
    planner_trials.add_argument("--key-file", type=Path)
    planner_trials.add_argument("--first", type=int, default=1)
    planner_trials.add_argument("--repeats", type=int, default=1)
    planner_trials.add_argument("--max-tokens", type=int, default=24000)
    planner_trials.add_argument("--reasoning-effort", default="medium")
    planner_trials.add_argument("--cap-usd", default="5")
    compare = commands.add_parser("compare")
    compare.add_argument("source", type=Path)
    compare.add_argument("candidate", type=Path)
    compare.add_argument("--golden-pdf", type=Path)
    compare.add_argument("--candidate-pdf", type=Path)
    pdf = commands.add_parser("pdf")
    pdf.add_argument("source", type=Path)
    pdf.add_argument("output", type=Path)
    commands.add_parser("environment")
    trials = commands.add_parser("trials")
    for name in ["content-dir", "template", "oracle", "source", "golden-pdf", "catalogue", "output"]:
        trials.add_argument("--" + name, type=Path, required=True)
    trials.add_argument("--model", required=True)
    trials.add_argument("--key-file", type=Path)
    trials.add_argument("--repeats", type=int, default=10)
    trials.add_argument("--cap-usd", default="5")
    trials.add_argument("--reasoning-effort", choices=["none", "minimal", "low", "medium", "high", "xhigh"])
    trials.add_argument("--max-tokens", type=int, default=14000)
    trials.add_argument("--model-registry", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "inspect":
        print(json.dumps(inspect_document(args.source, args.output), indent=2))
    elif args.command == "lossless-split":
        print(json.dumps(lossless_split(args.source, args.output), indent=2))
    elif args.command == "lossless-rebuild":
        lossless_rebuild(args.source, args.output)
    elif args.command == "render":
        render_roles(args.content_dir, json.loads(args.template.read_text()), json.loads(args.plan.read_text()), args.output)
    elif args.command == "build-template":
        definitions = json.loads(args.definitions.read_text())
        build_template(args.evidence_dir, json.loads(args.annotations.read_text()), definitions["roles"], args.output, definitions.get("inline_rules", []))
    elif args.command == "compare":
        if bool(args.golden_pdf) != bool(args.candidate_pdf):
            parser.error("--golden-pdf and --candidate-pdf must be provided together")
        result = compare_content(args.source, args.candidate)
        result["placements_exact"] = placement_fingerprint(args.source) == placement_fingerprint(args.candidate)
        if args.golden_pdf:
            result.update(compare_pixels(args.golden_pdf, args.candidate_pdf))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "extract-catalogue":
        print(json.dumps(extract_catalogue(args.source, json.loads(args.annotations.read_text()), json.loads(args.definitions.read_text()), args.output), indent=2))
    elif args.command == "render-catalogue":
        print(json.dumps(render_catalogue(args.template_dir, args.content_dir, json.loads(args.plan.read_text()), args.output), indent=2))
    elif args.command == "planner-input":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(model_view(args.template_dir, args.content_dir), ensure_ascii=False, indent=2))
    elif args.command == "compile-plan":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(compile_compact(args.template_dir, args.content_dir, json.loads(args.response.read_text())), ensure_ascii=False, indent=2))
    elif args.command == "catalogue-trials":
        options = vars(args).copy()
        options.pop("command")
        run_catalogue_trials(**options)
    elif args.command == "pdf":
        print(render_pdf(args.source, args.output))
    elif args.command == "environment":
        print(json.dumps(environment_manifest(), indent=2))
    elif args.command == "trials":
        run_trials(args.content_dir, args.template, args.oracle, args.source, args.golden_pdf, args.model, args.catalogue, args.output, args.key_file, args.repeats, args.cap_usd, args.reasoning_effort, args.max_tokens, args.model_registry)
