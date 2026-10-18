"""Export a private, style-free role packet for external teacher.json authoring.

The packet uses the same ordered ``extract_input(...)["blocks"]`` sequence as
``import-semantic-template``. It contains exact extracted text and content
atoms, plus structural features; the style catalogue and oracle plan never
leave the temporary extraction area. This command does not call a model.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

from articleflow.agent023 import extract_input
from articleflow.docx_engine import DocumentError, digest
from articleflow.rules023 import features


SCHEMA = "external-semantic-packet-037"
STRUCTURAL_FEATURES = (
    "depth", "columns", "column", "row_band", "story_kind",
    "section_boundary", "previous_kind", "next_kind", "language",
    "role_transition_language", "list_level", "list_kind", "field_commands",
)


def export_packet(references: list[Path], output: Path) -> dict:
    """Publish a new private directory only after every reference is extracted.

    ``references`` are positional: their order determines the global 1-based
    paragraph indices used by both ``groups`` and ``inline.paragraph`` at import.
    The returned summary contains no article text.
    """
    if not 1 <= len(references) <= 10:
        raise DocumentError("EXPORT_REFERENCE_LIMIT")
    # Keep the user-supplied DOCX name (including a .docx symlink) while making
    # the path unambiguous for a later import from another working directory.
    sources = [Path(path).absolute() for path in references]
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise DocumentError("OUTPUT_ALREADY_EXISTS")
    for source in sources:
        if source.suffix.lower() != ".docx" or not source.is_file():
            raise DocumentError("EXPORT_REFERENCE_INVALID")

    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
    published = False
    try:
        scratch = stage / ".extraction"
        references_out = []
        blocks_out = []
        for index, source in enumerate(sources):
            source_hash = digest(source.read_bytes())
            content = extract_input(source, scratch / f"reference-{index + 1}")
            if digest(source.read_bytes()) != source_hash:
                raise DocumentError("EXPORT_SOURCE_CHANGED")
            raw_blocks = content["blocks"]
            structure = features(content, {b["id"]: "unknown" for b in raw_blocks})["paragraph"]
            first = len(blocks_out) + 1
            for block in raw_blocks:
                structural = structure[block["id"]]
                blocks_out.append({
                    "n": len(blocks_out) + 1,
                    "document": index + 1,
                    "import_id": f"{index}:{block['id']}",
                    "content_block": block,
                    "structure": {key: structural[key] for key in STRUCTURAL_FEATURES},
                })
            references_out.append({
                "document": index + 1,
                "source_docx": str(source),
                "sha256": source_hash,
                "first_paragraph": first,
                "last_paragraph": len(blocks_out),
                "paragraphs": len(raw_blocks),
                "content_structure": content["structure"],
                "story_structure": [
                    {"part": story["part"], "structure": story["structure"]}
                    for story in content.get("stories", [])
                ],
            })
        packet = {
            "schema": SCHEMA,
            "model_calls": 0,
            "indexing": "1-based concatenation of content.blocks in the listed DOCX order",
            "reference_order": [row["source_docx"] for row in references_out],
            "references": references_out,
            "paragraphs": len(blocks_out),
            "blocks": blocks_out,
            "teacher_json_contract": {
                "keys": ["roles", "groups", "inline_roles", "inline", "questions"],
                "groups": "{start,end,role}; inclusive global n, cover every block once",
                "inline": "{paragraph,quote,occurrence,role} or {paragraph,start,end,role,quote}; paragraph is global n; Unicode offsets are 0-based and end-exclusive",
                "visual_evidence": "Open source_docx for observations; content_block and structure intentionally contain no source font/color/spacing/style catalogue.",
                "import": "Pass the same DOCX bytes in reference_order to python -m articleflow import-semantic-template.",
            },
        }
        # Scratch contains the target style catalogue and raw DOCX payload.
        # It must never be published as part of the role input.
        shutil.rmtree(scratch)
        packet_path = stage / "packet.json"
        packet_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        packet_path.chmod(0o600)
        (stage / ".gitignore").write_text("*\n", encoding="utf-8")
        if output.exists() or output.is_symlink():
            raise DocumentError("OUTPUT_ALREADY_EXISTS")
        os.rename(stage, output)
        published = True
        return {"schema": SCHEMA, "output": str(output), "references": len(references_out),
                "paragraphs": len(blocks_out), "model_calls": 0}
    finally:
        if not published:
            shutil.rmtree(stage, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new private output directory; contains document text")
    parser.add_argument("references", nargs="+", type=Path, help="1–10 DOCX files in exact import order")
    args = parser.parse_args()
    try:
        summary = export_packet(args.references, args.output)
    except DocumentError as exc:
        parser.exit(2, f"export_semantic_packet037: {exc}\n")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
