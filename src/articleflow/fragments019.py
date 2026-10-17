"""Exact ranges for explicitly labelled, plain-text abstract paragraphs."""
import copy
import re
from lxml import etree as ET
from .docx_engine import NS, W, DocumentError, paragraph_text

LABEL = re.compile(r"(?<!\w)(?:постановка\s+(?:проблемы|задачи)|проблема|цель(?:\s+(?:работы|исследования))?|результаты?|практическая\s+значимость)\s*[.:]", re.I)


def ranges(node, in_abstract):
    if not in_abstract or node.tag != f"{{{W}}}p":
        return []
    text = paragraph_text(node)
    matches = list(LABEL.finditer(text))
    if len(matches) < 2:
        return []
    # Never split fields, bookmarks, drawings, formulas or hyperlinks.
    if any(ET.QName(n).localname not in {"pPr", "r"} for n in node):
        return []
    if any(ET.QName(n).localname not in {"rPr", "t"} for r in node.findall("w:r", NS) for n in r):
        return []
    boundaries = sorted({0, len(text), *(m.start() for m in matches)})
    return list(zip(boundaries, boundaries[1:]))


def fragment(node, start, end):
    text = paragraph_text(node)
    if not 0 <= start < end <= len(text):
        raise DocumentError("FRAGMENT_RANGE_INVALID")
    out = copy.deepcopy(node)
    for n in list(out):
        if n.tag != f"{{{W}}}pPr":
            out.remove(n)
    offset = 0
    for run in node.findall("w:r", NS):
        new = copy.deepcopy(run)
        for n in list(new):
            if n.tag != f"{{{W}}}rPr":
                new.remove(n)
        for t in run.findall("w:t", NS):
            value = t.text or ""
            left, right = max(0, start-offset), min(len(value), end-offset)
            if right > left:
                c = copy.deepcopy(t)
                c.text = value[left:right]
                c.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                new.append(c)
            offset += len(value)
        if new.findall("w:t", NS):
            out.append(new)
    if paragraph_text(out) != text[start:end]:
        raise DocumentError("FRAGMENT_CONTENT_INTEGRITY")
    return out
