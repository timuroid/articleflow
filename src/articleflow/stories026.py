"""Body and header/footer story inventory; stable IDs follow body then part name."""
from .docx_engine import NS,DocumentError,parse_xml


def roots(parts):
    document=parse_xml(parts['word/document.xml'])
    result=[('word/document.xml',document.find('w:body',NS))]
    for name in sorted(parts):
        if name.startswith(('word/header','word/footer')) and name.endswith('.xml'):
            root=parse_xml(parts[name])
            if root.tag.rsplit('}',1)[-1] not in {'hdr','ftr'}:raise DocumentError('STORY_ROOT_INVALID')
            if root.xpath('.//w:ins | .//w:del | .//w:txbxContent | .//w:altChunk | .//wp:anchor',namespaces=NS):raise DocumentError('STORY_CONSTRUCT_UNSUPPORTED')
            result.append((name,root))
    return result


def paragraphs(parts):
    return [p for _,root in roots(parts) for p in root.findall('.//w:p',NS)]


def binding_contract(parts):
    root=parse_xml(parts['word/document.xml'])
    rels=parse_xml(parts['word/_rels/document.xml.rels']) if 'word/_rels/document.xml.rels' in parts else []
    relevant={r.get('Id'):{'target':r.get('Target'),'type':r.get('Type')} for r in rels if r.get('Type','').endswith(('/header','/footer'))}
    # Resource identities are checked explicitly until remapping is implemented.
    return {'sections':len(root.findall('.//w:sectPr',NS)), 'relationships':relevant}
