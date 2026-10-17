"""Bounded DOCX inspection, private evidence and explicit reconstruction modes.

Never execute document instructions. A lossless instance replay is a diagnostic,
not a reusable template or a model benchmark. The role renderer reconstructs a
new document body from content atoms and a shared role catalogue.
"""
from __future__ import annotations

import copy
import hashlib
import json
import unicodedata
import zlib
from collections import Counter
from pathlib import Path, PurePosixPath
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED

from lxml import etree as ET

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
}
W = NS["w"]
FORMAT_TAGS = {f"{{{W}}}{x}" for x in ["pPr", "rPr", "tblPr", "tblGrid", "trPr", "tcPr", "sectPr"]}
SAFE_PARTS = {
    "[Content_Types].xml", "_rels/.rels", "word/document.xml",
    "word/_rels/document.xml.rels", "word/styles.xml", "word/settings.xml",
    "word/numbering.xml", "word/theme/theme1.xml", "word/fontTable.xml",
    "word/_rels/fontTable.xml.rels", "word/footnotes.xml", "word/endnotes.xml",
    "word/webSettings.xml", "docProps/core.xml", "docProps/app.xml",
}


class DocumentError(ValueError):
    """Safe error codes: callers must not log manuscript contents."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def parse_xml(data: bytes):
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise DocumentError("XML_DTD_FORBIDDEN")
    parser = ET.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)
    try:
        return ET.fromstring(data, parser)
    except ET.XMLSyntaxError as exc:
        raise DocumentError("XML_INVALID") from exc


def xml_bytes(element) -> bytes:
    return ET.tostring(element, encoding="UTF-8", xml_declaration=True, standalone=True)


def load_package(path: Path) -> dict[str, bytes]:
    if path.stat().st_size > 25 * 1024**2:
        raise DocumentError("UPLOAD_TOO_LARGE")
    try:
        with ZipFile(path) as z:
            info = z.infolist()
            if len(info) > 10000 or sum(i.file_size for i in info) > 250 * 1024**2:
                raise DocumentError("ZIP_LIMIT")
            names = [i.filename for i in info]
            if len(names) != len(set(names)):
                raise DocumentError("ZIP_DUPLICATE")
            for i in info:
                name = i.filename
                if name.startswith("/") or "\\" in name or ".." in PurePosixPath(name).parts:
                    raise DocumentError("ZIP_PATH")
                if i.flag_bits & 1 or i.file_size > max(1, i.compress_size) * 100:
                    raise DocumentError("ZIP_RATIO_OR_ENCRYPTION")
            parts = {i.filename: z.read(i) for i in info}
    except DocumentError:
        raise
    except Exception as exc:
        raise DocumentError("INVALID_DOCX_ZIP") from exc
    if not {"word/document.xml", "[Content_Types].xml", "_rels/.rels"} <= parts.keys():
        raise DocumentError("INVALID_DOCX_PACKAGE")
    for name, data in parts.items():
        if name.endswith((".xml", ".rels")):
            parse_xml(data)
        if any(token in name.lower() for token in ["vbaproject", "activex", "embeddings/"]):
            raise DocumentError("ACTIVE_CONTENT_UNSUPPORTED")
    root = parse_xml(parts["word/document.xml"])
    if root.tag != f"{{{W}}}document":
        raise DocumentError("OOXML_PROFILE_UNSUPPORTED")
    if root.xpath(".//w:ins | .//w:del | .//w:txbxContent | .//w:altChunk | .//wp:anchor", namespaces=NS):
        raise DocumentError("UNSUPPORTED_CONSTRUCT")
    return parts


def write_package(path: Path, parts: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    with ZipFile(temp, "w", ZIP_DEFLATED) as z:
        for name, data in sorted(parts.items()):
            # Highly compressible legitimate parts (e.g. flat images) must not
            # make our own output fail the unchanged defensive import limit.
            compressor = zlib.compressobj(wbits=-15)
            compressed_size = len(compressor.compress(data) + compressor.flush())
            method = ZIP_STORED if len(data) > max(1, compressed_size) * 100 else ZIP_DEFLATED
            z.writestr(name, data, compress_type=method)
    temp.replace(path)


def paragraph_text(p) -> str:
    pieces = []
    for node in p.iter():
        if node.tag == f"{{{W}}}t":
            pieces.append(node.text or "")
        elif node.tag == f"{{{W}}}tab" and node.getparent() is not None and node.getparent().tag == f"{{{W}}}r":
            pieces.append("\t")
        elif node.tag in {f"{{{W}}}br", f"{{{W}}}cr"}:
            pieces.append("\n")
        elif node.tag == f"{{{W}}}noBreakHyphen":
            pieces.append("\u2011")
    return "".join(pieces)


def flag(rpr, name):
    if rpr is None:
        return None
    element = rpr.find(f"w:{name}", NS)
    if element is None:
        return None
    return element.get(f"{{{W}}}val", "true") not in {"0", "false", "off"}


def stripped_xml(element):
    """Stable evidence representation, excluding author/revision identifiers."""
    if element is None:
        return None
    e = copy.deepcopy(element)
    for node in e.iter():
        for key in list(node.attrib):
            if ET.QName(key).localname.startswith("rsid"):
                del node.attrib[key]
    return ET.tostring(e, encoding="unicode", with_tail=False)


def source_spans(p) -> list[dict]:
    spans = []
    offset = 0
    for run in p.xpath(".//w:r[not(ancestor::m:oMath)]", namespaces=NS):
        text = paragraph_text(run)
        rpr = run.find("w:rPr", NS)
        props = {k: flag(rpr, k) for k in ["b", "i"] if flag(rpr, k) is not None}
        if rpr is not None:
            vertical = rpr.find("w:vertAlign", NS)
            if vertical is not None:
                props["vertAlign"] = vertical.get(f"{{{W}}}val")
        if text and props:
            span = {"start": offset, "end": offset + len(text), **props}
            if spans and spans[-1]["end"] == offset and {k: v for k, v in spans[-1].items() if k not in {"start", "end"}} == props:
                spans[-1]["end"] = span["end"]
            else:
                spans.append(span)
        offset += len(text)
    return spans


def _atomize(p, object_dir: Path, index: list, source_parts: dict) -> list[dict]:
    """Collapse text runs; retain opaque math/drawing payloads as named atoms.

    Drawing geometry is retained in the diagnostic hybrid protocol ONLY. The
    manifest explicitly excludes this renderer from strict I1 reconstruction.
    """
    atoms = []

    def add_text(value):
        if atoms and atoms[-1]["kind"] == "text":
            atoms[-1]["text"] += value
        else:
            atoms.append({"kind": "text", "text": value})

    def visit(node):
        if node.tag in FORMAT_TAGS:
            return
        if node.tag in {f"{{{NS['m']}}}oMathPara", f"{{{NS['m']}}}oMath", f"{{{W}}}drawing"}:
            kind = "drawing" if node.tag == f"{{{W}}}drawing" else "math"
            oid = f"{kind}-{len(index)+1:04d}"
            raw = ET.tostring(node, encoding="utf-8", with_tail=False)
            object_dir.mkdir(parents=True, exist_ok=True)
            (object_dir / f"{oid}.xml").write_bytes(raw)
            index.append({"id": oid, "kind": kind, "sha256": digest(raw)})
            atoms.append({"kind": kind, "object_id": oid})
            return
        if node.tag == f"{{{W}}}hyperlink":
            # Preserve link identity, not direct formatting of its child runs.
            atoms.append({"kind": "hyperlink", "text": paragraph_text(node), "attributes": dict(node.attrib)})
            return
        if node.tag == f"{{{W}}}t":
            add_text(node.text or "")
        elif node.tag == f"{{{W}}}tab" and node.getparent() is not None and node.getparent().tag == f"{{{W}}}r":
            add_text("\t")
        elif node.tag in {f"{{{W}}}br", f"{{{W}}}cr"}:
            if node.get(f"{{{W}}}type") not in {None, "textWrapping"}:
                raise DocumentError("MANUAL_BREAK_UNSUPPORTED")
            add_text("\n")
        elif node.tag == f"{{{W}}}noBreakHyphen":
            add_text("\u2011")
        elif node.tag in {f"{{{W}}}sym", f"{{{W}}}instrText", f"{{{W}}}fldChar", f"{{{W}}}footnoteReference", f"{{{W}}}endnoteReference"}:
            raise DocumentError("INLINE_CONSTRUCT_UNSUPPORTED")
        else:
            for child in node:
                visit(child)

    visit(p)
    return atoms


def inspect_document(source: Path, output: Path) -> dict:
    parts = load_package(source)
    root = parse_xml(parts["word/document.xml"])
    body = root.find("w:body", NS)
    paragraphs = body.findall(".//w:p", NS)
    output.mkdir(parents=True, exist_ok=True)
    objects = []
    records = []
    pid_by_node = {p: f"b-{i+1:06d}" for i, p in enumerate(paragraphs)}
    top_index = {p: i for i, p in enumerate(body.findall("w:p", NS))}
    for p in paragraphs:
        raw_runs = []
        for run in p.xpath(".//w:r[not(ancestor::m:oMath)]", namespaces=NS):
            text = paragraph_text(run)
            raw_runs.append({"length": len(text), "rpr": stripped_xml(run.find("w:rPr", NS))})
        records.append({
            "id": pid_by_node[p], "text": paragraph_text(p),
            "top_index": top_index.get(p), "in_table": p not in top_index,
            "atoms": _atomize(p, output / "objects", objects, parts),
            "ppr": stripped_xml(p.find("w:pPr", NS)),
            "runs": raw_runs, "source_spans": source_spans(p),
        })
    skeleton = copy.deepcopy(root)
    # Preserve table geometry only for explicitly labelled hybrid pilot.
    for original, p in zip(paragraphs, skeleton.find("w:body", NS).findall(".//w:p", NS)):
        p.clear()
        p.set("data-af-id", pid_by_node[original])
    section = skeleton.find(".//w:body/w:sectPr", NS)
    section_xml = stripped_xml(section)
    if section is not None:
        section.getparent().remove(section)
    (output / "skeleton.xml").write_bytes(xml_bytes(skeleton))
    write_package(output / "support.docx", {k: v for k, v in parts.items() if k != "word/document.xml"})
    content = {"schema_version": "pilot-0.3", "protocol": "I1-text-to-model/I3-object-layout-to-renderer", "blocks": [{k: r[k] for k in ["id", "text", "in_table", "atoms"]} for r in records], "objects": objects}
    dump(output / "content.json", content)
    dump(output / "evidence.json", {"blocks": records, "section_xml": section_xml})
    inventory = {
        "source_sha256": digest(source.read_bytes()), "paragraphs": len(paragraphs),
        "top_level_paragraphs": len(top_index), "tables": len(body.findall("w:tbl", NS)),
        "math_objects": len(root.findall(".//m:oMath", NS)), "inline_images": len(root.findall(".//wp:inline", NS)),
        "media_count": len([k for k in parts if k.startswith("word/media/")]),
        "font_files": len([k for k in parts if k.startswith("word/fonts/")]),
        "sections": len(root.findall(".//w:sectPr", NS)),
        "text_characters": sum(len(r["text"]) for r in records),
        "protocol_limitations": ["table geometry and drawing XML retained by renderer", "not strict I1 or text-only", "source opaque object XML retained", "role formatting uses representative direct properties"],
    }
    dump(output / "inventory.json", inventory)
    return inventory


def lossless_split(source: Path, directory: Path) -> dict:
    """Lossless specimen encoding, explicitly NOT a transferable template."""
    parts = load_package(source)
    root = parse_xml(parts.pop("word/document.xml"))
    catalogue = {}
    assignments = {}
    count = 0
    for node in list(root.iter()):
        if node.tag in FORMAT_TAGS and node.getparent() is not None:
            if any(a.tag in FORMAT_TAGS for a in node.iterancestors()):
                continue
            raw = ET.tostring(node, encoding="unicode", with_tail=False)
            key = digest(raw.encode())
            catalogue[key] = raw
            token = f"format-{count:06d}"
            count += 1
            marker = ET.Element("af-format")
            marker.set("id", token)
            marker.tail = node.tail
            node.getparent().replace(node, marker)
            assignments[token] = key
    directory.mkdir(parents=True, exist_ok=True)
    write_package(directory / "support.docx", parts)
    (directory / "content.xml").write_bytes(xml_bytes(root))
    dump(directory / "format-catalogue.json", catalogue)
    dump(directory / "oracle-plan.json", assignments)
    summary = {"mode": "instance_lossless_diagnostic", "properties": count, "unique_properties": len(catalogue), "model_calls": 0, "eligible_for_model_benchmark": False}
    dump(directory / "manifest.json", summary)
    return summary


def lossless_rebuild(directory: Path, target: Path) -> None:
    with ZipFile(directory / "support.docx") as z:
        parts = {n: z.read(n) for n in z.namelist()}
    root = parse_xml((directory / "content.xml").read_bytes())
    catalogue = json.loads((directory / "format-catalogue.json").read_text())
    plan = json.loads((directory / "oracle-plan.json").read_text())
    for marker in root.findall(".//af-format"):
        node = parse_xml(catalogue[plan[marker.get("id")]].encode())
        node.tail = marker.tail
        marker.getparent().replace(marker, node)
    parts["word/document.xml"] = xml_bytes(root)
    write_package(target, parts)


def build_template(evidence_dir: Path, annotations: dict, role_definitions: dict, destination: Path, inline_rules: list[str] | None = None) -> dict:
    evidence = json.loads((evidence_dir / "evidence.json").read_text())
    by_id = {b["id"]: b for b in evidence["blocks"]}
    if set(annotations) != set(by_id):
        raise DocumentError("ANNOTATION_COVERAGE")
    if not set(annotations.values()) <= set(role_definitions):
        raise DocumentError("ANNOTATION_UNKNOWN_ROLE")
    roles = {}
    for role, description in role_definitions.items():
        members = [by_id[bid] for bid, rid in annotations.items() if rid == role]
        if not members:
            continue
        pcounts = Counter(b["ppr"] for b in members)
        ppr = pcounts.most_common(1)[0][0]
        rcounts = Counter()
        for block in members:
            for run in block["runs"]:
                if run["length"]:
                    rcounts[run["rpr"]] += run["length"]
        rpr = rcounts.most_common(1)[0][0] if rcounts else None
        roles[role] = {"description": description, "ppr_xml": ppr, "rpr_xml": rpr, "sample_count": len(members), "paragraph_variants": len(pcounts)}
    template = {"schema_version": "pilot-0.3", "status": "research_draft", "method": "E-MANUAL-plus-observed-modal-properties", "section_xml": evidence["section_xml"], "roles": roles, "inline_rules": inline_rules or [], "limitations": ["Draft inferred from one specimen", "Observed variants within semantic roles remain unresolved", "Not a promise of pixel-exact reconstruction", "Current renderer preserves source object/table geometry and uses original style resources"]}
    dump(destination, template)
    return template


def validate_plan(content: dict, template: dict, plan: dict) -> None:
    if set(plan) != {"blocks"} or not isinstance(plan["blocks"], list):
        raise DocumentError("PLAN_SCHEMA")
    blocks = {b["id"]: b for b in content["blocks"]}
    seen = set()
    for assignment in plan["blocks"]:
        if set(assignment) != {"id", "role", "spans"}:
            raise DocumentError("PLAN_SCHEMA")
        bid = assignment["id"]
        if bid not in blocks or bid in seen:
            raise DocumentError("PLAN_BLOCK_IDS")
        seen.add(bid)
        if assignment["role"] not in template["roles"]:
            raise DocumentError("PLAN_ROLE")
        if not isinstance(assignment["spans"], list):
            raise DocumentError("PLAN_SPANS")
        previous_end = 0
        for span in assignment["spans"]:
            if set(span) != {"start", "end", "bold", "italic", "vertical"}:
                raise DocumentError("PLAN_SPAN_SCHEMA")
            start, end = span["start"], span["end"]
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(blocks[bid]["text"]):
                raise DocumentError("PLAN_SPAN_BOUNDS")
            if start < previous_end:
                raise DocumentError("PLAN_SPAN_OVERLAP")
            previous_end = end
            if any(span[k] is not None and type(span[k]) is not bool for k in ["bold", "italic"]) or span["vertical"] not in [None, "baseline", "superscript", "subscript"]:
                raise DocumentError("PLAN_SPAN_VALUE")
            text = blocks[bid]["text"]
            for boundary in [start, end]:
                if boundary < len(text) and (unicodedata.combining(text[boundary]) or text[boundary] in {"\u200d", "\ufe0f"}):
                    raise DocumentError("PLAN_GRAPHEME_BOUNDARY")
                if boundary and text[boundary - 1] == "\u200d":
                    raise DocumentError("PLAN_GRAPHEME_BOUNDARY")
    if seen != set(blocks):
        raise DocumentError("PLAN_COVERAGE")


def _set_run_property(rpr, name, value):
    for old in list(rpr.findall(f"w:{name}", NS)):
        rpr.remove(old)
    el = ET.SubElement(rpr, f"{{{W}}}{name}")
    el.set(f"{{{W}}}val", ("1" if value else "0") if isinstance(value, bool) else value)


def _text_runs(parent, text: str, base: str | None, spans: list, offset: int):
    boundaries = sorted({0, len(text)} | {max(0, min(len(text), s[k] - offset)) for s in spans for k in ["start", "end"]})
    for left, right in zip(boundaries, boundaries[1:]):
        if left == right:
            continue
        run = ET.SubElement(parent, f"{{{W}}}r")
        rpr = parse_xml(base.encode()) if base else ET.Element(f"{{{W}}}rPr")
        for s in spans:
            if s["start"] <= offset + left < s["end"]:
                for key, tag in [("bold", "b"), ("italic", "i"), ("vertical", "vertAlign")]:
                    if s[key] is not None:
                        _set_run_property(rpr, tag, s[key])
                        if key in {"bold", "italic"}:
                            _set_run_property(rpr, tag + "Cs", s[key])
        if len(rpr):
            run.append(rpr)
        buffer = ""
        for char in text[left:right]:
            if char in "\t\n":
                if buffer:
                    node = ET.SubElement(run, f"{{{W}}}t")
                    node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                    node.text = buffer
                    buffer = ""
                ET.SubElement(run, f"{{{W}}}{'tab' if char == chr(9) else 'br'}")
            else:
                buffer += char
        if buffer:
            node = ET.SubElement(run, f"{{{W}}}t")
            node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            node.text = buffer


def render_roles(content_dir: Path, template: dict, plan: dict, target: Path) -> None:
    content = json.loads((content_dir / "content.json").read_text())
    validate_plan(content, template, plan)
    by_id = {b["id"]: b for b in content["blocks"]}
    assignments = {b["id"]: b for b in plan["blocks"]}
    root = parse_xml((content_dir / "skeleton.xml").read_bytes())
    for p in root.findall(".//w:body//w:p", NS):
        bid = p.attrib.pop("data-af-id")
        assignment = assignments[bid]
        style = template["roles"][assignment["role"]]
        if style["ppr_xml"]:
            p.append(parse_xml(style["ppr_xml"].encode()))
        offset = 0
        for atom in by_id[bid]["atoms"]:
            if atom["kind"] in {"text", "hyperlink"}:
                parent = p
                if atom["kind"] == "hyperlink":
                    parent = ET.SubElement(p, f"{{{W}}}hyperlink", atom["attributes"])
                _text_runs(parent, atom["text"], style["rpr_xml"], assignment["spans"], offset)
                offset += len(atom["text"])
            else:
                node = parse_xml((content_dir / "objects" / f"{atom['object_id']}.xml").read_bytes())
                if atom["kind"] == "drawing":
                    ET.SubElement(p, f"{{{W}}}r").append(node)
                else:
                    p.append(node)
    root.find("w:body", NS).append(parse_xml(template["section_xml"].encode()))
    with ZipFile(content_dir / "support.docx") as z:
        parts = {n: z.read(n) for n in z.namelist()}
    parts["word/document.xml"] = xml_bytes(root)
    write_package(target, parts)


def emphasis_masks(path: Path) -> list[list[tuple]]:
    """Evaluate b/i/vertical flags for this pilot; not a full Word style engine."""
    parts = load_package(path)
    styles = parse_xml(parts["word/styles.xml"])
    by_id = {s.get(f"{{{W}}}styleId"): s for s in styles.findall("w:style", NS)}
    default = next((key for key, s in by_id.items() if s.get(f"{{{W}}}default") == "1" and s.get(f"{{{W}}}type") == "paragraph"), None)

    def apply(state, rpr, toggle=False):
        if rpr is not None:
            for key in ["b", "i"]:
                v = flag(rpr, key)
                if v is not None:
                    if toggle:
                        if v:
                            state[key] = not state[key]
                    else:
                        state[key] = v
            vertical = rpr.find("w:vertAlign", NS)
            if vertical is not None:
                state["vertical"] = vertical.get(f"{{{W}}}val", "baseline")

    def chain(key, seen=None):
        seen = set() if seen is None else seen
        if key is None or key not in by_id:
            return []
        if key in seen:
            raise DocumentError("STYLE_CYCLE")
        seen.add(key)
        node = by_id[key]
        parent = node.find("w:basedOn", NS)
        return (chain(parent.get(f"{{{W}}}val"), seen) if parent is not None else []) + [node]

    root = parse_xml(parts["word/document.xml"])
    result = []
    from .stories026 import paragraphs
    for p in paragraphs(parts):
        base = {"b": False, "i": False, "vertical": "baseline"}
        apply(base, styles.find("w:docDefaults/w:rPrDefault/w:rPr", NS))
        sid = p.find("w:pPr/w:pStyle", NS)
        for style in chain(sid.get(f"{{{W}}}val") if sid is not None else default):
            apply(base, style.find("w:rPr", NS), toggle=True)
        values = []
        for run in p.xpath(".//w:r[not(ancestor::m:oMath)]", namespaces=NS):
            state = dict(base)
            rpr = run.find("w:rPr", NS)
            csid = run.find("w:rPr/w:rStyle", NS)
            if csid is not None:
                for style in chain(csid.get(f"{{{W}}}val")):
                    apply(state, style.find("w:rPr", NS), toggle=True)
            apply(state, rpr)
            values.extend([(state["b"], state["i"], state["vertical"])] * len(paragraph_text(run)))
        result.append(values)
    return result


def compare_emphasis(source: Path, target: Path) -> dict:
    a, b = emphasis_masks(source), emphasis_masks(target)
    structure_equal = len(a) == len(b) and all(len(x) == len(y) for x, y in zip(a, b))
    if not structure_equal:
        return {"inline_exact": False, "inline_character_accuracy": None, "protected_vertical_exact": False}
    total = sum(map(len, a))
    correct = sum(x == y for aa, bb in zip(a, b) for x, y in zip(aa, bb))
    vertical = all(x[2] == y[2] for aa, bb in zip(a, b) for x, y in zip(aa, bb))
    return {"inline_exact": a == b, "inline_character_accuracy": correct / total if total else 1.0, "protected_vertical_exact": vertical}


def content_fingerprint(path: Path) -> dict:
    parts = load_package(path)
    root = parse_xml(parts["word/document.xml"])
    def shape(node):
        return [ET.QName(node).localname, sorted((ET.QName(k).localname, v) for k, v in node.attrib.items()), node.text or "", [shape(c) for c in node]]
    body = root.find("w:body", NS)
    paragraphs = [paragraph_text(p) for p in body.findall(".//w:p", NS)]
    math = [shape(x) for x in root.findall(".//m:oMath", NS)]
    tables = []
    for t in body.findall("w:tbl", NS):
        tables.append([[{"text": [paragraph_text(p) for p in c.findall("w:p", NS)], "merge": [shape(x) for x in c.xpath("./w:tcPr/w:gridSpan | ./w:tcPr/w:vMerge", namespaces=NS)]} for c in row.findall("w:tc", NS)] for row in t.findall("w:tr", NS)])
    notes = {name: digest(data) for name, data in parts.items() if name in {"word/footnotes.xml", "word/endnotes.xml"}}
    from .stories026 import roots
    stories={name:{"paragraphs":[paragraph_text(p) for p in story.findall('.//w:p',NS)],
                   "math":[shape(x) for x in story.findall('.//m:oMath',NS)],
                   "fields":[dict(h.attrib) for h in story.findall('.//w:fldSimple',NS)],
                   "links":[dict(h.attrib) for h in story.findall('.//w:hyperlink',NS)]}
             for name,story in roots(parts)[1:]}
    story_relationships={n:digest(v) for n,v in parts.items() if n.startswith(('word/_rels/header','word/_rels/footer'))}
    return {"fields":[dict(h.attrib) for h in root.findall('.//w:fldSimple',NS)],"stories":stories,"story_relationships":story_relationships,"paragraphs": paragraphs, "math": math, "tables": tables, "media": {n: digest(v) for n, v in parts.items() if n.startswith("word/media/")}, "links": [dict(h.attrib) for h in root.findall(".//w:hyperlink", NS)], "relationships": digest(parts.get("word/_rels/document.xml.rels", b"")), "notes": notes}


def compare_content(source: Path, target: Path) -> dict:
    a, b = content_fingerprint(source), content_fingerprint(target)
    checks = {key: a[key] == b[key] for key in a}
    emphasis = compare_emphasis(source, target)
    checks["protected_vertical"] = emphasis["protected_vertical_exact"]
    return {"content_exact": all(checks.values()), "checks": checks, **emphasis, "scope": "text including tabs/breaks, table cell content/merges, OMML, media bytes, hyperlink attrs, relationship part, note parts and vertical semantics; ordinary emphasis separately"}
