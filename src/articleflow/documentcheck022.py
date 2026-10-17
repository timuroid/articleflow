"""All-page physical checks on a new manuscript; never pixel-compare different text."""
from __future__ import annotations

import copy
import re
from pathlib import Path
import pymupdf
from .docx_engine import NS, load_package,parse_xml,xml_bytes,write_package,digest,dump,paragraph_text
from . import typography019 as t
from .research import render_pdf

HEADING = re.compile(r'^(?:введение|заключение|выводы|список литературы|references|introduction|conclusions?)$',re.I)
CAPTION = re.compile(r'^(?:таблица|table|рис(?:унок)?\.?|fig(?:ure)?\.?)\s*\d',re.I)


def audit_pdf(pdf, source=None):
    issues=[];pages=[];page_texts=[]
    with pymupdf.open(pdf) as document:
        if len(document)>100: raise ValueError('VISUAL_PAGE_LIMIT')
        for i,page in enumerate(document):
            page_texts.append(re.sub(r'\s+', '', page.get_text()).casefold())
            rect=page.rect;lines=[];images=[];fonts=set()
            for block in page.get_text('dict')['blocks']:
                if block['type']==1:
                    images.append(pymupdf.Rect(block['bbox']));continue
                for line in block['lines']:
                    spans=[s for s in line['spans'] if s['text'].strip()]
                    if not spans:continue
                    box=pymupdf.Rect(line['bbox']);text=''.join(s['text'] for s in spans)
                    lines.append((box,text,spans));fonts.update(s['font'] for s in spans)
                    if box.x0 < -1 or box.y0 < -1 or box.x1 > rect.width+1 or box.y1 > rect.height+1:
                        issues.append({'code':'TEXT_OUTSIDE_PAGE','page':i+1,'bbox':list(box)})
                    if any('\ufffd' in s['text'] or '\x00' in s['text'] for s in spans):
                        issues.append({'code':'MISSING_GLYPH','page':i+1,'bbox':list(box)})
            for box in images:
                if box.x0 < -1 or box.y0 < -1 or box.x1 > rect.width+1 or box.y1 > rect.height+1:
                    issues.append({'code':'IMAGE_OUTSIDE_PAGE','page':i+1,'bbox':list(box)})
            # Large overlap between independent lines is suspicious. Sup/subscripts
            # and glyph boxes from the same baseline are intentionally excluded.
            for n,(a,_,sa) in enumerate(lines):
                for b,_,sb in lines[n+1:]:
                    if abs(sa[0]['origin'][1]-sb[0]['origin'][1])<2:continue
                    overlap=a & b
                    if not overlap.is_empty and overlap.width>12 and overlap.height>min(a.height,b.height)*.65:
                        issues.append({'code':'TEXT_OVERLAP_REVIEW','page':i+1,'bbox':list(overlap)})
            # Caption / heading at the very end of a page without following text/object.
            candidates=sorted([(b.y0,b.y1,txt,b) for b,txt,_ in lines],key=lambda x:x[0])
            if candidates:
                last=candidates[-1]
                if (HEADING.fullmatch(last[2].strip()) or CAPTION.match(last[2].strip())) and not any(b.y0>=last[1]-1 for b in images):
                    issues.append({'code':'ORPHAN_LABEL','page':i+1,'bbox':list(last[3]),'text_sha256':digest(re.sub(r'\s+','',last[2]).casefold().encode())})
            if not lines and not images:
                issues.append({'code':'EMPTY_PAGE_REVIEW','page':i+1})
            pages.append({'page':i+1,'width_pt':rect.width,'height_pt':rect.height,
                          'text_lines':len(lines),'images':len(images),'fonts':sorted(fonts)})
    result={'schema':'document-visual-022','status':'passed' if not issues else 'needs_review',
            'scope':'all-page physical checks; not semantic template conformance',
            'pages':pages,'issues':issues,'pdf_sha256':digest(Path(pdf).read_bytes()),
            'not_checked':['journal-specific semantics','Microsoft Word pagination','arbitrary overlapping vector graphics']}
    if source:
        parts=load_package(source);root=parse_xml(parts['word/document.xml'])
        result['table_checks']=[]
        for index,table in enumerate(root.findall('.//w:tbl',NS)):
            rows=table.findall('w:tr',NS)
            texts=[''.join(paragraph_text(p) for p in cell.findall('.//w:p',NS)) for cell in table.findall('.//w:tc',NS)]
            locations=set()
            for text in texts:
                normalized=re.sub(r'\s+','',text).casefold()
                if len(normalized)<10:continue
                found=[i+1 for i,p in enumerate(page_texts) if normalized in p]
                if len(found)==1:locations.add(found[0])
            small=len(rows)<=6 and sum(map(len,texts))<1500
            result['table_checks'].append({'table_index':index,'located_pages':sorted(locations),'short_table':small})
            if small and len(locations)>1:
                issues.append({'code':'SMALL_TABLE_SPLIT','page':min(locations),'table_index':index,'pages':sorted(locations)})
        result['status']='passed' if not issues else 'needs_review'
        result['objects']={'tables':len(root.findall('.//w:tbl',NS)),
                           'drawings':len(root.findall('.//w:drawing',NS)),
                           'math':len(root.findall('.//m:oMath',NS))}
    return result


def repair_keep_links(source, target, report):
    """Only page-boundary labels identified by the evaluator are eligible.

    Never rewrite text, reduce fonts, move objects or remove scientific payload.
    """
    if not any(i['code'] in {'ORPHAN_LABEL','SMALL_TABLE_SPLIT'} for i in report['issues']):return []
    parts=load_package(source);root=parse_xml(parts['word/document.xml']);body=root.find('w:body',NS)
    changes=[]
    for index,p in enumerate(body):
        if p.tag!=t.tag('p'):continue
        text=paragraph_text(p).strip()
        if not HEADING.fullmatch(text) and not CAPTION.match(text):continue
        if digest(re.sub(r'\s+','',text).casefold().encode()) not in {i.get('text_sha256') for i in report['issues'] if i['code']=='ORPHAN_LABEL'}:continue
        pp=t.child(p,'pPr')
        if pp is None:pp=t.prop('pPr');p.insert(0,pp)
        if t.value(pp,'keepNext') in {None,'0','false','off'}:
            t._replace(pp,'keepNext',t.prop('keepNext'));changes.append({'block_index':index,'property':'keepNext'})
    tables=root.findall('.//w:tbl',NS)
    for issue in report['issues']:
        if issue['code']!='SMALL_TABLE_SPLIT':continue
        table=tables[issue['table_index']];paragraphs=table.findall('.//w:p',NS)
        for paragraph in paragraphs[:-1]:
            pp=t.child(paragraph,'pPr')
            if pp is None:pp=t.prop('pPr');paragraph.insert(0,pp)
            t._replace(pp,'keepNext',t.prop('keepNext'))
        previous=table.getprevious()
        if previous is not None and previous.tag==t.tag('p') and CAPTION.match(paragraph_text(previous).strip()):
            pp=t.child(previous,'pPr')
            if pp is None:pp=t.prop('pPr');previous.insert(0,pp)
            t._replace(pp,'keepNext',t.prop('keepNext'))
        changes.append({'table_index':issue['table_index'],'property':'keep_short_table_together'})
    if not changes:return []
    before=parse_xml(parts['word/document.xml']).find('w:body',NS)
    if t.scientific_signature(list(before))!=t.scientific_signature(list(body)):
        raise ValueError('VISUAL_REPAIR_CONTENT_CHANGED')
    parts['word/document.xml']=xml_bytes(root);write_package(target,parts);return changes


def check(source, folder, repair=False):
    folder.mkdir(parents=True,exist_ok=False)
    pdf=render_pdf(source,folder/'initial');first=audit_pdf(pdf,source)
    result={'schema':'document-loop-022','attempts':[first],'repairs':[], 'status':first['status']}
    final_pdf=pdf
    if repair and first['status']!='passed':
        candidate=folder/'repair.docx';changes=repair_keep_links(source,candidate,first)
        if changes:
            candidate_pdf=render_pdf(candidate,folder/'repair');second=audit_pdf(candidate_pdf,candidate)
            result['attempts'].append(second)
            # No change is accepted if the total issue count has not improved.
            if len(second['issues'])<len(first['issues']) and {i['code'] for i in second['issues']} <= {i['code'] for i in first['issues']}:
                source.write_bytes(candidate.read_bytes());final_pdf=candidate_pdf
                result.update(status=second['status'],repairs=changes)
    result['final']=result['attempts'][-1] if result['repairs'] else first
    result['output_sha256']=digest(source.read_bytes())
    (folder/'preview.pdf').write_bytes(final_pdf.read_bytes())
    dump(folder/'result.json',result);return result
