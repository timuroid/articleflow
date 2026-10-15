"""Explicit style catalogues and a fresh-body renderer for oracle experiments.

The template contains property alternatives, never specimen block assignments.
The private oracle selects those alternatives. It is not an LLM prediction.
Formula XML is opaque payload, so this is not a strict plain-text I1 protocol.
"""
from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from lxml import etree as ET

from .docx_engine import (
    NS, W, DocumentError, digest, dump, load_package, paragraph_text,
    parse_xml, write_package, xml_bytes,
)

VERSION = "catalogue-0.4"
GROUPS = {
    "paragraph": ["pPr"], "character": ["rPr"],
    "table": ["tblPr", "tblGrid"], "row": ["trPr"],
    "cell": ["tcPr"], "section": ["sectPr"], "drawing": ["drawing"],
}
RESOURCE_NAMES = {
    "word/styles.xml", "word/settings.xml", "word/webSettings.xml",
    "word/numbering.xml", "word/fontTable.xml", "word/_rels/fontTable.xml.rels",
}


def _json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _property_xml(node) -> str:
    node = copy.deepcopy(node)
    for e in node.iter():
        for k in list(e.attrib):
            if ET.QName(k).localname.startswith("rsid"):
                del e.attrib[k]
    ET.cleanup_namespaces(node)
    return ET.tostring(node, encoding="unicode", with_tail=False)


def _is_resource(name: str) -> bool:
    return name in RESOURCE_NAMES or name.startswith(("word/theme/", "word/fonts/"))


def _write_bundle(path: Path, parts: dict) -> None:
    """Resource hashes must not depend on the clock at extraction time."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", ZIP_DEFLATED) as z:
        for name, raw in sorted(parts.items()):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, raw)


class Catalogue:
    def __init__(self):
        self.styles = {group: {} for group in GROUPS}

    def add(self, group: str, nodes: list) -> str:
        values = [_property_xml(n) for n in nodes]
        key = group + "-" + digest(_json_bytes(values))[:16]
        previous = self.styles[group].get(key)
        if previous is not None and previous != values:
            raise DocumentError("CATALOGUE_HASH_COLLISION")
        self.styles[group][key] = values
        return key

    def properties(self, group: str, parent) -> str:
        return self.add(group, [child for child in parent if child.tag in {f"{{{W}}}{t}" for t in GROUPS[group]}])


def _drawing_rule(drawing):
    """Move relationship IDs and descriptive metadata out of the layout rule."""
    node = copy.deepcopy(drawing)
    bindings = []
    for index, e in enumerate(node.iter()):
        for key, value in list(e.attrib.items()):
            q = ET.QName(key)
            identity = ET.QName(e).localname in {"docPr", "cNvPr"} and q.localname in {"id", "name", "descr", "title"}
            if q.namespace == NS["r"] or identity:
                bindings.append({"node": index, "attribute": key, "value": value})
                e.set(key, "__ARTICLEFLOW_BINDING__")
    return node, bindings


def extract_catalogue(source: Path, annotations: dict, definitions: dict, output: Path,
                      source_observation: bool = False) -> dict:
    if output.exists() and any(output.iterdir()):
        raise DocumentError("OUTPUT_NOT_EMPTY")
    parts = load_package(source)
    if any(name.startswith(("word/header", "word/footer")) for name in parts):
        raise DocumentError("CATALOGUE_STORY_UNSUPPORTED")
    for name in ["word/footnotes.xml", "word/endnotes.xml", "word/comments.xml"]:
        if name in parts and parse_xml(parts[name]).find(".//w:t", NS) is not None:
            raise DocumentError("CATALOGUE_STORY_UNSUPPORTED")
    root = parse_xml(parts["word/document.xml"])
    body = root.find("w:body", NS)
    paragraphs = body.findall(".//w:p", NS)
    by_node = {p: f"b-{i + 1:06d}" for i, p in enumerate(paragraphs)}
    if set(annotations) != set(by_node.values()):
        raise DocumentError("ANNOTATION_COVERAGE")
    if not set(annotations.values()) <= set(definitions["roles"]):
        raise DocumentError("ANNOTATION_UNKNOWN_ROLE")
    if len(root.findall(".//w:sectPr", NS)) != 1 or body.find("w:sectPr", NS) is None:
        raise DocumentError("CATALOGUE_SECTION_PROFILE_UNSUPPORTED")
    catalogue = Catalogue()
    roles = {name: {"description": definitions["roles"][name], "paragraph_styles": set(), "character_styles": set()} for name in sorted(set(annotations.values()))}
    blocks, block_plan, objects, object_plan, layout_plan = [], [], [], [], []
    object_files = {}
    discarded = Counter()

    for p in paragraphs:
        bid = by_node[p]
        role = annotations[bid]
        pstyle = catalogue.properties("paragraph", p)
        roles[role]["paragraph_styles"].add(pstyle)
        atoms, spans = [], []
        offset = 0

        def add_text(sequence, text, style):
            nonlocal offset
            if not text:
                return
            if sequence and sequence[-1]["kind"] == "text":
                sequence[-1]["text"] += text
            else:
                sequence.append({"kind": "text", "text": text})
            if spans and spans[-1]["end"] == offset and spans[-1]["style"] == style:
                spans[-1]["end"] += len(text)
            else:
                spans.append({"start": offset, "end": offset + len(text), "style": style})
            offset += len(text)

        def visit(node, sequence, run_style=None):
            tag = ET.QName(node).localname
            if node.tag in {f"{{{W}}}pPr", f"{{{W}}}rPr"}:
                return
            if node.tag == f"{{{W}}}r":
                style = catalogue.properties("character", node)
                roles[role]["character_styles"].add(style)
                if not len(node) or all(c.tag == f"{{{W}}}rPr" for c in node):
                    raise DocumentError("EMPTY_RUN_UNSUPPORTED")
                for child in node:
                    visit(child, sequence, style)
            elif node.tag == f"{{{W}}}t":
                add_text(sequence, node.text or "", run_style)
            elif node.tag in {f"{{{W}}}tab", f"{{{W}}}br", f"{{{W}}}cr", f"{{{W}}}noBreakHyphen"}:
                if node.tag == f"{{{W}}}br" and node.get(f"{{{W}}}type") not in {None, "textWrapping"}:
                    raise DocumentError("MANUAL_BREAK_UNSUPPORTED")
                add_text(sequence, "\t" if tag == "tab" else "\u2011" if tag == "noBreakHyphen" else "\n", run_style)
            elif node.tag == f"{{{W}}}lastRenderedPageBreak":
                discarded[tag] += 1
            elif node.tag == f"{{{W}}}hyperlink":
                item = {"kind": "hyperlink", "attributes": dict(node.attrib), "children": []}
                sequence.append(item)
                for child in node:
                    visit(child, item["children"])
            elif node.tag in {f"{{{W}}}bookmarkStart", f"{{{W}}}bookmarkEnd"}:
                sequence.append({"kind": "marker", "xml": _property_xml(node)})
            elif node.tag == f"{{{W}}}drawing":
                oid = f"obj-{len(objects) + 1:06d}"
                rule, bindings = _drawing_rule(node)
                style = catalogue.add("drawing", [rule])
                objects.append({"id": oid, "kind": "drawing", "bindings": bindings})
                object_plan.append({"id": oid, "drawing_style": style, "run_style": run_style})
                sequence.append({"kind": "drawing", "object_id": oid})
            elif node.tag in {f"{{{NS['m']}}}oMath", f"{{{NS['m']}}}oMathPara"}:
                oid = f"obj-{len(objects) + 1:06d}"
                raw = ET.tostring(node, encoding="utf-8", with_tail=False)
                object_files[f"objects/{oid}.xml"] = raw
                objects.append({"id": oid, "kind": "math", "sha256": digest(raw)})
                sequence.append({"kind": "math", "object_id": oid})
            else:
                raise DocumentError("CATALOGUE_INLINE_UNSUPPORTED")

        for child in p:
            visit(child, atoms)
        if offset != len(paragraph_text(p)):
            raise DocumentError("CATALOGUE_TEXT_COVERAGE")
        blocks.append({"id": bid, "text": paragraph_text(p), "atoms": atoms})
        block_plan.append({"id": bid, "role": role, "paragraph_style": pstyle, "spans": spans})

    def structure(node):
        if node.tag == f"{{{W}}}p":
            return {"kind": "paragraph", "id": by_node[node]}
        if node.tag == f"{{{W}}}sectPr":
            return None
        if node.tag in {f"{{{W}}}bookmarkStart", f"{{{W}}}bookmarkEnd"}:
            return {"kind": "marker", "xml": _property_xml(node)}
        group = {f"{{{W}}}tbl": "table", f"{{{W}}}tr": "row", f"{{{W}}}tc": "cell"}.get(node.tag)
        if group is None:
            raise DocumentError("CATALOGUE_STRUCTURE_UNSUPPORTED")
        lid = f"layout-{len(layout_plan) + 1:06d}"
        style = catalogue.properties(group, node)
        layout_plan.append({"id": lid, "kind": group, "style": style})
        excluded = {f"{{{W}}}{tag}" for tag in GROUPS[group]}
        children = [structure(c) for c in node if c.tag not in excluded]
        return {"kind": group, "id": lid, "children": [c for c in children if c is not None]}

    tree = [value for child in body if (value := structure(child)) is not None]
    section = catalogue.add("section", [body.find("w:sectPr", NS)])
    resources = {name: data for name, data in parts.items() if _is_resource(name)}
    payload = {name: data for name, data in parts.items() if name != "word/document.xml" and not _is_resource(name)}
    template_dir, content_dir = output / "template", output / "content"
    template_dir.mkdir(parents=True, exist_ok=True)
    content_dir.mkdir(parents=True, exist_ok=True)
    _write_bundle(template_dir / "resources.zip", resources)
    _write_bundle(content_dir / "payload.zip", payload)
    for name, data in object_files.items():
        target = content_dir / name
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(data)
    template = {
        "schema_version": VERSION, "status": "observed_catalogue_not_approved",
        "roles": {name: {**r, "paragraph_styles": sorted(r["paragraph_styles"]), "character_styles": sorted(r["character_styles"])} for name, r in roles.items()},
        "styles": catalogue.styles, "inline_rules": definitions.get("inline_rules", []),
        "resource_sha256": digest((template_dir / "resources.zip").read_bytes()),
        "limitations": ["Alternative selection rules require confirmation", "No new LLM evaluation", "Opaque mathematical payload retains its internal appearance", "No unseen transfer validation"],
    }
    content = {
        "schema_version": VERSION, "protocol": "source_docx_I3" if source_observation else "explicit-catalogue-oracle-structured-payload",
        "root_namespaces": root.nsmap, "root_attributes": dict(root.attrib),
        "structure": tree, "blocks": blocks, "objects": objects,
        "payload_sha256": digest((content_dir / "payload.zip").read_bytes()),
    }
    dump(template_dir / "rules.json", template)
    dump(content_dir / "content.json", content)
    plan = {
        "schema_version": VERSION, "provenance": "source_observations_I3" if source_observation else "source_oracle",
        "template_sha256": digest((template_dir / "rules.json").read_bytes()),
        "input_sha256": digest((content_dir / "content.json").read_bytes()),
        "blocks": block_plan, "layout": layout_plan, "objects": object_plan,
        "section_style": section,
    }
    dump(output / ("source-observations.json" if source_observation else "oracle-plan.json"), plan)
    manifest = {
        "schema_version": VERSION, "mode": "source_observations_I3" if source_observation else "oracle_renderer_control", "model_calls": 0,
        "eligible_for_model_benchmark": False, "strict_I1_eligible": False,
        "blocks": len(blocks), "roles": len(roles), "catalogue_counts": {k: len(v) for k, v in catalogue.styles.items()},
        "source_text_runs": len(root.xpath(".//w:body//w:r[not(ancestor::m:oMath)]", namespaces=NS)),
        "compiled_text_spans": sum(len(b["spans"]) for b in block_plan),
        "discarded_cached_markers": dict(discarded),
        "template_sha256": plan["template_sha256"], "input_sha256": plan["input_sha256"],
    }
    dump(output / "manifest.json", manifest)
    return manifest


def _walk_structure(nodes):
    for node in nodes:
        yield node
        yield from _walk_structure(node.get("children", []))


def _unique(items, key="id"):
    result = {}
    for item in items:
        if item[key] in result:
            raise DocumentError("PLAN_DUPLICATE_ID")
        result[item[key]] = item
    return result


def validate_catalogue_plan(content: dict, template: dict, plan: dict) -> None:
    if any(x.get("schema_version") != VERSION for x in [content, template, plan]):
        raise DocumentError("CATALOGUE_VERSION")
    by_id = _unique(content["blocks"])
    object_ids = _unique(content["objects"])
    occurrences = []
    def inspect_atoms(atoms):
        text = []
        for atom in atoms:
            if atom["kind"] == "text":
                text.append(atom["text"])
            elif atom["kind"] == "hyperlink":
                text.append(inspect_atoms(atom["children"]))
            elif atom["kind"] in {"drawing", "math"}:
                oid = atom["object_id"]
                if oid not in object_ids or object_ids[oid]["kind"] != atom["kind"]:
                    raise DocumentError("CONTENT_OBJECT_ID")
                occurrences.append(oid)
            elif atom["kind"] == "marker":
                if parse_xml(atom["xml"].encode()).tag not in {f"{{{W}}}bookmarkStart", f"{{{W}}}bookmarkEnd"}:
                    raise DocumentError("CONTENT_MARKER_TYPE")
            else:
                raise DocumentError("CONTENT_ATOM_UNSUPPORTED")
        return "".join(text)
    for block in by_id.values():
        if inspect_atoms(block["atoms"]) != block["text"]:
            raise DocumentError("CONTENT_TEXT_MISMATCH")
    if len(occurrences) != len(set(occurrences)) or set(occurrences) != set(object_ids):
        raise DocumentError("CONTENT_OBJECT_COVERAGE")
    assignments = _unique(plan["blocks"])
    if set(assignments) != set(by_id):
        raise DocumentError("PLAN_COVERAGE")
    for bid, block in assignments.items():
        role = template["roles"].get(block["role"])
        if role is None or block["paragraph_style"] not in role["paragraph_styles"] or block["paragraph_style"] not in template["styles"]["paragraph"]:
            raise DocumentError("PLAN_STYLE_ROLE")
        cursor = 0
        for span in block["spans"]:
            if set(span) != {"start", "end", "style"}:
                raise DocumentError("PLAN_SPAN_SCHEMA")
            a, b = span["start"], span["end"]
            if type(a) is not int or type(b) is not int or a != cursor or not a < b <= len(by_id[bid]["text"]):
                raise DocumentError("PLAN_SPAN_COVERAGE")
            if span["style"] not in role["character_styles"] or span["style"] not in template["styles"]["character"]:
                raise DocumentError("PLAN_CHARACTER_STYLE")
            cursor = b
        if cursor != len(by_id[bid]["text"]):
            raise DocumentError("PLAN_SPAN_COVERAGE")
    structure = list(_walk_structure(content["structure"]))
    paragraph_ids = [n["id"] for n in structure if n["kind"] == "paragraph"]
    if len(paragraph_ids) != len(set(paragraph_ids)) or set(paragraph_ids) != set(by_id):
        raise DocumentError("CONTENT_STRUCTURE_COVERAGE")
    expected_layout = {n["id"]: n["kind"] for n in structure if n["kind"] in {"table", "row", "cell"}}
    layout = _unique(plan["layout"])
    if set(layout) != set(expected_layout):
        raise DocumentError("PLAN_LAYOUT_COVERAGE")
    for lid, item in layout.items():
        if item["kind"] != expected_layout[lid] or item["style"] not in template["styles"][item["kind"]]:
            raise DocumentError("PLAN_LAYOUT_STYLE")
    drawings = {o["id"] for o in content["objects"] if o["kind"] == "drawing"}
    object_plan = _unique(plan["objects"])
    if set(object_plan) != drawings:
        raise DocumentError("PLAN_OBJECT_COVERAGE")
    for item in object_plan.values():
        if item["drawing_style"] not in template["styles"]["drawing"] or item["run_style"] not in template["styles"]["character"]:
            raise DocumentError("PLAN_OBJECT_STYLE")
    if plan["section_style"] not in template["styles"]["section"]:
        raise DocumentError("PLAN_SECTION_STYLE")


def placement_fingerprint(path: Path) -> list:
    """Scientific links/objects/bookmarks by text position, independent of runs."""
    root = parse_xml(load_package(path)["word/document.xml"])
    events = []
    paragraph, offset = -1, 0
    def visit(node):
        nonlocal paragraph, offset
        tag = node.tag
        if tag == f"{{{W}}}p":
            paragraph += 1
            offset = 0
        if tag in {f"{{{W}}}pPr", f"{{{W}}}rPr"}:
            return
        if tag == f"{{{W}}}t":
            offset += len(node.text or "")
            return
        if tag in {f"{{{W}}}tab", f"{{{W}}}br", f"{{{W}}}cr", f"{{{W}}}noBreakHyphen"}:
            offset += 1
            return
        if tag == f"{{{W}}}drawing":
            links = [dict(n.attrib) for n in node.findall(".//a:blip", NS)]
            events.append([paragraph, offset, "drawing", links])
            return
        if tag in {f"{{{NS['m']}}}oMath", f"{{{NS['m']}}}oMathPara"}:
            # Whole formula equality is checked independently by compare_content.
            events.append([paragraph, offset, "math"])
            return
        if tag in {f"{{{W}}}bookmarkStart", f"{{{W}}}bookmarkEnd"}:
            events.append([paragraph, offset, ET.QName(tag).localname, dict(node.attrib)])
            return
        if tag == f"{{{W}}}hyperlink":
            events.append([paragraph, offset, "hyperlink_start", dict(node.attrib)])
        for child in node:
            visit(child)
        if tag == f"{{{W}}}hyperlink":
            events.append([paragraph, offset, "hyperlink_end"])
    visit(root.find("w:body", NS))
    return events


def _read_bundle(path: Path) -> dict:
    with ZipFile(path) as z:
        names = z.namelist()
        if len(names) != len(set(names)):
            raise DocumentError("BUNDLE_DUPLICATE")
        return {name: z.read(name) for name in names}


def render_catalogue(template_dir: Path, content_dir: Path, plan: dict, target: Path) -> dict:
    raw_template = (template_dir / "rules.json").read_bytes()
    raw_content = (content_dir / "content.json").read_bytes()
    if digest(raw_template) != plan["template_sha256"] or digest(raw_content) != plan["input_sha256"]:
        raise DocumentError("PLAN_INPUT_HASH")
    template, content = json.loads(raw_template), json.loads(raw_content)
    if digest((template_dir / "resources.zip").read_bytes()) != template["resource_sha256"] or digest((content_dir / "payload.zip").read_bytes()) != content["payload_sha256"]:
        raise DocumentError("RESOURCE_HASH")
    validate_catalogue_plan(content, template, plan)
    blocks, assignments = _unique(content["blocks"]), _unique(plan["blocks"])
    objects, obj_plan, layout = _unique(content["objects"]), _unique(plan["objects"]), _unique(plan["layout"])
    root = ET.Element(f"{{{W}}}document", nsmap={None if k == "null" else k: v for k, v in content["root_namespaces"].items()})
    root.attrib.update(content["root_attributes"])
    body = ET.SubElement(root, f"{{{W}}}body")

    def properties(parent, group, key):
        for raw in template["styles"][group][key]:
            node = parse_xml(raw.encode())
            if node.tag not in {f"{{{W}}}{tag}" for tag in GROUPS[group]}:
                raise DocumentError("CATALOGUE_PROPERTY_TYPE")
            if node.xpath(".//w:t | .//m:t", namespaces=NS):
                raise DocumentError("TEMPLATE_CONTAINS_TEXT")
            parent.append(node)

    def text_run(parent, text, style):
        r = ET.SubElement(parent, f"{{{W}}}r")
        properties(r, "character", style)
        buffer = []
        def flush():
            if buffer:
                n = ET.SubElement(r, f"{{{W}}}t")
                n.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                n.text = "".join(buffer)
                buffer.clear()
        for char in text:
            if char in "\n\t":
                flush()
                ET.SubElement(r, f"{{{W}}}{'tab' if char == chr(9) else 'br'}")
            else:
                buffer.append(char)
        flush()

    def paragraph(parent, bid):
        p = ET.SubElement(parent, f"{{{W}}}p")
        assignment = assignments[bid]
        properties(p, "paragraph", assignment["paragraph_style"])
        offset = 0
        def atoms(parent, sequence):
            nonlocal offset
            for atom in sequence:
                if atom["kind"] == "text":
                    text = atom["text"]
                    end = offset + len(text)
                    for span in assignment["spans"]:
                        a, b = max(offset, span["start"]), min(end, span["end"])
                        if a < b:
                            text_run(parent, text[a - offset:b - offset], span["style"])
                    offset = end
                elif atom["kind"] == "hyperlink":
                    link = ET.SubElement(parent, f"{{{W}}}hyperlink", atom["attributes"])
                    atoms(link, atom["children"])
                elif atom["kind"] == "marker":
                    parent.append(parse_xml(atom["xml"].encode()))
                elif atom["kind"] == "math":
                    obj = objects[atom["object_id"]]
                    raw = (content_dir / "objects" / (obj["id"] + ".xml")).read_bytes()
                    if digest(raw) != obj["sha256"]:
                        raise DocumentError("OBJECT_HASH")
                    parent.append(parse_xml(raw))
                elif atom["kind"] == "drawing":
                    oid = atom["object_id"]
                    rule = obj_plan[oid]
                    run = ET.SubElement(parent, f"{{{W}}}r")
                    properties(run, "character", rule["run_style"])
                    properties(run, "drawing", rule["drawing_style"])
                    drawing = run.find("w:drawing", NS)
                    nodes = list(drawing.iter())
                    for binding in objects[oid]["bindings"]:
                        node = nodes[binding["node"]]
                        if node.get(binding["attribute"]) != "__ARTICLEFLOW_BINDING__":
                            raise DocumentError("DRAWING_BINDING_MISMATCH")
                        node.set(binding["attribute"], binding["value"])
                else:
                    raise DocumentError("CONTENT_ATOM_UNSUPPORTED")
        atoms(p, blocks[bid]["atoms"])

    def build(parent, nodes):
        for node in nodes:
            kind = node["kind"]
            if kind == "paragraph":
                paragraph(parent, node["id"])
            elif kind == "marker":
                parent.append(parse_xml(node["xml"].encode()))
            elif kind in {"table", "row", "cell"}:
                tag = {"table": "tbl", "row": "tr", "cell": "tc"}[kind]
                child = ET.SubElement(parent, f"{{{W}}}{tag}")
                properties(child, kind, layout[node["id"]]["style"])
                build(child, node["children"])
            else:
                raise DocumentError("CONTENT_STRUCTURE_UNSUPPORTED")
    build(body, content["structure"])
    properties(body, "section", plan["section_style"])
    payload = _read_bundle(content_dir / "payload.zip")
    resources = _read_bundle(template_dir / "resources.zip")
    if "word/document.xml" in payload or "word/document.xml" in resources or set(payload) & set(resources):
        raise DocumentError("BUNDLE_PART_COLLISION")
    write_package(target, {**payload, **resources, "word/document.xml": xml_bytes(root)})
    return {"renderer": VERSION, "body_rebuilt": True, "source_docx_read": False, "model_calls": 0, "plan_provenance": plan.get("provenance"), "strict_I1_pass": False}
