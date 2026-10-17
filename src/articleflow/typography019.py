"""Portable measured typography, without reference text or paragraph indices.

The resolver supports docDefaults, basedOn, paragraph and character styles,
direct formatting and theme Latin fonts. Complex Word layout is still gated
by the importer. Context keys express reusable roles, never gold bindings.
"""
from __future__ import annotations

import copy
import re
from collections import Counter
from lxml import etree as ET

from .docx_engine import NS, W, DocumentError, parse_xml, paragraph_text

def tag(name):
    return f"{{{W}}}{name}"


def child(parent, name):
    return parent.find(tag(name)) if parent is not None else None


def value(parent, name, fallback=None):
    n = child(parent, name)
    return n.get(tag("val"), fallback) if n is not None else fallback


def prop(name, **attrs):
    return ET.Element(tag(name), {tag(k): str(v) for k, v in attrs.items()})


def merge(target, incoming, *, toggle=False):
    if incoming is None:
        return
    for node in incoming:
        name = ET.QName(node).localname
        if name in {"pStyle", "rStyle", "sectPr", "rPr"}:
            continue
        old = target.find(node.tag)
        new = copy.deepcopy(node)
        if old is not None:
            # Attribute-level inheritance matters for ind/spacing/rFonts.
            attrs = dict(old.attrib)
            attrs.update(new.attrib)
            new.attrib.clear()
            new.attrib.update(attrs)
            target.remove(old)
        if toggle and name in {"b", "i", "bCs", "iCs", "caps", "smallCaps", "strike"}:
            on = node.get(tag("val"), "1") not in {"0", "false", "off"}
            previous = old is not None and old.get(tag("val"), "1") not in {"0", "false", "off"}
            new.set(tag("val"), "1" if previous != on else "0")
        target.append(new)


def stable_xml(node):
    # Do not hash namespace maps copied from particular Word documents.
    out = ET.Element(node.tag, nsmap={"w": W})
    orders = {
        "pPr": "pStyle keepNext keepLines pageBreakBefore framePr widowControl numPr suppressLineNumbers pBdr shd tabs suppressAutoHyphens kinsoku wordWrap overflowPunct topLinePunct autoSpaceDE autoSpaceDN bidi adjustRightInd snapToGrid spacing ind contextualSpacing mirrorIndents suppressOverlap jc textDirection textAlignment textboxTightWrap outlineLvl divId cnfStyle rPr sectPr pPrChange",
        "rPr": "rStyle rFonts b bCs i iCs caps smallCaps strike dstrike outline shadow emboss imprint noProof snapToGrid vanish webHidden color spacing w kern position sz szCs highlight u effect bdr shd fitText vertAlign rtl cs em lang eastAsianLayout specVanish oMath rPrChange",
        "sectPr": "headerReference footerReference footnotePr endnotePr type pgSz pgMar paperSrc pgBorders lnNumType pgNumType cols formProt vAlign noEndnote titlePg textDirection bidi rtlGutter docGrid printerSettings sectPrChange",
        "tblPr": "tblStyle tblpPr tblOverlap bidiVisual tblStyleRowBandSize tblStyleColBandSize tblW jc tblCellSpacing tblInd tblBorders shd tblLayout tblCellMar tblLook tblCaption tblDescription tblPrChange",
    }
    def append(src, dst):
        for k, v in sorted(src.attrib.items()):
            dst.set(k, v)
        order = orders.get(ET.QName(src).localname, "").split()
        children = sorted(src, key=lambda x: order.index(ET.QName(x).localname) if ET.QName(x).localname in order else len(order)) if order else src
        for c in children:
            n = ET.SubElement(dst, c.tag)
            append(c, n)
    append(node, out)
    return ET.tostring(out, encoding="unicode")


class Resolver:
    def __init__(self, parts):
        self.styles = parse_xml(parts.get("word/styles.xml", f'<w:styles xmlns:w="{W}"/>'.encode()))
        self.by_id = {s.get(tag("styleId")): s for s in self.styles.findall(tag("style"))}
        self.default = next((k for k, s in self.by_id.items() if s.get(tag("default")) == "1" and s.get(tag("type")) == "paragraph"), None)
        self.theme = {}
        if "word/theme/theme1.xml" in parts:
            root = parse_xml(parts["word/theme/theme1.xml"])
            a = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
            for kind in ("major", "minor"):
                n = root.find(f".//a:fontScheme/a:{kind}Font/a:latin", a)
                if n is not None:
                    self.theme[kind] = n.get("typeface")

    def chain(self, sid, visited=None):
        visited = set() if visited is None else visited
        if sid is None or sid not in self.by_id:
            return []
        if sid in visited:
            raise DocumentError("STYLE_CYCLE")
        visited.add(sid)
        style = self.by_id[sid]
        return self.chain(value(style, "basedOn"), visited) + [style]

    def resolve(self, paragraph, run=None):
        p = ET.Element(tag("pPr"))
        r = ET.Element(tag("rPr"))
        merge(p, self.styles.find("w:docDefaults/w:pPrDefault/w:pPr", NS))
        merge(r, self.styles.find("w:docDefaults/w:rPrDefault/w:rPr", NS))
        tables = paragraph.xpath("ancestor::w:tbl", namespaces=NS)
        if tables:
            for style in self.chain(value(child(tables[-1], "tblPr"), "tblStyle")):
                merge(p, child(style, "pPr"))
                merge(r, child(style, "rPr"), toggle=True)
        ppr = child(paragraph, "pPr")
        for style in self.chain(value(ppr, "pStyle", self.default)):
            merge(p, child(style, "pPr"))
            merge(r, child(style, "rPr"), toggle=True)
        merge(p, ppr)
        if run is not None:
            rpr = child(run, "rPr")
            for style in self.chain(value(rpr, "rStyle")):
                merge(r, child(style, "rPr"), toggle=True)
            merge(r, rpr)
        fonts = child(r, "rFonts")
        if fonts is not None:
            for key, theme_key in (("ascii", "asciiTheme"), ("hAnsi", "hAnsiTheme"), ("eastAsia", "eastAsiaTheme"), ("cs", "cstheme")):
                theme = fonts.get(tag(theme_key))
                if fonts.get(tag(key)) is None and theme:
                    resolved = self.theme.get("major" if theme.startswith("major") else "minor")
                    if resolved:
                        fonts.set(tag(key), resolved)
                fonts.attrib.pop(tag(theme_key), None)
        return p, r

    def hints(self, paragraph):
        p, r = self.resolve(paragraph)
        direct = child(paragraph, "pPr")
        fonts = child(r, "rFonts")
        return {"style": value(direct, "pStyle"), "outline_level": value(p, "outlineLvl"),
                "font": fonts.get(tag("ascii")) if fonts is not None else None,
                "size_half_points": value(r, "sz"), "keep_next": value(p, "keepNext")}


def context(role, node, hints=None):
    text = paragraph_text(node).strip() if node.tag == tag("p") else ""
    if node.tag == tag("tbl"):
        return "body.table"
    if not text and not node.xpath(".//w:drawing | .//m:oMath | .//w:hyperlink", namespaces=NS):
        return role + ".spacing"
    if role == "keywords":
        return "keywords.heading" if re.fullmatch(r"(?:ключевые слова|keywords)\s*:??", text, re.I) else "keywords"
    if role != "body":
        return role
    if re.match(r"^(?:рис(?:унок)?\.?|fig(?:ure)?\.?)\s*\d", text, re.I):
        return "body.figure_caption"
    if re.match(r"^(?:таблица|table)\s*\d", text, re.I):
        return "body.table_caption"
    if not text and node.findall(".//w:drawing", NS):
        return "body.figure"
    level = (hints or {}).get("outline_level")
    if level is not None and str(level).isdigit() and int(level) < 9:
        return "body.heading." + str(int(level) + 1)
    if (hints or {}).get("bibliography"):
        return "body.references"
    numbered = re.match(r"^(\d+(?:\.\d+)*)\.?\s+\S", text)
    if numbered and len(text) < 160:
        return "body.heading." + str(numbered.group(1).count(".") + 1)
    if re.fullmatch(r"(?:введение|заключение|выводы|список литературы|references|introduction|conclusions?)", text, re.I):
        return "body.heading.1"
    return "body"


def measure(paragraph, resolver, key):
    p, base = resolver.resolve(paragraph)
    # A numbering ID belongs to the source package, never to a portable style.
    numbering = child(p, "numPr")
    if numbering is not None:
        p.remove(numbering)
    runs = paragraph.findall(".//w:r", NS)
    text_runs = [r for r in runs if paragraph_text(r)]
    dominant = max(text_runs, key=lambda r: len(paragraph_text(r)), default=None)
    if dominant is not None:
        _, font_source = resolver.resolve(paragraph, dominant)
        # Body local emphasis is content. It must not become a universal rule.
        if key in {"body", "body.table", "body.references"}:
            font_only = ET.Element(tag("rPr"))
            for n in font_source:
                if ET.QName(n).localname in {"rFonts", "sz", "szCs", "color", "lang"}:
                    font_only.append(copy.deepcopy(n))
            merge(base, font_only)
        else:
            base = font_source
    result = {"schema": "typography-019", "pPr": stable_xml(p), "rPr": stable_xml(base)}
    # Word may split a label before its punctuation (e.g. bold word, plain dot).
    match = re.match(r"^\s*(?:постановка\s+(?:проблемы|задачи)|проблема|цель(?:\s+(?:исследования|работы))?|результаты?|практическая\s+значимость)([.:])\s*", paragraph_text(paragraph), re.I)
    if key.startswith("abstract_") and key != "abstract_heading" and match and len(text_runs) > 1:
        _, label = resolver.resolve(paragraph, text_runs[0])
        _, rest = resolver.resolve(paragraph, text_runs[-1])
        result["label_rPr"] = stable_xml(label)
        result["rPr"] = stable_xml(rest)
        offset = 0
        for run in text_runs:
            if offset <= match.start(1) < offset + len(paragraph_text(run)):
                _, punctuation = resolver.resolve(paragraph, run)
                if stable_xml(punctuation) != stable_xml(label):
                    result["label_scope"] = "words"
                break
            offset += len(paragraph_text(run))
    return result


def _replace(parent, name, new):
    old = child(parent, name)
    if old is not None:
        parent.remove(old)
    parent.insert(0, copy.deepcopy(new))


def apply(paragraph, profile, resolver, key):
    if paragraph.tag != tag("p"):
        return
    label = re.match(r"^[^.:]{1,80}[.:]\s*", paragraph_text(paragraph)) if profile.get("label_rPr") else None
    label_end = (len(label.group().rstrip().rstrip(".:")) if profile.get("label_scope") == "words" else label.end()) if label else 0
    offset = 0
    if label:
        for run in list(paragraph.findall("w:r", NS)):
            text = paragraph_text(run)
            boundary = label_end - offset
            if 0 < boundary < len(text) and all(ET.QName(c).localname in {"rPr", "t"} for c in run):
                position = paragraph.index(run)
                for i, part in enumerate((text[:boundary], text[boundary:])):
                    clone = copy.deepcopy(run)
                    for c in list(clone):
                        if c.tag != tag("rPr"): clone.remove(c)
                    n = ET.SubElement(clone, tag("t")); n.text = part
                    n.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                    paragraph.insert(position+i, clone)
                paragraph.remove(run)
            offset += len(text)
    semantic = []
    for run in paragraph.findall(".//w:r", NS):
        _, r = resolver.resolve(paragraph, run)
        semantic.append((run, r))
    source_p = child(paragraph, "pPr")
    p = parse_xml(profile["pPr"].encode())
    # Also protect previously saved 019 profiles carrying foreign numIds.
    for n in list(p):
        if n.tag in {tag("numPr"), tag("sectPr")}:
            p.remove(n)
    # Numbering and source bindings are content, not template style IDs.
    if source_p is not None:
        for n in source_p:
            if ET.QName(n).localname in {"numPr", "sectPr"}:
                p.append(copy.deepcopy(n))
    _replace(paragraph, "pPr", p)
    offset = 0
    label = re.match(r"^[^.:]{1,80}[.:]\s*", paragraph_text(paragraph)) if profile.get("label_rPr") else None
    for run, source_r in semantic:
        length = len(paragraph_text(run))
        chosen = profile.get("label_rPr") if label and offset < label_end else profile["rPr"]
        r = parse_xml(chosen.encode())
        preserve = {"vertAlign"}
        if key in {"body", "body.table", "body.references", "keywords"}:
            preserve |= {"b", "i", "bCs", "iCs", "u", "strike", "dstrike", "highlight"}
        for n in source_r:
            if ET.QName(n).localname in preserve:
                old = r.find(n.tag)
                if old is not None:
                    r.remove(old)
                r.append(copy.deepcopy(n))
        # Explicit zeros block source paragraph-style emphasis inheritance.
        for name in ("b", "i", "bCs", "iCs"):
            if child(r, name) is None:
                r.append(prop(name, val="0"))
        _replace(run, "rPr", r)
        offset += length


def section_profile(section):
    result = ET.Element(tag("sectPr"))
    for n in section:
        if ET.QName(n).localname in {"pgSz", "pgMar", "cols", "docGrid"}:
            result.append(copy.deepcopy(n))
    return {"schema": "typography-019", "section": stable_xml(result)}


def base_profile(resolver):
    p, r = resolver.resolve(ET.Element(tag("p")))
    return {"schema": "typography-019", "pPr": stable_xml(p), "rPr": stable_xml(r)}


def apply_base(parts, profile):
    """Paragraph end marks and math inherit the target document defaults too."""
    styles = parse_xml(parts["word/styles.xml"])
    normal = next((s for s in styles.findall(tag("style")) if s.get(tag("default")) == "1" and s.get(tag("type")) == "paragraph"), None)
    if normal is None:
        raise DocumentError("DEFAULT_STYLE_MISSING")
    defaults = styles.find(tag("docDefaults"))
    if defaults is None:
        defaults = ET.Element(tag("docDefaults"))
        styles.insert(0, defaults)
    for kind in ("pPr", "rPr"):
        container = defaults.find(tag(kind + "Default"))
        if container is None:
            container = ET.SubElement(defaults, tag(kind + "Default"))
        container[:] = [parse_xml(profile[kind].encode())]
        old = child(normal, kind)
        if old is not None:
            normal.remove(old)
        normal.append(parse_xml(profile[kind].encode()))
    from .docx_engine import xml_bytes
    parts["word/styles.xml"] = xml_bytes(styles)


def apply_section(section, profile):
    for n in parse_xml(profile["section"].encode()):
        old = section.find(n.tag)
        if old is not None:
            section.remove(old)
        section.append(copy.deepcopy(n))


def table_profile(table, resolver):
    first = table.find(".//w:p", NS)
    profile = measure(first, resolver, "body.table") if first is not None else {}
    grid = table.find("w:tblGrid", NS)
    widths = [int(n.get(tag("w"), "0")) for n in grid] if grid is not None else []
    profile["table_width"] = sum(widths)
    rows = table.findall("w:tr", NS)
    if len(rows) > 1:
        def bold_text(row):
            flags = []
            for p in row.findall(".//w:p", NS):
                for r in p.findall(".//w:r", NS):
                    if paragraph_text(r).strip():
                        _, effective = resolver.resolve(p, r)
                        flags.append(child(effective, "b") is not None and value(effective, "b", "1") not in {"0", "false", "off"})
            return flags
        first_flags = bold_text(rows[0])
        later_flags = [f for row in rows[1:] for f in bold_text(row)]
        if first_flags and all(first_flags) and later_flags and not all(later_flags):
            # Observation requires the same template approval as other variants.
            profile["first_row"] = measure(first, resolver, "body.table.header")
    properties = ET.Element(tag("tblPr"))
    for style in resolver.chain(value(child(table, "tblPr"), "tblStyle")):
        if style.findall("w:tblStylePr", NS):
            profile["conditional_style_review"] = True
        merge(properties, child(style, "tblPr"))
    merge(properties, child(table, "tblPr"))
    for n in list(properties):
        if ET.QName(n).localname in {"tblStyle", "tblCaption", "tblDescription"}:
            properties.remove(n)
    profile["tblPr"] = stable_xml(properties)
    return profile


def apply_table(table, profile, resolver):
    first_row = table.find("w:tr", NS)
    for p in table.findall(".//w:p", NS):
        header = profile.get("first_row") if first_row is not None and first_row in p.iterancestors() else None
        apply(p, header or profile, resolver, "body.table.header" if header else "body.table")
    if profile.get("tblPr"):
        target = parse_xml(profile["tblPr"].encode())
        old = child(table, "tblPr")
        if old is not None:
            for n in old:
                if ET.QName(n).localname in {"tblCaption", "tblDescription"}:
                    target.append(copy.deepcopy(n))
        _replace(table, "tblPr", target)
    grid = table.find("w:tblGrid", NS)
    if grid is None or not profile.get("table_width"):
        return
    old = [int(n.get(tag("w"), "0")) for n in grid]
    if not sum(old):
        return
    ratio = profile["table_width"] / sum(old)
    for n, width in zip(grid, old):
        n.set(tag("w"), str(round(width * ratio)))
    for n in table.findall(".//w:tcW", NS):
        if n.get(tag("type")) == "dxa":
            n.set(tag("w"), str(round(int(n.get(tag("w"), "0")) * ratio)))


def scientific_signature(nodes):
    """Content and bindings excluding only formatting properties; detects loss."""
    def canonical(n):
        local = ET.QName(n).localname
        if n.tag == tag("pPr"):
            protected = tuple(canonical(c) for c in n if ET.QName(c).localname in {"numPr", "sectPr"})
            return (n.tag, protected) if protected else None
        if n.tag.startswith("{" + W + "}") and local in {"rPr", "tblPr", "tblGrid", "trPr"}:
            return None
        if n.tag == tag("tcPr"):
            # Cell merges and span topology remain protected.
            return (n.tag, tuple(canonical(c) for c in n if ET.QName(c).localname in {"gridSpan", "vMerge", "hMerge"}))
        children = []
        for c in n:
            v = canonical(c)
            if v is None: continue
            children.extend(v[1] if v[0] == "run-content" else [v])
        merged = []
        for v in children:
            if merged and v[0] == tag("t") and merged[-1][0] == tag("t") and v[1] == merged[-1][1]:
                previous = merged.pop(); merged.append((v[0], v[1], previous[2]+v[2], ()))
            else: merged.append(v)
        if n.tag == tag("r"):
            return ("run-content", tuple(merged))
        attrs = tuple(sorted((k,v) for k,v in n.attrib.items() if not (n.tag == tag("t") and k == "{http://www.w3.org/XML/1998/namespace}space")))
        return (n.tag, attrs, n.text or "", tuple(merged))
    return Counter(canonical(n) for n in nodes)
