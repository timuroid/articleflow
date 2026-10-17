"""Ordered content and recursive table topology gates for the 023 renderer."""
from .docx_engine import NS, load_package, parse_xml, content_fingerprint, compare_emphasis
from .catalogue import placement_fingerprint


def topology(source):
    root=parse_xml(load_package(source)['word/document.xml'])
    def walk(node):
        local=node.tag.rsplit('}',1)[-1]
        if local=='p':return ['paragraph']
        if local in {'tbl','tr','tc','body'}:
            merge=[]
            if local=='tc':
                merge=[(n.tag,tuple(sorted(n.attrib.items()))) for n in node.xpath('./w:tcPr/w:gridSpan | ./w:tcPr/w:vMerge | ./w:tcPr/w:hMerge',namespaces=NS)]
            return [local,merge,[walk(c) for c in node if c.tag.rsplit('}',1)[-1] in {'tbl','tr','tc','p'}]]
    return walk(root.find('w:body',NS))


def check(source,target):
    return {'content_exact':content_fingerprint(source)==content_fingerprint(target),
            'placements_exact':placement_fingerprint(source)==placement_fingerprint(target),
            'nested_topology_exact':topology(source)==topology(target),
            'protected_vertical_exact':compare_emphasis(source,target)['protected_vertical_exact']}
