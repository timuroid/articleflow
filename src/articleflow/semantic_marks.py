"""Explicit source emphasis payload, independent of target fonts and layout."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from lxml import etree as ET

from .catalogue import Catalogue
from .docx_engine import NS, W, DocumentError, content_fingerprint, digest, emphasis_masks, parse_xml

VERSION = "source-marks-0.7"
BASELINE = (False, False, "baseline")


def extract_marks(source: Path, content_path: Path) -> dict:
    raw = content_path.read_bytes()
    content = json.loads(raw)
    texts = [b["text"] for b in content["blocks"]]
    if content_fingerprint(source)["paragraphs"] != texts:
        raise DocumentError("MARKS_SOURCE_TEXT_MISMATCH")
    masks = emphasis_masks(source)
    if len(masks) != len(texts) or any(len(m) != len(t) for m, t in zip(masks, texts)):
        raise DocumentError("MARKS_SOURCE_COVERAGE")
    blocks = []
    for block, mask in zip(content["blocks"], masks):
        ranges = []
        for offset, flags in enumerate(mask):
            if flags == BASELINE:
                continue
            if ranges and ranges[-1]["end"] == offset and tuple(ranges[-1]["flags"]) == flags:
                ranges[-1]["end"] += 1
            else:
                ranges.append({"start": offset, "end": offset + 1, "flags": list(flags)})
        blocks.append({"id": block["id"], "length": len(mask), "marks": ranges})
    return {"schema_version": VERSION, "protocol": "explicit_source_emphasis_I2_like",
            "input_sha256": digest(raw), "source_sha256": digest(source.read_bytes()), "blocks": blocks}


def expand_mark_styles(template: dict) -> tuple[dict, dict]:
    """Generate every flag combination without inspecting source text or ranges."""
    result = copy.deepcopy(template)
    catalogue, mapping = Catalogue(), {}
    for key, raw in template["styles"]["character"].items():
        if len(raw) > 1:
            raise DocumentError("CHARACTER_PROPERTIES_MULTIPLE")
        mapping[key] = {}
        for bold in (False, True):
            for italic in (False, True):
                for vertical in ("baseline", "superscript", "subscript"):
                    node = parse_xml(raw[0].encode()) if raw else ET.Element(f"{{{W}}}rPr", nsmap={"w": W})
                    for name, value in (("b", str(int(bold))), ("i", str(int(italic))), ("vertAlign", vertical)):
                        for child in list(node.findall(f"w:{name}", NS)):
                            node.remove(child)
                        ET.SubElement(node, f"{{{W}}}{name}", {f"{{{W}}}val": value})
                    mapping[key][(bold, italic, vertical)] = catalogue.add("character", [node])
    result["styles"]["character"].update(catalogue.styles["character"])
    for role in result["roles"].values():
        role["character_styles"] = sorted(set(role["character_styles"]) |
            {mapped for key in role["character_styles"] for mapped in mapping[key].values()})
    result["emphasis_policy"] = "explicit_source_marks_0.7"
    return result, mapping


def apply_marks(content: dict, plan: dict, payload: dict, mapping: dict) -> dict:
    if payload.get("schema_version") != VERSION or payload.get("input_sha256") != plan["input_sha256"]:
        raise DocumentError("MARKS_INPUT_HASH")
    if [b["id"] for b in payload["blocks"]] != [b["id"] for b in content["blocks"]]:
        raise DocumentError("MARKS_COVERAGE")
    masks = {}
    for item, block in zip(payload["blocks"], content["blocks"]):
        length = len(block["text"])
        if type(item["length"]) is not int or item["length"] != length:
            raise DocumentError("MARKS_LENGTH")
        mask, previous = [BASELINE] * length, 0
        for mark in item["marks"]:
            a, z, flags = mark["start"], mark["end"], mark["flags"]
            if (type(a) is not int or type(z) is not int or not previous <= a < z <= length
                or not isinstance(flags, list) or len(flags) != 3
                or type(flags[0]) is not bool or type(flags[1]) is not bool
                or flags[2] not in ("baseline", "superscript", "subscript")):
                raise DocumentError("MARKS_RANGE")
            mask[a:z] = [tuple(flags)] * (z - a)
            previous = z
        masks[item["id"]] = mask
    result = copy.deepcopy(plan)
    for block in result["blocks"]:
        spans = []
        for span in block["spans"]:
            for offset in range(span["start"], span["end"]):
                style = mapping[span["style"]][masks[block["id"]][offset]]
                if spans and spans[-1]["end"] == offset and spans[-1]["style"] == style:
                    spans[-1]["end"] += 1
                else:
                    spans.append({"start": offset, "end": offset + 1, "style": style})
        block["spans"] = spans
    result["provenance"] = plan.get("provenance", "unknown") + "+source_marks"
    return result
