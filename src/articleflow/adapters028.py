"""Bounded, auditable DOCX import adaptations. Never executes document code."""
from pathlib import Path
from .docx_engine import NS, DocumentError, load_package, parse_xml, xml_bytes, write_package, content_fingerprint


def normalize(source, target):
    parts=load_package(source);changes={}
    for name in list(parts):
        if name!='word/document.xml' and not (name.startswith(('word/header','word/footer')) and name.endswith('.xml')):continue
        root=parse_xml(parts[name]);count=0
        # Proofing annotations and contentless runs carry no manuscript content.
        for node in root.xpath('.//w:proofErr | .//w:r[not(*[not(self::w:rPr)])]',namespaces=NS):
            node.getparent().remove(node);count+=1
        if count:parts[name]=xml_bytes(root);changes[name]=count
    write_package(target,parts)
    if content_fingerprint(source)!=content_fingerprint(target):raise DocumentError('ADAPTER_CONTENT_CHANGED')
    return {'adapter':'proofing-and-empty-runs-v1','removed_nodes':sum(changes.values()),'parts':changes}
