"""Evaluate a replay against source bytes and reference OOXML (not its profile).

This evaluator is not runtime template input. No model calls or text in stdout.
"""
import argparse
import copy
import json
from collections import Counter
from pathlib import Path
from articleflow.docx_engine import load_package, parse_xml, NS, paragraph_text, digest
from articleflow import typography019 as t, representation021 as rep, layout021
from articleflow.structure017 import inventory


def audit(reference, source, candidate):
    ref=load_package(reference); src=load_package(source); dst=load_package(candidate)
    rb=parse_xml(ref['word/document.xml']).find('w:body',NS); sb=parse_xml(src['word/document.xml']).find('w:body',NS); db=parse_xml(dst['word/document.xml']).find('w:body',NS)
    ref_blocks=inventory(reference)['blocks']; refp=next(rb[b['index']] for b in ref_blocks if b['format_hints'].get('bibliography') and b['text'].strip())
    def geometry(p,parts):
        # Raw reference level properties + direct overrides; no extracted profile.
        pp=p.find('w:pPr',NS); num=pp.find('w:numPr',NS) if pp is not None else None; level=None
        if num is not None:
            nr=parse_xml(parts['word/numbering.xml']); nid=t.value(num,'numId'); ilvl=t.value(num,'ilvl','0'); inst=nr.find(f'w:num[@w:numId="{nid}"]',NS)
            aid=t.value(inst,'abstractNumId');level=nr.find(f'w:abstractNum[@w:abstractNumId="{aid}"]/w:lvl[@w:ilvl="{ilvl}"]',NS)
        props={}
        for holder in [t.child(level,'pPr'),pp]:
            for name in ('ind','tabs'):
                n=t.child(holder,name)
                if n is not None:
                    if name=='ind':props.setdefault(name,{}).update({t.ET.QName(k).localname:v for k,v in n.attrib.items()})
                    else:props[name]=t.stable_xml(n)
        return {'numFmt':t.value(level,'numFmt'),'label':t.value(level,'lvlText'),'suffix':t.value(level,'suff','tab') if level is not None else None,'alignment':t.value(level,'lvlJc','left') if level is not None else None,**props}
    expected=geometry(refp,ref); refs=[db[b['index']] for b in inventory(candidate)['blocks'] if b['format_hints'].get('bibliography') and b['text'].strip()]
    source_refs=[sb[b['index']] for b in inventory(source)['blocks'] if b['format_hints'].get('bibliography') and b['text'].strip()]
    expected_ordinals=[int(rep.CITATION.match(paragraph_text(p)).group(1)) for p in source_refs]
    actual_ordinals=rep.source_ordinals(db,t.Resolver(dst))
    candidate_ordinals=[actual_ordinals.get(db.index(p)) for p in refs]
    restored=[]; i=0; all_nodes=list(db)
    while i<len(all_nodes):
        p=all_nodes[i]; i+=1
        if p.tag==t.tag('sectPr'):continue
        if layout021.empty_paragraph(p) and not any(layout021.empty_paragraph(n) for n in sb):continue
        text=paragraph_text(p)
        if text.startswith('[ЗАПОЛНИТЬ:') or text=='[Укажите авторов статьи]':continue
        n=copy.deepcopy(p)
        if p in refs and db.index(p) in actual_ordinals:
            pp=t.child(n,'pPr');pp.remove(t.child(pp,'numPr'));r=t.prop('r');txt=t.prop('t');txt.text=f'{actual_ordinals[db.index(p)]}. ';r.append(txt);n.insert(1,r)
        if rep.KEYWORD_LABEL.match(text) and not rep.has_value('keywords',text) and i<len(all_nodes):
            nxt=all_nodes[i]
            # This evaluator expects the known inline-source replay, not arbitrary input.
            if any(rep.KEYWORD_LABEL.match(paragraph_text(s)) and rep.has_value('keywords',paragraph_text(s)) for s in sb if s.tag==t.tag('p')):
                for c in nxt:
                    if c.tag!=t.tag('pPr'):n.append(copy.deepcopy(c))
                i+=1
        restored.append(n)
    before=[n for n in sb if n.tag!=t.tag('sectPr')]
    scientific_exact=t.scientific_signature(before)==t.scientific_signature(restored)
    headings=[p for p in db if p.tag==t.tag('p') and rep.KEYWORD_LABEL.match(paragraph_text(p)) and not rep.has_value('keywords',paragraph_text(p))]
    media=[k for k in src if k.startswith('word/media/')]
    return {'source_sha256':digest(source.read_bytes()),'candidate_sha256':digest(candidate.read_bytes()),'reference_sha256':digest(reference.read_bytes()),
            'bibliography_entries':len(refs),'bibliography_geometry_matching':sum(geometry(p,dst)==expected for p in refs),'bibliography_ordinals_exact':candidate_ordinals==expected_ordinals,'native_numbering':sum(x is not None for x in candidate_ordinals),
            'heading_layout_spacers':sum(layout021.empty_paragraph(n) for n in db),'keyword_separate_headings':len(headings),'scientific_payload_exact_after_declared_representation_reversal':scientific_exact,'media_identical':all(src[k]==dst.get(k) for k in media),'media_count':len(media),
            'tables':len(db.findall('w:tbl',NS)),'drawings':len(db.findall('.//w:drawing',NS)), 'page_geometry_exact':t.section_profile(db.find('w:sectPr',NS))==t.section_profile(rb.find('w:sectPr',NS))}

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('reference','source','candidate','out'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();result=audit(a.reference,a.source,a.candidate);a.out.write_text(json.dumps(result,indent=2));print(json.dumps(result))
