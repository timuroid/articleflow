"""Ordered content and recursive table topology gates for the 023 renderer."""
from .docx_engine import NS, load_package, parse_xml, content_fingerprint, compare_emphasis
from .catalogue import placement_fingerprint


def topology(source):
    root=parse_xml(load_package(source)['word/document.xml'])
    def walk(node):
        local=node.tag.rsplit('}',1)[-1]
        if local=='p':return ['paragraph']
        if local in {'tbl','tr','tc','body','hdr','ftr'}:
            merge=[]
            if local=='tc':
                merge=[(n.tag,tuple(sorted(n.attrib.items()))) for n in node.xpath('./w:tcPr/w:gridSpan | ./w:tcPr/w:vMerge | ./w:tcPr/w:hMerge',namespaces=NS)]
            return [local,merge,[walk(c) for c in node if c.tag.rsplit('}',1)[-1] in {'tbl','tr','tc','p'}]]
    from .stories026 import roots
    return {name:walk(story) for name,story in roots(load_package(source))}


def section_boundaries(source):
    root=parse_xml(load_package(source)['word/document.xml'])
    return ([p.find('w:pPr/w:sectPr',NS) is not None for p in root.findall('w:body//w:p',NS)],root.find('w:body/w:sectPr',NS) is not None)


def check(source,target):
    return {'section_boundaries_exact':section_boundaries(source)==section_boundaries(target),'content_exact':content_fingerprint(source)==content_fingerprint(target),
            'placements_exact':placement_fingerprint(source)==placement_fingerprint(target),
            'nested_topology_exact':topology(source)==topology(target),
            'protected_vertical_exact':compare_emphasis(source,target)['protected_vertical_exact']}
