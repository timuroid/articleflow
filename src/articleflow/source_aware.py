"""I3 baseline: source formatting is an explicit input, never a hidden oracle."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from lxml import etree as ET

from .catalogue import extract_catalogue, render_catalogue, validate_catalogue_plan
from .context_rules import context_features, validate_rule_pack
from .docx_engine import W, DocumentError, digest, dump, parse_xml, compare_content

ROLE_VERSION = "source-roles-0.7"


def _signature(raw: list, group: str):
    """Ignore only declared mutable typography, not scientific emphasis."""
    def normalize(node):
        name = ET.QName(node).localname
        if name in {"sz", "szCs"} or (group == "paragraph" and name in {"spacing", "ind", "jc"}):
            return None
        attrs = dict(node.attrib)
        if name == "rFonts":
            for attr in ("ascii", "hAnsi", "cs"):
                attrs.pop(f"{{{W}}}{attr}", None)
        children = tuple(value for child in node if (value := normalize(child)) is not None)
        if not attrs and not children and name in {"rFonts", "rPr", "pPr"}:
            return None
        return node.tag, tuple(sorted(attrs.items())), children
    return tuple(value for xml in raw if (value := normalize(parse_xml(xml.encode()))) is not None)


def choose_source_style(group: str, observed: str, source_styles: dict, template: dict, allowed: list) -> tuple[str, str]:
    if observed in allowed:
        if source_styles[group][observed] != template["styles"][group][observed]:
            raise DocumentError("CATALOGUE_HASH_COLLISION")
        return observed, "preserved_allowed_source"
    if group not in {"paragraph", "character"}:
        raise DocumentError("SOURCE_VARIANT_UNKNOWN")
    signature = _signature(source_styles[group][observed], group)
    candidates = [key for key in allowed if _signature(template["styles"][group][key], group) == signature]
    if len(candidates) != 1:
        raise DocumentError("SOURCE_VARIANT_AMBIGUOUS" if candidates else "SOURCE_VARIANT_UNKNOWN")
    return candidates[0], "unique_typography_mapping"


def format_source(template_dir: Path, source: Path, role_plan: dict, output: Path,
                  pack: dict | None = None) -> dict:
    if output.exists() and any(output.iterdir()):
        raise DocumentError("OUTPUT_NOT_EMPTY")
    if role_plan.get("schema_version") != ROLE_VERSION or role_plan.get("source_sha256") != digest(source.read_bytes()):
        raise DocumentError("SOURCE_ROLE_PLAN_HASH")
    entries = role_plan["blocks"]
    if any(set(block) != {"id", "role"} for block in entries) or len({b["id"] for b in entries}) != len(entries):
        raise DocumentError("SOURCE_ROLE_PLAN_SCHEMA")
    template_raw = (template_dir / "rules.json").read_bytes()
    template = json.loads(template_raw)
    if not {b["role"] for b in entries} <= set(template["roles"]):
        raise DocumentError("SOURCE_ROLE_UNKNOWN")
    if pack is not None:
        validate_rule_pack(pack, template)
        if pack["template_sha256"] != digest(template_raw):
            raise DocumentError("RULE_TEMPLATE_HASH")
    output.mkdir(parents=True, exist_ok=True)
    report = {"protocol": "I3_source_docx", "mode": "source_aware_rebuild", "source_sha256": role_plan["source_sha256"],
              "strict_I1_eligible": False, "new_model_calls": 0, "target_oracle_used": False,
              "source_formatting_used": True, "status": "needs_review", "decisions": [], "unresolved": [],
              "template_status": template.get("status"), "independent_transfer_validated": False}
    input_dir = output / "input"
    extract_catalogue(source, {b["id"]: b["role"] for b in entries},
        {"roles": {name: value["description"] for name, value in template["roles"].items()}}, input_dir,
        source_observation=True)
    observed = json.loads((input_dir / "source-observations.json").read_text())
    source_template = json.loads((input_dir / "template/rules.json").read_text())
    if source_template["resource_sha256"] != template["resource_sha256"]:
        report["unresolved"].append({"reason": "SOURCE_RESOURCES_INCOMPATIBLE"})
        dump(output / "report.json", report)
        return report
    content = json.loads((input_dir / "content/content.json").read_text())
    features = context_features(content, observed)
    plan = copy.deepcopy(observed)
    plan.update(template_sha256=digest(template_raw), provenance="source_aware_I3")

    def decide(kind, item_id, group, source_style, allowed, field="style"):
        matches = [] if pack is None or kind is None else [r for r in pack["rules"]
            if r["kind"] == kind and all(features[kind][item_id].get(k) == v for k, v in r["when"].items())]
        if matches:
            rank = max(len(r["when"]) for r in matches)
            matches = [r for r in matches if len(r["when"]) == rank]
            choices = {r["set"][field] for r in matches}
            if len(choices) != 1:
                raise DocumentError("RULE_CONFLICT")
            chosen = choices.pop()
            reason = "context_rule"
        else:
            try:
                chosen, reason = choose_source_style(group, source_style, source_template["styles"], template, allowed)
            except DocumentError as exc:
                report["unresolved"].append({"kind": group, "id": item_id, "reason": str(exc)})
                return source_style
        report["decisions"].append({"kind": group, "id": item_id, "reason": reason, "changed": chosen != source_style})
        return chosen

    for block in plan["blocks"]:
        role = template["roles"][block["role"]]
        block["paragraph_style"] = decide("paragraph", block["id"], "paragraph", block["paragraph_style"], role["paragraph_styles"])
        for span in block["spans"]:
            span["style"] = decide(None, block["id"], "character", span["style"], role["character_styles"])
    for item in plan["layout"]:
        item["style"] = decide("layout", item["id"], item["kind"], item["style"], list(template["styles"][item["kind"]]))
    for item in plan["objects"]:
        item["drawing_style"] = decide("drawing", item["id"], "drawing", item["drawing_style"], list(template["styles"]["drawing"]), "drawing_style")
        item["run_style"] = decide("drawing", item["id"], "character", item["run_style"], list(template["styles"]["character"]), "run_style")
    plan["section_style"] = decide(None, "section", "section", plan["section_style"], list(template["styles"]["section"]))
    if not report["unresolved"]:
        validate_catalogue_plan(content, template, plan)
        dump(output / "plan.json", plan)
        render_catalogue(template_dir, input_dir / "content", plan, output / "candidate.docx")
        checks = compare_content(source, output / "candidate.docx")
        report["content_checks"] = checks["checks"]
        if checks["content_exact"]:
            report["status"] = "assembled_draft"
        else:
            (output / "candidate.docx").unlink()
            report["unresolved"].append({"reason": "SOURCE_CONTENT_CHANGED"})
    dump(output / "report.json", report)
    return report
