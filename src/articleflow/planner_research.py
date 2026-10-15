"""Budgeted catalogue trials with a separate, post-call oracle evaluator."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .catalogue import render_catalogue, placement_fingerprint
from .docx_engine import DocumentError, digest, dump, compare_content
from .planner import model_view, compact_messages, compact_schema, compile_compact, score_choices
from .research import one_model_call, validate_model_choice, render_pdf, compare_pixels


def run_catalogue_trials(*, template_dir: Path, content_dir: Path, oracle_path: Path,
                         source: Path, golden_pdf: Path, model: str, catalogue: Path,
                         registry: Path, output: Path, ledger: Path, key_file: Path | None,
                         first: int = 1, repeats: int = 1, cap_usd: str = "5",
                         max_tokens: int = 24000, reasoning_effort: str = "medium") -> list:
    if first < 1 or repeats < 1:
        raise DocumentError("INVALID_TRIAL_RANGE")
    # This function is a serial research runner, not a concurrent job scheduler.
    if not ledger.is_file():
        raise DocumentError("SHARED_LEDGER_REQUIRED")
    record = validate_model_choice(model, json.loads(registry.read_text()))
    models = {m["id"]: m for m in json.loads(catalogue.read_text())["data"]}
    config = models[model]
    if not {"reasoning", "structured_outputs"} <= set(config.get("supported_parameters", [])):
        raise DocumentError("MODEL_PARAMETERS_UNSUPPORTED")
    view = model_view(template_dir, content_dir)
    # Preserve the exact JSON ordering sent by the first attempt of a series.
    # Semantically equal dictionaries may have a different order across processes.
    view_path = output / "model-view.json"
    if view_path.exists():
        frozen_view = json.loads(view_path.read_text())
        if frozen_view != view:
            raise DocumentError("SERIES_INPUT_CHANGED")
        view = frozen_view
    template = json.loads((template_dir / "rules.json").read_text())
    messages, schema = compact_messages(view), compact_schema(template)
    frozen = {"model": model, "release": record, "reasoning_effort": reasoning_effort, "max_tokens": max_tokens,
        "template_sha256": digest((template_dir / "rules.json").read_bytes()),
        "input_sha256": digest((content_dir / "content.json").read_bytes()),
        "prompt_sha256": digest(json.dumps(messages, ensure_ascii=False).encode()),
        "schema_sha256": digest(json.dumps(schema, sort_keys=True).encode()),
        "pricing": config["pricing"], "protocol": "catalogue_choices_structured_payload", "strict_I1_eligible": False}
    upper = len(json.dumps({"messages": messages, "schema": schema}, ensure_ascii=False).encode()) + 8192
    output_limit = config.get("top_provider", {}).get("max_completion_tokens")
    if max_tokens < 1 or (output_limit and max_tokens > output_limit) or upper + max_tokens > config["context_length"]:
        raise DocumentError("CONTEXT_OVERFLOW")
    if any(upper >= int(tier["min_prompt_tokens"]) for tier in config["pricing"].get("overrides", [])):
        raise DocumentError("TIERED_PRICING_NOT_SUPPORTED")
    output.mkdir(parents=True, exist_ok=True)
    frozen_path = output / "series.json"
    if frozen_path.exists() and json.loads(frozen_path.read_text()) != frozen:
        raise DocumentError("SERIES_CONFIGURATION_CHANGED")
    dump(frozen_path, frozen)
    dump(view_path, view)
    dump(output / "response-schema.json", schema)
    results_path = output / "results.json"
    rows = json.loads(results_path.read_text()) if results_path.exists() else []
    for trial in range(first, first + repeats):
        run_id = f"{output.name}-{model.replace('/', '_')}-{trial:02d}"
        directory = output / run_id
        # Reserve in the historical ledger, and send exactly one HTTP attempt.
        meta = one_model_call(model=model, messages=messages, schema=schema, pricing=config["pricing"],
            key_file=key_file, run_dir=directory, ledger=ledger, cap_usd=cap_usd,
            max_tokens=max_tokens, temperature=None, reasoning_effort=reasoning_effort)
        row = {"run_id": run_id, "repeat": trial, **frozen, **meta,
            "eligible_for_strict_I1": False, "strict_I1_pass": False,
            "observed_full_match": False, "artifact_accepted": False}
        if meta["status"] == "schema_valid":
            try:
                response = json.loads((directory / "plan.json").read_text())
                plan = compile_compact(template_dir, content_dir, response)
                dump(directory / "compiled-plan.json", plan)
                target = directory / "candidate.docx"
                render_catalogue(template_dir, content_dir, plan, target)
                # Only the evaluator below reads the source oracle and golden.
                oracle = json.loads(oracle_path.read_text())
                content = json.loads((content_dir / "content.json").read_text())
                row.update(score_choices(plan, oracle, content))
                row.update(compare_content(source, target))
                row["placements_exact"] = placement_fingerprint(source) == placement_fingerprint(target)
                row.update(compare_pixels(golden_pdf, render_pdf(target, directory / "pdf")))
                row["observed_full_match"] = all(row[k] for k in ["content_exact", "inline_exact", "placements_exact", "pixel_exact", "roles_exact"])
                row["artifact_accepted"] = row["observed_full_match"]
                row["status"] = "evaluated"
            except DocumentError as exc:
                row.update(status="validation_failed", error_code=str(exc))
            except (subprocess.TimeoutExpired, OSError):
                row.update(status="render_failed", error_code="RENDER_ENVIRONMENT_FAILURE")
        dump(directory / "metrics.json", row)
        rows.append(row)
        dump(results_path, rows)
        print(json.dumps({k: row.get(k) for k in ["run_id", "status", "error_code", "content_exact", "pixel_exact", "paragraph_style_correct", "candidate_pages", "cost_usd"]}), flush=True)
        if meta.get("cost_usd") is None:
            # Unknown billing stays reserved; no further requests this invocation.
            break
    return rows
