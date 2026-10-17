"""Preserve bookmark ranges when Word stores markers between body paragraphs."""
import copy
from .docx_engine import NS, DocumentError, digest
from .typography019 import tag

MARKERS = {tag('bookmarkStart'), tag('bookmarkEnd')}


def _object_signature(node):
    # Namespace declarations inherited from ancestors are serialization detail.
    # Expanded names, attributes, text and tree topology remain protected.
    return (node.tag, tuple(sorted(node.attrib.items())), node.text or '',
            tuple(_object_signature(child) for child in node))


def validate_body_markers(body):
    for i, node in enumerate(body):
        if node.tag not in MARKERS:
            continue
        direction = 1 if node.tag == tag('bookmarkStart') else -1
        j = i + direction
        while 0 <= j < len(body) and body[j].tag in MARKERS:
            j += direction
        if not 0 <= j < len(body) or body[j].tag != tag('p'):
            raise DocumentError('BOOKMARK_BOUNDARY_REVIEW')
    signature(body)


def clone_paragraph(body, index):
    node = copy.deepcopy(body[index])
    if node.tag != tag('p'):
        return node
    before = []
    j = index - 1
    while j >= 0 and body[j].tag in MARKERS:
        if body[j].tag == tag('bookmarkStart'):
            before.append(copy.deepcopy(body[j]))
        j -= 1
    offset = 1 if node.find(tag('pPr')) is not None else 0
    for n in reversed(before):
        node.insert(offset, n); offset += 1
    j = index + 1
    while j < len(body) and body[j].tag in MARKERS:
        if body[j].tag == tag('bookmarkEnd'):
            node.append(copy.deepcopy(body[j]))
        j += 1
    return node


def signature(nodes):
    """Ordered scientific stream enclosed by every named range; no text logging."""
    active, closed, seen = {}, {}, set()
    for root in nodes:
        for node in root.iter():
            if node.tag == tag('bookmarkStart'):
                key = node.get(tag('id'))
                if key is None or key in seen:
                    raise DocumentError('BOOKMARK_INVALID')
                seen.add(key); active[key] = (tuple(sorted(node.attrib.items())), [])
            elif node.tag == tag('bookmarkEnd'):
                key = node.get(tag('id'))
                if key not in active:
                    raise DocumentError('BOOKMARK_INVALID')
                attrs, values = active.pop(key)
                closed[key] = (attrs, digest(''.join(values).encode()))
            elif node.tag in {tag('t'), '{'+NS['m']+'}t'}:
                for _, values in active.values(): values.append(node.text or '')
            elif node.tag in {tag('tab'), tag('br'), tag('cr'), tag('drawing')}:
                token = '\x00' + (digest(repr(_object_signature(node)).encode()) if node.tag == tag('drawing') else node.tag) + '\x00'
                for _, values in active.values(): values.append(token)
    if active:
        raise DocumentError('BOOKMARK_INVALID')
    return closed
