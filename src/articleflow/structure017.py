"""Conservative Web 017 DOCX structure pass.

Only whole top-level OOXML nodes are moved. Ambiguous content stays in the
source and produces a review question; the engine never invents article text.
"""
from __future__ import annotations

import copy
import json
import re
from collections import Counter
from pathlib import Path

from lxml import etree as ET

from .docx_engine import NS, W, DocumentError, digest, load_package, paragraph_text, parse_xml, write_package, xml_bytes
from . import typography019 as typo
from . import fragments019, bookmarks020

SLOTS = (
    "udc", "title", "authors", "affiliation", "city", "email",
    "abstract_heading", "abstract_problem", "abstract_goal",
    "abstract_results", "abstract_practical", "abstract_remainder", "keywords", "body",
)
REQUIRED = ("title", "authors", "abstract_problem", "abstract_goal", "abstract_results", "abstract_practical")
LABELS = {
    "abstract_problem": re.compile(r"^\s*(?:постановка\s+(?:проблемы|задачи)|проблема)\s*[.:—-]", re.I),
    "abstract_goal": re.compile(r"^\s*цель\s*(?:исследования|работы)?\s*[.:—-]", re.I),
    "abstract_results": re.compile(r"^\s*результат(?:ы)?\s*[.:—-]", re.I),
    "abstract_practical": re.compile(r"^\s*практическая\s+значимость\s*[.:—-]", re.I),
}
_SINGLE_STORY = ("word/footnotes.xml", "word/endnotes.xml", "word/comments.xml")


def _body(parts: dict[str, bytes]):
    root = parse_xml(parts["word/document.xml"])
    body = root.find("w:body", NS)
    if body is None:
        raise DocumentError("DOCX_BODY_MISSING")
    if len(root.findall(".//w:sectPr", NS)) != 1 or body.find("w:sectPr", NS) is None:
        raise DocumentError("MULTI_SECTION_REVIEW")
    if root.xpath(".//w:fldChar | .//w:instrText | .//w:commentRangeStart | .//w:commentRangeEnd", namespaces=NS):
        raise DocumentError("COMPLEX_FIELDS_REVIEW")
    for name in _SINGLE_STORY:
        if name in parts and parse_xml(parts[name]).xpath(".//w:t", namespaces=NS):
            raise DocumentError("OTHER_STORY_REVIEW")
    bookmarks020.validate_body_markers(body)
    return root, body


def _node_text(node) -> str:
    if node.tag == f"{{{W}}}p":
        return paragraph_text(node)
    return " ".join(paragraph_text(p) for p in node.findall(".//w:p", NS))


def inventory(source: Path) -> dict:
    parts = load_package(source)
    _, body = _body(parts)
    blocks = []
    resolver = typo.Resolver(parts)
    in_abstract = False
    in_references = False
    for index, node in enumerate(body):
        if node.tag == f"{{{W}}}sectPr":
            continue
        if node.tag in bookmarks020.MARKERS:
            continue
        if node.tag not in {f"{{{W}}}p", f"{{{W}}}tbl"}:
            raise DocumentError("BODY_NODE_REVIEW")
        raw = ET.tostring(node, encoding="utf-8", with_tail=False)
        block = {
            "id": f"n-{index + 1:06d}", "index": index,
            "kind": "paragraph" if node.tag == f"{{{W}}}p" else "table",
            "text": _node_text(node), "sha256": digest(raw),
            "has_objects": bool(node.xpath(".//w:drawing | .//m:oMath | .//w:hyperlink", namespaces=NS)),
            "format_hints": resolver.hints(node) if node.tag == typo.tag("p") else {},
        }
        text = block["text"].strip()
        if re.fullmatch(r"(?:список литературы|references|bibliography)", text, re.I):
            in_references = True
        elif in_references and (block["format_hints"].get("outline_level") not in {None, "9"} or re.match(r"^(?:информация об авторах|information about the authors|abstract|аннотация)\b", text, re.I)):
            in_references = False
        elif in_references:
            block["format_hints"]["bibliography"] = True
        if re.match(r"^(?:аннотация|реферат|краткое\s+содержание)\s*$", text, re.I):
            in_abstract = True
        elif re.match(r"^ключевые\s+слова", text, re.I):
            in_abstract = False
        ranges = fragments019.ranges(node, in_abstract)
        if ranges:
            for start, end in ranges:
                blocks.append({**block, "id": f"{block['id']}:{start}:{end}", "text": block["text"][start:end], "range": [start, end]})
        else:
            blocks.append(block)
    return {"source_sha256": digest(source.read_bytes()), "blocks": blocks}


def suggest_roles(blocks: list[dict]) -> tuple[dict[str, str], list[str]]:
    """Recognize explicit Russian labels only; do not infer missing facts."""
    assignments: dict[str, str] = {}
    questions: list[str] = []
    in_abstract = False
    seen_abstract = False
    seen_title = False
    seen_authors = False
    keyword_value_pending = False
    for block in blocks:
        text = block["text"].strip()
        role = "body"
        if block["kind"] == "table":
            assignments[block["id"]] = role
            continue
        if re.match(r"^(?:рабочая\s+(?:рукопись|заметка)|редакционная\s+заметка)\b", text, re.I):
            role = "editorial"
        elif re.match(r"^удк\b", text, re.I):
            role = "udc"
        elif re.match(r"^(?:аннотация|реферат|краткое\s+содержание)\s*$", text, re.I):
            role = "abstract_heading"
            in_abstract = True
            seen_abstract = True
        elif re.match(r"^ключевые\s+слова(?:\s*[:—-]|\s*$)", text, re.I):
            role = "keywords"
            in_abstract = False
            keyword_value_pending = bool(re.fullmatch(r"ключевые\s+слова\s*[:—-]?", text, re.I))
        elif keyword_value_pending and text and not re.match(r"^\d+[. ]|^(?:введение|заключение)\b", text, re.I):
            role = "keywords"
            keyword_value_pending = False
        elif not text and not block.get("has_objects") and assignments:
            role = next(reversed(assignments.values()))
        elif seen_title and not seen_abstract and re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text):
            role = "email"
        elif seen_authors and not seen_abstract and re.search(r"(?:университет|институт|академия|university|institute)", text, re.I):
            role = "affiliation"
        elif seen_authors and not seen_abstract and re.fullmatch(r"\([^()\n]{2,100}\)", text):
            role = "city"
        elif in_abstract:
            role = next((name for name, label in LABELS.items() if label.match(text)), "abstract_remainder")
            if role == "abstract_remainder" and text:
                questions.append(f"Неразобранный фрагмент аннотации: {block['id']}")
        elif text and not seen_title and len(text) < 400:
            role = "title"
            seen_title = True
        elif text and seen_title and not seen_authors and not seen_abstract and len(text) < 240 and not re.match(r"^(?:введение|проблема|постановка|глава)\b", text, re.I):
            role = "authors"
            seen_authors = True
        assignments[block["id"]] = role
    return assignments, questions


def _style(node) -> dict:
    if node.tag != f"{{{W}}}p":
        return {}
    ppr = node.find("w:pPr", NS)
    first_run = node.find(".//w:r", NS)
    rpr = first_run.find("w:rPr", NS) if first_run is not None else None
    return {
        "pPr": ET.tostring(ppr, encoding="unicode") if ppr is not None else None,
        "rPr": ET.tostring(rpr, encoding="unicode") if rpr is not None else None,
    }


def inspect_templates(paths: list[Path], plans: dict | None = None) -> dict:
    if not 1 <= len(paths) <= 10:
        raise DocumentError("TEMPLATE_COUNT")
    samples = []
    variants: dict[str, dict[str, list[str]]] = {}
    styles: dict[str, dict[str, dict]] = {}
    for path in paths:
        parts = load_package(path)
        _, body = _body(parts)
        inv = inventory(path)
        resolver = typo.Resolver(parts)
        base = typo.base_profile(resolver)
        bkey = digest(json.dumps(base, sort_keys=True).encode())[:16]
        variants.setdefault("__base__", {}).setdefault(bkey, []).append(path.name)
        styles.setdefault("__base__", {})[bkey] = base
        geometry = typo.section_profile(body.find("w:sectPr", NS))
        gkey = digest(json.dumps(geometry, sort_keys=True).encode())[:16]
        variants.setdefault("__document__", {}).setdefault(gkey, []).append(path.name)
        styles.setdefault("__document__", {})[gkey] = geometry
        assignments, questions = suggest_roles(inv["blocks"])
        if plans and inv["source_sha256"] in plans:
            assignments = plans[inv["source_sha256"]]["assignments"]
        observations = []
        for block in inv["blocks"]:
            role = assignments[block["id"]]
            if role in SLOTS:
                node = _block_nodes(body, block)[0]
                role = (plans or {}).get(inv["source_sha256"], {}).get("contexts", {}).get(block["id"]) or typo.context(role, node, block.get("format_hints"))
                style = typo.table_profile(node, resolver) if node.tag == typo.tag("tbl") else typo.measure(node, resolver, role)
                key = digest(json.dumps(style, sort_keys=True).encode())[:16]
                variants.setdefault(role, {}).setdefault(key, []).append(path.name)
                styles.setdefault(role, {})[key] = style
                observations.append({"role": role, "block_id": block["id"], "style_key": key})
        samples.append({"name": path.name, "sha256": inv["source_sha256"], "observations": observations, "questions": questions})
    conflicts = {role: sources for role, sources in variants.items() if len(sources) > 1}
    return {"schema_version": "web-019", "samples": samples, "variants": variants,
            "styles": styles, "conflicts": conflicts, "approved": False,
            "structure": {"order": list(SLOTS), "required": [r for r in REQUIRED if r in variants]},
            "role_evidence": "model" if plans else "heuristic"}


def _apply_style(node, style: dict) -> None:
    if node.tag != f"{{{W}}}p":
        return
    source_ppr = parse_xml(style["pPr"].encode()) if style.get("pPr") else None
    if source_ppr is not None:
        target_ppr = node.find("w:pPr", NS)
        if target_ppr is None:
            target_ppr = ET.Element(f"{{{W}}}pPr")
            node.insert(0, target_ppr)
        allowed = {"spacing", "ind", "jc", "keepNext", "keepLines", "pageBreakBefore", "widowControl"}
        for child in list(target_ppr):
            if ET.QName(child).localname in allowed:
                target_ppr.remove(child)
        for child in source_ppr:
            if ET.QName(child).localname in allowed:
                target_ppr.append(copy.deepcopy(child))
    source_rpr = parse_xml(style["rPr"].encode()) if style.get("rPr") else None
    if source_rpr is None:
        return
    allowed = {"rFonts", "sz", "szCs", "color"}
    for run in node.findall(".//w:r", NS):
        target_rpr = run.find("w:rPr", NS)
        if target_rpr is None:
            target_rpr = ET.Element(f"{{{W}}}rPr")
            run.insert(0, target_rpr)
        for child in list(target_rpr):
            if ET.QName(child).localname in allowed:
                target_rpr.remove(child)
        for child in source_rpr:
            if ET.QName(child).localname in allowed:
                target_rpr.append(copy.deepcopy(child))


def _placeholder(slot: str):
    paragraph = ET.Element(f"{{{W}}}p")
    ppr = ET.SubElement(paragraph, f"{{{W}}}pPr")
    shd = ET.SubElement(ppr, f"{{{W}}}shd")
    shd.set(f"{{{W}}}fill", "FFF59D")
    run = ET.SubElement(paragraph, f"{{{W}}}r")
    text = ET.SubElement(run, f"{{{W}}}t")
    text.text = f"[ЗАПОЛНИТЬ: {slot}]"
    return paragraph


def _audit_source_nodes(original: list, output: list) -> None:
    source_text = Counter(_node_text(node) for node in original)
    output_text = Counter(_node_text(node) for node in output)
    if source_text != output_text:
        raise DocumentError("CONTENT_INTEGRITY")
    def objects(nodes):
        return Counter(ET.QName(e).localname for n in nodes for e in n.iter() if ET.QName(e).localname in {"drawing", "oMath", "oMathPara", "hyperlink"})
    if objects(original) != objects(output):
        raise DocumentError("OBJECT_INTEGRITY")


def _clone_with_bookmark_end(body, index: int) -> list:
    return [bookmarks020.clone_paragraph(body, index)]


def _block_nodes(body, block):
    if block.get("range"):
        return [fragments019.fragment(bookmarks020.clone_paragraph(body, block["index"]), *block["range"])]
    return _clone_with_bookmark_end(body, block["index"])


def compile_document(source: Path, output: Path, *, assignments: dict[str, str] | None = None,
                     approved: bool = False, fonts_ok: bool = False,
                     styles: dict[str, dict] | None = None,
                     editorial_output: Path | None = None, contexts: dict[str, str] | None = None,
                     required: tuple | list = REQUIRED, supplied: dict[str, str] | None = None, model_assigned: bool = False) -> dict:
    parts = load_package(source)
    root, body = _body(parts)
    inv = inventory(source)
    suggested, _ = suggest_roles(inv["blocks"])
    if assignments:
        if not set(assignments) <= set(suggested) or not set(assignments.values()) <= set(SLOTS) | {"editorial", "abstract_remainder"}:
            raise DocumentError("ROLE_ASSIGNMENT_INVALID")
        suggested.update(assignments)
    if "editorial" in suggested.values():
        if editorial_output is None:
            raise DocumentError("EDITORIAL_OUTPUT_REQUIRED")
        if editorial_output.resolve() in {source.resolve(), output.resolve()}:
            raise DocumentError("EDITORIAL_OUTPUT_CONFLICT")
    questions = [f"Неразобранный фрагмент аннотации: {block['id']}" for block in inv["blocks"]
                 if suggested[block["id"]] == "abstract_remainder" and block["text"].strip()
                 and block["id"] not in (assignments or {})]
    if set(assignments or {}) != set(suggested):
        questions.append("Роли всех исходных блоков ещё не подтверждены")
    resolver = typo.Resolver(parts)
    original_bookmarks = bookmarks020.signature(body)
    original = [n for block in inv["blocks"] for n in _block_nodes(body, block)]
    ordered = []
    reordered_source = []
    editorial = []
    supplied = supplied or {}
    if not set(required) <= set(SLOTS) or not set(supplied) <= set(required) or any(not isinstance(t, str) or not t.strip() or len(t)>10000 for t in supplied.values()):
        raise DocumentError("SUPPLIED_DATA_INVALID")
    absent = [role for role in required if role not in suggested.values()]
    if not set(supplied) <= set(absent):
        raise DocumentError("SUPPLIED_DATA_DUPLICATE")
    missing = [role for role in absent if role not in supplied]
    for role in SLOTS:
        if role in absent:
            placeholder = _placeholder(role)
            if role in supplied:
                placeholder.find("w:r/w:t", NS).text = supplied[role]
                placeholder.remove(placeholder.find("w:pPr", NS))
            if (styles or {}).get(role, {}).get("schema") == "typography-019":
                typo.apply(placeholder, styles[role], resolver, role)
                if role in missing:
                    placeholder.find("w:pPr", NS).append(typo.prop("shd", fill="FFF59D"))
            ordered.append(placeholder)
        for block in inv["blocks"]:
            if suggested[block["id"]] == role:
                nodes = _block_nodes(body, block)
                key = (contexts or {}).get(block["id"]) or typo.context(role, nodes[0], block.get("format_hints"))
                if key.split(".")[0] != role or (block["id"] in (contexts or {}) and key not in (styles or {})):
                    raise DocumentError("FORMAT_CONTEXT_INVALID")
                if styles and any(v.get("schema") == "typography-019" for v in styles.values()) and key not in styles:
                    questions.append(f"Нет подтверждённого оформления: {key} ({block['id']})")
                style = (styles or {}).get(key) or (styles or {}).get(role)
                if style and style.get("conditional_style_review"):
                    questions.append(f"Условное оформление таблицы требует проверки: {block['id']}")
                if style and style.get("schema") == "typography-019":
                    if nodes[0].tag == typo.tag("tbl"):
                        typo.apply_table(nodes[0], style, resolver)
                    else:
                        typo.apply(nodes[0], style, resolver, key)
                elif style:
                    _apply_style(nodes[0], style)
                ordered.extend(nodes)
                reordered_source.extend(nodes)
    for block in inv["blocks"]:
        if suggested[block["id"]] == "editorial":
            editorial.extend(_block_nodes(body, block))
    # Editorial text is kept in a separate review result; it is not authorship.
    _audit_source_nodes(original, reordered_source + editorial)
    if typo.scientific_signature(original) != typo.scientific_signature(reordered_source + editorial):
        raise DocumentError("SCIENTIFIC_PAYLOAD_INTEGRITY")
    if original_bookmarks != bookmarks020.signature(reordered_source + editorial):
        raise DocumentError("BOOKMARK_RANGE_CHANGED")
    # A valid combined stream must not conceal a range split across two files.
    bookmarks020.signature(reordered_source)
    bookmarks020.signature(editorial)
    sect = copy.deepcopy(body.find("w:sectPr", NS))
    if (styles or {}).get("__document__"):
        typo.apply_section(sect, styles["__document__"])
    body[:] = []
    body.extend(ordered)
    body.append(sect)
    parts["word/document.xml"] = xml_bytes(root)
    if (styles or {}).get("__base__"):
        typo.apply_base(parts, styles["__base__"])
    write_package(output, parts)
    if editorial:
        if editorial_output is None or any(suggested[b["id"]] == "editorial" and b["id"] not in (assignments or {}) for b in inv["blocks"]):
            questions.append("Редакционная заметка сохранена отдельно от статьи")
        if editorial_output is not None:
            editorial_root = copy.deepcopy(root)
            editorial_body = editorial_root.find("w:body", NS)
            editorial_body[:] = editorial + [copy.deepcopy(sect)]
            editorial_parts = dict(parts)
            editorial_parts["word/document.xml"] = xml_bytes(editorial_root)
            write_package(editorial_output, editorial_parts)
    if model_assigned:
        for block in inv["blocks"]:
            if suggested[block["id"]] == "editorial" and not re.match(r"^(?:рабочая\s+(?:рукопись|заметка)|редакционная\s+заметка)\b", block["text"].strip(), re.I):
                questions.append(f"Подтвердите вынос фрагмента в редакционные заметки: {block['id']}")
    if missing:
        questions.extend(f"Отсутствует обязательный слот: {slot}" for slot in missing)
    if styles and any(profile.get("schema") != "typography-019" for profile in styles.values()):
        questions.append("Старый профиль оформления: загрузите эталоны заново и утвердите шаблон версии 019")
    if not approved:
        questions.append("Версия шаблона не утверждена")
    if not fonts_ok:
        questions.append("Точные Arial и Times New Roman не подтверждены")
    return {
        "status": "ready" if not questions else "draft", "source_sha256": inv["source_sha256"],
        "output_sha256": digest(output.read_bytes()), "assignments": suggested,
        "questions": questions, "missing": missing, "supplied_slots": list(supplied), "source_blocks": len(original),
        "output_blocks": len(ordered), "editorial_blocks": len(editorial),
    }
