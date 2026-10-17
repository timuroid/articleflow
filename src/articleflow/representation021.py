"""Audited presentation changes: native bibliography labels and keyword layout.

No citation text, ordinal or keyword is generated. Complex cases remain draft.
"""
import copy
import re
from lxml import etree as ET
from .docx_engine import NS, W, DocumentError, paragraph_text, parse_xml, xml_bytes
from . import typography019 as t, fragments019

KEYWORD_LABEL = re.compile(r'^\s*(?:ключевые\s+слова|keywords)\b\s*[:：—-]?\s*', re.I)
CITATION = re.compile(r'^(\d{1,6})\.([ \t]+)')


def plain(node):
    return node.tag == t.tag('p') and all(c.tag in {t.tag('pPr'), t.tag('r')} for c in node) and all(c.tag in {t.tag('rPr'), t.tag('t')} for r in node.findall('w:r', NS) for c in r)


def has_value(role, text):
    text = text.strip()
    return bool(KEYWORD_LABEL.sub('', text).strip()) if role == 'keywords' else bool(text)


def numbering_spec(resolver, ppr):
    """Portable level, without source IDs, starts or article text."""
    num = t.child(ppr, 'numPr')
    if num is None or t.value(num, 'numId') == '0':
        return None
    level = resolver.numbering_level(ppr)
    if level is None:
        return {'review': 'NUMBERING_DEFINITION_MISSING'}
    ilvl = t.value(num, 'ilvl', '0')
    allowed = {'start', 'numFmt', 'lvlText', 'lvlJc', 'suff', 'pPr', 'rPr', 'lvlRestart'}
    if (ilvl != '0' or t.value(level, 'numFmt') != 'decimal' or t.value(level, 'lvlText') != '%1.'
            or any(ET.QName(c).localname not in allowed for c in level)
            or level.attrib.get(t.tag('tentative')) is not None):
        return {'review': 'NUMBERING_PROFILE_UNSUPPORTED'}
    out = t.prop('lvl', ilvl='0')
    for name in ('numFmt', 'lvlText', 'suff', 'lvlJc', 'pPr', 'rPr'):
        n = t.child(level, name)
        if n is not None: out.append(copy.deepcopy(n))
    if out.xpath('.//w:pStyle | .//w:rStyle | .//w:numPr | .//w:sectPr', namespaces=NS):
        return {'review': 'NUMBERING_STYLE_LINK_REVIEW'}
    return {'schema': 'numbering-021', 'level': t.stable_xml(out)}


def source_ordinals(body, resolver):
    """Only unambiguous single-level decimal source counters are supported."""
    counts = {}; out = {}; rows = []; blocked = set()
    for p in body.iter(t.tag('p')):
        pp, _ = resolver.resolve(p); num = t.child(pp, 'numPr')
        if num is None or t.value(num, 'numId') == '0': continue
        spec = numbering_spec(resolver, pp); nid = t.value(num, 'numId')
        if not spec or 'review' in spec: blocked.add(nid)
        rows.append((p, pp, nid))
    for p, pp, nid in rows:
        if nid in blocked: continue
        level = resolver.numbering_level(pp)
        try: start = int(t.value(level, 'start', '1'))
        except ValueError: raise DocumentError('NUMBERING_START_INVALID')
        counts[nid] = counts.get(nid, start - 1) + 1
        if p.getparent() is body: out[body.index(p)] = counts[nid]
    return out


class NumberingWriter:
    def __init__(self, parts):
        self.parts = parts
        self.root = parse_xml(parts.get('word/numbering.xml', f'<w:numbering xmlns:w="{W}"/>'.encode()))
        self.abstracts = {}
        self.changed = False

    def bind(self, paragraph, spec, ordinal):
        if spec.get('schema') != 'numbering-021' or not 0 <= ordinal <= 999999:
            raise DocumentError('NUMBERING_PROFILE_INVALID')
        level = parse_xml(spec['level'].encode())
        if level.tag != t.tag('lvl') or t.value(level, 'numFmt') != 'decimal' or t.value(level, 'lvlText') != '%1.':
            raise DocumentError('NUMBERING_PROFILE_INVALID')
        if spec.get('rPr'):
            t._replace(level, 'rPr', parse_xml(spec['rPr'].encode()))
        key = t.stable_xml(level)
        if key not in self.abstracts:
            aid = 1 + max((int(n.get(t.tag('abstractNumId'))) for n in self.root.findall('w:abstractNum', NS)), default=-1)
            abstract = t.prop('abstractNum', abstractNumId=aid)
            abstract.append(t.prop('multiLevelType', val='singleLevel'))
            level.insert(0, t.prop('start', val=1)); abstract.append(parse_xml(t.stable_xml(level).encode()))
            # abstractNum must precede num in the numbering part.
            first_num = next((i for i,n in enumerate(self.root) if n.tag == t.tag('num')), len(self.root))
            self.root.insert(first_num, abstract); self.abstracts[key] = aid
        nid = 1 + max((int(n.get(t.tag('numId'))) for n in self.root.findall('w:num', NS)), default=0)
        number = t.prop('num', numId=nid); number.append(t.prop('abstractNumId', val=self.abstracts[key]))
        override = t.prop('lvlOverride', ilvl=0); override.append(t.prop('startOverride', val=ordinal)); number.append(override); self.root.append(number)
        pp = t.child(paragraph, 'pPr')
        if pp is None: pp = t.prop('pPr'); paragraph.insert(0, pp)
        old = t.child(pp, 'numPr')
        if old is not None: pp.remove(old)
        binding = t.prop('numPr'); binding.append(t.prop('ilvl', val=0)); binding.append(t.prop('numId', val=nid)); pp.append(binding)
        t._replace(paragraph, 'pPr', parse_xml(t.stable_xml(pp).encode()))
        self.changed = True

    def save(self):
        if not self.changed: return
        self.parts['word/numbering.xml'] = xml_bytes(self.root)
        relns = 'http://schemas.openxmlformats.org/package/2006/relationships'
        rels = parse_xml(self.parts['word/_rels/document.xml.rels'])
        typ = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering'
        if not any(n.get('Type') == typ for n in rels):
            ids = {n.get('Id') for n in rels}; i = 1
            while f'rId{i}' in ids: i += 1
            ET.SubElement(rels, f'{{{relns}}}Relationship', Id=f'rId{i}', Type=typ, Target='numbering.xml')
            self.parts['word/_rels/document.xml.rels'] = xml_bytes(rels)
        ct = parse_xml(self.parts['[Content_Types].xml'])
        if not any(n.get('PartName') == '/word/numbering.xml' for n in ct):
            ET.SubElement(ct, '{http://schemas.openxmlformats.org/package/2006/content-types}Override', PartName='/word/numbering.xml', ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml')
            self.parts['[Content_Types].xml'] = xml_bytes(ct)


def bibliography(node, style, ordinal, writer):
    spec = style.get('numbering')
    if not spec: return [node], None, 'Библиография: профиль не содержит проверенного правила нумерации'
    if 'review' in spec: return [node], None, spec['review']
    text = paragraph_text(node); match = CITATION.match(text)
    if ordinal is None and node.find('w:pPr/w:numPr', NS) is not None:
        return [node], None, 'Библиография: исходная нумерация требует проверки'
    if ordinal is not None:
        # A literal label plus native numbering is ambiguous, never double-number it.
        if match: return [node], None, 'Библиография: одновременно текстовый номер и нумерация Word'
        out = copy.deepcopy(node); prefix = ''
    elif match and plain(node):
        prefix = match.group(); ordinal = int(match.group(1))
        if str(ordinal) != match.group(1): return [node], None, 'Библиография: номер с ведущими нулями требует проверки'
        if match.end() == len(text): return [node], None, 'Библиография: пустая запись'
        out = fragments019.fragment(node, match.end(), len(text))
    else:
        return [node], None, 'Библиография: номер или сложный фрагмент требует проверки'
    writer.bind(out, spec, ordinal)
    # Reconstruct the exact source representation before accepting the change.
    restored = copy.deepcopy(out); pp = t.child(restored, 'pPr'); newnum = t.child(pp, 'numPr'); pp.remove(newnum)
    oldnum = node.find('w:pPr/w:numPr', NS)
    if oldnum is not None: pp.append(copy.deepcopy(oldnum))
    if prefix:
        r = t.prop('r'); txt = t.prop('t'); txt.text = prefix; r.append(txt); restored.insert(1, r)
    if t.scientific_signature([node]) != t.scientific_signature([restored]):
        raise DocumentError('NUMBERING_CONTENT_INTEGRITY')
    return [out], {'kind': 'native_bibliography', 'ordinal': ordinal, 'source_prefix': prefix, 'text_preserved': True}, None


def keywords(node, styles, resolver):
    text = paragraph_text(node); match = KEYWORD_LABEL.match(text)
    if not match or not text[match.end():].strip() or 'keywords.heading' not in styles:
        return [node], None, None
    if not plain(node): return [node], None, 'Ключевые слова: сложный inline-блок не разделён; требуется проверка'
    left = fragments019.fragment(node, 0, match.end()); right = fragments019.fragment(node, match.end(), len(text))
    if paragraph_text(left) + paragraph_text(right) != text: raise DocumentError('KEYWORDS_CONTENT_INTEGRITY')
    # No fields/links/bookmarks are allowed here; fragments preserve each text range.
    t.apply(left, styles['keywords.heading'], resolver, 'keywords.heading')
    t.apply(right, styles['keywords'], resolver, 'keywords')
    return [left, right], {'kind': 'split_keyword_label', 'boundary': match.end(), 'text_preserved': True}, None
