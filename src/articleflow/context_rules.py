"""Observed context rules and explicit source-index payload; no oracle at apply time."""
from __future__ import annotations

import copy
import json
import shutil
from collections import defaultdict
from pathlib import Path

from lxml import etree as ET

from .catalogue import Catalogue, validate_catalogue_plan
from .docx_engine import NS, W, DocumentError, digest, dump, parse_xml, emphasis_masks, content_fingerprint

RULE_VERSION = "context-rules-0.6"
ALLOWED = {
    "role", "previous_role", "next_role", "in_table", "empty", "has_math", "has_drawing",
    "kind", "roles", "table_roles", "row_cells", "cell_band", "object_kind",
}


def _key(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def context_features(content: dict, plan: dict) -> dict:
    roles = {b["id"]: b["role"] for b in plan["blocks"]}
    if len(roles) != len(plan["blocks"]) or set(roles) != {b["id"] for b in content["blocks"]}:
        raise DocumentError("RULE_ROLE_COVERAGE")
    paragraphs, layouts, objects = {}, {}, {}
    def descend_roles(node):
        if node["kind"] == "paragraph":
            return [roles[node["id"]]]
        return [r for child in node.get("children", []) for r in descend_roles(child)]
    def walk(nodes, table_roles="", row_cells=0, cell_band="outside"):
        for n in nodes:
            kind = n["kind"]
            if kind == "marker":
                continue
            if kind == "paragraph":
                paragraphs[n["id"]] = {"in_table": bool(table_roles), "table_roles": table_roles, "row_cells": row_cells, "cell_band": cell_band}
                continue
            tr = ",".join(sorted(set(descend_roles(n)))) if kind == "table" else table_roles
            count = len([c for c in n.get("children", []) if c["kind"] == "cell"]) if kind == "row" else row_cells
            layouts[n["id"]] = {"kind": kind, "roles": ",".join(sorted(set(descend_roles(n)))), "table_roles": tr,
                "row_cells": count if kind in {"row", "cell"} else 0, "cell_band": cell_band if kind == "cell" else "outside"}
            if kind == "row":
                cells = [c for c in n["children"] if c["kind"] == "cell"]
                for i, child in enumerate(cells):
                    band = "only" if len(cells) == 1 else "first" if i == 0 else "last" if i == len(cells) - 1 else "middle"
                    walk([child], tr, count, band)
            else:
                walk(n.get("children", []), tr, count, cell_band)
    walk(content["structure"])
    def object_atoms(atoms):
        for a in atoms:
            if a["kind"] in {"drawing", "math"}:
                yield a
            yield from object_atoms(a.get("children", []))
    for i, b in enumerate(content["blocks"]):
        events = list(object_atoms(b["atoms"]))
        f = paragraphs[b["id"]]
        f.update(role=roles[b["id"]], previous_role=roles[content["blocks"][i-1]["id"]] if i else "START",
            next_role=roles[content["blocks"][i+1]["id"]] if i+1 < len(content["blocks"]) else "END",
            empty=not bool(b["text"]), has_math=any(a["kind"] == "math" for a in events), has_drawing=any(a["kind"] == "drawing" for a in events))
        for a in events:
            if a["kind"] == "drawing":
                objects[a["object_id"]] = {k: f[k] for k in ["role", "in_table", "table_roles", "row_cells", "cell_band"]} | {"object_kind": "drawing"}
    return {"paragraph": paragraphs, "layout": layouts, "drawing": objects}


def fit_rules(template: dict, content: dict, oracle: dict, template_hash: str) -> tuple[dict, dict]:
    """Preparation from specimen observations. No assignments go into runtime rules."""
    if oracle["template_sha256"] != template_hash:
        raise DocumentError("RULE_TRAINING_TEMPLATE_HASH")
    validate_catalogue_plan(content, template, oracle)
    features = context_features(content, oracle)
    targets = {
        "paragraph": {b["id"]: {"style": b["paragraph_style"]} for b in oracle["blocks"]},
        "layout": {b["id"]: {"style": b["style"]} for b in oracle["layout"]},
        "drawing": {b["id"]: {"drawing_style": b["drawing_style"], "run_style": b["run_style"]} for b in oracle["objects"]},
    }
    rules, conflicts = [], []
    for kind, entries in features.items():
        groups = defaultdict(list)
        for item_id, f in entries.items():
            condition = {"role": f["role"]} if kind == "paragraph" and len(template["roles"][f["role"]]["paragraph_styles"]) == 1 else f
            groups[_key(condition)].append((item_id, targets[kind][item_id]))
        for condition, examples in sorted(groups.items()):
            choices = {_key(target) for _, target in examples}
            if len(choices) != 1:
                conflicts.append({"kind": kind, "when": json.loads(condition), "observations": len(examples), "variants": len(choices)})
                continue
            item = {"kind": kind, "when": json.loads(condition), "set": examples[0][1]}
            rules.append({"id": "rule-" + digest(_key(item).encode())[:16], **item, "support": len(examples), "status": "observed_only"})
    pack = {"schema_version": RULE_VERSION, "template_sha256": template_hash, "status": "research_draft",
        "method": "unanimous_role_or_structural_context", "rules": rules,
        "ambiguous_groups": conflicts, "independent_validation": False}
    audit = {"rules": len(rules), "single_observation_rules": sum(r["support"] == 1 for r in rules),
        "ambiguous_groups": len(conflicts), "ambiguous_observations": sum(r["observations"] for r in conflicts),
        "by_kind": {kind: {"rules": sum(r["kind"] == kind for r in rules), "resolved_training_items": sum(r["support"] for r in rules if r["kind"] == kind), "ambiguous_training_items": sum(r["observations"] for r in conflicts if r["kind"] == kind)} for kind in features}}
    return pack, audit


def validate_rule_pack(pack: dict, template: dict) -> None:
    if pack.get("schema_version") != RULE_VERSION:
        raise DocumentError("RULE_VERSION")
    seen = set()
    for rule in pack["rules"]:
        if rule["id"] in seen:
            raise DocumentError("RULE_DUPLICATE_ID")
        seen.add(rule["id"])
        if rule["kind"] not in {"paragraph", "layout", "drawing"} or not rule["when"] or not set(rule["when"]) <= ALLOWED:
            raise DocumentError("RULE_CONDITION_NOT_ALLOWED")
        target = rule["set"]
        if rule["kind"] == "paragraph":
            role = template["roles"].get(rule["when"].get("role"))
            if set(target) != {"style"} or role is None or target["style"] not in role["paragraph_styles"]:
                raise DocumentError("RULE_TARGET_INVALID")
        elif rule["kind"] == "layout":
            group = rule["when"].get("kind")
            if group not in {"table", "row", "cell"} or set(target) != {"style"} or target["style"] not in template["styles"][group]:
                raise DocumentError("RULE_TARGET_INVALID")
        elif set(target) != {"drawing_style", "run_style"} or target["drawing_style"] not in template["styles"]["drawing"] or target["run_style"] not in template["styles"]["character"]:
            raise DocumentError("RULE_TARGET_INVALID")


def apply_context_rules(template: dict, content: dict, plan: dict, pack: dict) -> tuple[dict, dict]:
    validate_catalogue_plan(content, template, plan)
    validate_rule_pack(pack, template)
    if pack["template_sha256"] != plan["template_sha256"]:
        raise DocumentError("RULE_TEMPLATE_HASH")
    features = context_features(content, plan)
    result = copy.deepcopy(plan)
    applied, unresolved = [], []
    for kind, items in [("paragraph", result["blocks"]), ("layout", result["layout"]), ("drawing", result["objects"])]:
        for item in items:
            f = features[kind][item["id"]]
            matches = [r for r in pack["rules"] if r["kind"] == kind and all(f.get(k) == v for k, v in r["when"].items())]
            if not matches:
                unresolved.append({"kind": kind, "id": item["id"], "reason": "no_unambiguous_context_rule"})
                continue
            rank = max(len(r["when"]) for r in matches)
            matches = [r for r in matches if len(r["when"]) == rank]
            if len({_key(r["set"]) for r in matches}) != 1:
                raise DocumentError("RULE_CONFLICT")
            chosen = sorted(matches, key=lambda r: r["id"])[0]
            action = {"paragraph_style": chosen["set"]["style"]} if kind == "paragraph" else chosen["set"]
            changed = any(item.get(k) != v for k, v in action.items())
            item.update(action)
            applied.append({"kind": kind, "id": item["id"], "rule_id": chosen["id"], "changed": changed})
    result["provenance"] = "model_with_observed_context_rules"
    validate_catalogue_plan(content, template, result)
    return result, {"applied": applied, "unresolved": unresolved, "needs_review": bool(unresolved) or pack.get("status") != "approved"}


def extract_indices(source: Path, content_path: Path) -> dict:
    raw = content_path.read_bytes()
    content = json.loads(raw)
    fingerprints = content_fingerprint(source)
    if fingerprints["paragraphs"] != [b["text"] for b in content["blocks"]]:
        raise DocumentError("SEMANTICS_SOURCE_TEXT_MISMATCH")
    masks = emphasis_masks(source)
    blocks = []
    for b, mask in zip(content["blocks"], masks):
        if len(mask) != len(b["text"]):
            raise DocumentError("SEMANTICS_SOURCE_LENGTH")
        spans = []
        for i, flags in enumerate(mask):
            vertical = flags[2]
            if vertical == "baseline":
                continue
            if spans and spans[-1]["end"] == i and spans[-1]["vertical"] == vertical:
                spans[-1]["end"] = i + 1
            else:
                spans.append({"start": i, "end": i + 1, "vertical": vertical})
        blocks.append({"id": b["id"], "length": len(b["text"]), "indices": spans})
    return {"schema_version": "source-indices-0.6", "protocol": "explicit_source_vertical_I2_like",
        "input_sha256": digest(raw), "source_sha256": digest(source.read_bytes()), "blocks": blocks}


def expand_vertical_styles(template: dict) -> tuple[dict, dict]:
    result = copy.deepcopy(template)
    cat = Catalogue()
    mapping = {}
    for key, raw in template["styles"]["character"].items():
        mapping[key] = {}
        if len(raw) > 1:
            raise DocumentError("CHARACTER_PROPERTIES_MULTIPLE")
        for value in ["baseline", "superscript", "subscript"]:
            node = parse_xml(raw[0].encode()) if raw else ET.Element(f"{{{W}}}rPr", nsmap={"w": W})
            for element in list(node.findall("w:vertAlign", NS)):
                node.remove(element)
            ET.SubElement(node, f"{{{W}}}vertAlign", {f"{{{W}}}val": value})
            mapped = cat.add("character", [node])
            mapping[key][value] = mapped
    result["styles"]["character"].update(cat.styles["character"])
    for role in result["roles"].values():
        role["character_styles"] = sorted(set(role["character_styles"]) | {mapped for key in role["character_styles"] for mapped in mapping[key].values()})
    result["vertical_policy"] = "explicit_source_indices_0.6"
    return result, mapping


def apply_indices(content: dict, plan: dict, semantics: dict, mapping: dict) -> dict:
    if semantics.get("schema_version") != "source-indices-0.6" or semantics["input_sha256"] != plan["input_sha256"]:
        raise DocumentError("SEMANTICS_INPUT_HASH")
    if [b["id"] for b in semantics["blocks"]] != [b["id"] for b in content["blocks"]]:
        raise DocumentError("SEMANTICS_COVERAGE")
    source = {b["id"]: b for b in semantics["blocks"]}
    texts = {b["id"]: b["text"] for b in content["blocks"]}
    result = copy.deepcopy(plan)
    for b in result["blocks"]:
        item = source[b["id"]]
        length = len(texts[b["id"]])
        if item["length"] != length:
            raise DocumentError("SEMANTICS_LENGTH")
        mask, previous = ["baseline"] * length, 0
        for s in item["indices"]:
            a, z = s["start"], s["end"]
            if type(a) is not int or type(z) is not int or not previous <= a < z <= length or s["vertical"] not in {"superscript", "subscript"}:
                raise DocumentError("SEMANTICS_RANGE")
            mask[a:z] = [s["vertical"]] * (z-a)
            previous = z
        spans = []
        for s in b["spans"]:
            for offset in range(s["start"], s["end"]):
                style = mapping[s["style"]][mask[offset]]
                if spans and spans[-1]["end"] == offset and spans[-1]["style"] == style:
                    spans[-1]["end"] = offset + 1
                else:
                    spans.append({"start": offset, "end": offset + 1, "style": style})
        b["spans"] = spans
    result["provenance"] = "model_context_rules_with_source_indices"
    return result


def transform_plan(template_dir: Path, content_dir: Path, plan: dict, pack: dict | None,
                   semantics: dict | None, output: Path) -> dict:
    if output.exists() and any(output.iterdir()):
        raise DocumentError("OUTPUT_NOT_EMPTY")
    raw = (template_dir / "rules.json").read_bytes()
    content_raw = (content_dir / "content.json").read_bytes()
    if digest(raw) != plan["template_sha256"] or digest(content_raw) != plan["input_sha256"]:
        raise DocumentError("PLAN_INPUT_HASH")
    template, content = json.loads(raw), json.loads(content_raw)
    validate_catalogue_plan(content, template, plan)
    result = copy.deepcopy(plan)
    report = {"mode": "offline_replay", "new_model_calls": 0, "strict_I1_eligible": False,
        "source_indices_used": semantics is not None, "rules_used": pack is not None,
        "applied": [], "unresolved": [], "needs_review": True}
    if pack is not None:
        result, changes = apply_context_rules(template, content, result, pack)
        report.update(changes)
    if semantics is not None:
        template, mapping = expand_vertical_styles(template)
        result = apply_indices(content, result, semantics, mapping)
    validate_catalogue_plan(content, template, result)
    target = output / "template"
    target.mkdir(parents=True, exist_ok=True)
    dump(target / "rules.json", template)
    shutil.copyfile(template_dir / "resources.zip", target / "resources.zip")
    result["template_sha256"] = digest((target / "rules.json").read_bytes())
    dump(output / "plan.json", result)
    dump(output / "changes.json", report)
    return report
