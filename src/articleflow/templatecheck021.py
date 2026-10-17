"""Offline visual gate for extracted heading boundaries, with a negative control.

Raw reference OOXML is evaluator-only. Runtime receives portable profiles.
Exit 1 means a layout mismatch; exit 2 means the render gate could not run.
"""
import argparse
import copy
import json
from pathlib import Path
from docx import Document
import pymupdf
from articleflow.docx_engine import load_package,parse_xml,xml_bytes,write_package,NS
from articleflow import typography019 as t,layout021
from articleflow.structure017 import inventory
from articleflow.research import render_pdf,compare_pixels


def text_paragraph(text):
    p=t.prop('p');pp=t.prop('pPr');pp.append(t.prop('spacing',after=0,line=240,lineRule='auto'));p.append(pp)
    r=t.prop('r');rp=t.prop('rPr');rp.append(t.prop('rFonts',ascii='Times New Roman',hAnsi='Times New Roman'));rp.append(t.prop('sz',val=24));r.append(rp);txt=t.prop('t');txt.text=text;r.append(txt);p.append(r);return p


def gap(pdf):
    with pymupdf.open(pdf) as doc:
        a=doc[0].search_for('Предыдущий блок')[0]; b=doc[0].search_for('Контрольный заголовок')[0]
        return round(b.y0-a.y1,4)


def verify(reference, spec, profiles, folder):
    folder.mkdir(parents=True,exist_ok=False)
    parts=load_package(reference);root=parse_xml(parts['word/document.xml']);body=root.find('w:body',NS)
    sample=next(s for s in spec['samples'] if s['sha256']==inventory(reference)['source_sha256'])
    rows=[]
    for key,profile in profiles.items():
        if not key.startswith('body.heading.') or 'leading_spacing' not in profile:continue
        import hashlib
        sk=hashlib.sha256(json.dumps(profile,sort_keys=True).encode()).hexdigest()[:16]
        obs=next((o for o in sample['observations'] if o['role']==key and o['style_key']==sk),None)
        if obs is None:continue
        block=next(b for b in inventory(reference)['blocks'] if b['id']==obs['block_id']);i=block['index']
        expected_heading=copy.deepcopy(body[i]); first=expected_heading.find('w:r/w:rPr',NS)
        for c in list(expected_heading):
            if c.tag!=t.tag('pPr'):expected_heading.remove(c)
        r=t.prop('r')
        if first is not None:r.append(copy.deepcopy(first))
        txt=t.prop('t');txt.text='Контрольный заголовок';r.append(txt);expected_heading.append(r)
        j=i
        while j>0 and layout021.empty_paragraph(body[j-1]):j-=1
        blanks=[copy.deepcopy(n) for n in body[j:i]]
        paths={}
        for variant in ('reference','candidate','without-boundary-control'):
            out=folder/f'{key}-{variant}.docx'
            if variant=='reference':
                package=dict(parts);heading=copy.deepcopy(expected_heading);before=blanks
            else:
                doc=Document();doc.save(out);package=load_package(out);resolver=t.Resolver(package)
                heading=text_paragraph('Контрольный заголовок');t.apply(heading,profile,resolver,key)
                before=[layout021.spacing_node(p,resolver) for p in profile['leading_spacing']] if variant=='candidate' else []
                t.apply_base(package,profiles['__base__'])
            docroot=parse_xml(package['word/document.xml']);b=docroot.find('w:body',NS)
            section=t.prop('sectPr');t.apply_section(section,profiles['__document__'])
            b[:]=[text_paragraph('Предыдущий блок'),*copy.deepcopy(before),heading,text_paragraph('Следующий блок'),section]
            package['word/document.xml']=xml_bytes(docroot);write_package(out,package)
            paths[variant]=render_pdf(out,folder/f'{key}-{variant}')
        expected_gap=gap(paths['reference']);actual_gap=gap(paths['candidate']);negative_gap=gap(paths['without-boundary-control'])
        pixels=compare_pixels(paths['reference'],paths['candidate'])
        rows.append({'context':key,'reference_gap_pt':expected_gap,'candidate_gap_pt':actual_gap,'negative_control_gap_pt':negative_gap,
                     'gap_pass':abs(expected_gap-actual_gap)<=0.05,'negative_control_detected':abs(expected_gap-negative_gap)>0.05 if blanks else None,'pixels':pixels})
    result={'status':('passed' if all(r['gap_pass'] and r['pixels']['pixel_exact'] for r in rows) else 'failed') if rows else 'not_applicable','scope':'synthetic heading-boundary probes; not full document fidelity','model_calls':0,'rows':rows}
    (folder/'result.json').write_text(json.dumps(result,indent=2));return result

def verify_table_boundaries(reference,spec,profiles,folder):
    """Isolate the table-to-body gap; raw source is evaluator evidence only."""
    import hashlib
    parts=load_package(reference);body=parse_xml(parts['word/document.xml']).find('w:body',NS)
    inv=inventory(reference);sample=next(s for s in spec['samples'] if s['sha256']==inv['source_sha256']);rows=[]
    for key,profile in profiles.items():
        if 'trailing_spacing' not in profile:continue
        sk=hashlib.sha256(json.dumps(profile,sort_keys=True).encode()).hexdigest()[:16]
        obs=next((o for o in sample['observations'] if o['role']==key and o['style_key']==sk),None)
        if obs is None:continue
        block=next(b for b in inv['blocks'] if b['id']==obs['block_id']);i=block['index'];end=i+1
        while end<len(body) and layout021.empty_paragraph(body[end]):end+=1
        table=copy.deepcopy(body[i])
        for n,p in enumerate(table.findall('.//w:p',NS)):
            first=p.find('w:r/w:rPr',NS);first=copy.deepcopy(first)
            for c in list(p):
                if c.tag!=t.tag('pPr'):p.remove(c)
            r=t.prop('r')
            if first is not None:r.append(first)
            txt=t.prop('t');txt.text=f'Cell {n+1}';r.append(txt);p.append(r)
        paths={}
        for variant in ('reference','candidate','without-boundary-control'):
            package=dict(parts);root=parse_xml(package['word/document.xml']);b=root.find('w:body',NS)
            resolver=t.Resolver(package)
            blanks=[copy.deepcopy(n) for n in body[i+1:end]] if variant=='reference' else [layout021.spacing_node(p,resolver) for p in profile['trailing_spacing']] if variant=='candidate' else []
            section=t.prop('sectPr');t.apply_section(section,profiles['__document__'])
            b[:]=[copy.deepcopy(table),*blanks,text_paragraph('After table'),section]
            package['word/document.xml']=xml_bytes(root)
            out=folder/f'table-{key}-{variant}.docx';write_package(out,package)
            paths[variant]=render_pdf(out,folder/f'table-{key}-{variant}')
        def table_gap(path):
            with pymupdf.open(path) as pdf:
                last=pdf[0].search_for(f'Cell {len(table.findall(".//w:p",NS))}')[0]
                after=pdf[0].search_for('After table')[0]
                return round(after.y0-last.y1,4)
        expected,actual,negative=[table_gap(paths[v]) for v in ('reference','candidate','without-boundary-control')]
        rows.append({'context':key,'boundary':'after_table','reference_gap_pt':expected,'candidate_gap_pt':actual,'negative_control_gap_pt':negative,
                     'gap_pass':abs(expected-actual)<=0.05,'negative_control_detected':abs(expected-negative)>0.05 if end>i+1 else None,
                     'pixels':compare_pixels(paths['reference'],paths['candidate'])})
    return rows

def main():
    p=argparse.ArgumentParser()
    for key in ('reference','spec','profile','output'):p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args()
    try:result=verify(a.reference,json.loads(a.spec.read_text()),json.loads(a.profile.read_text()),a.output)
    except Exception as exc:
        print(json.dumps({'status':'unavailable','error_type':type(exc).__name__}));raise SystemExit(2)
    print(json.dumps(result));raise SystemExit(0 if result['status']=='passed' else 1)


def validate_samples(paths, spec, profiles, folder):
    needed={k for k,p in profiles.items() if (k.startswith('body.heading.') and p.get('leading_spacing')) or p.get('trailing_spacing')}
    if not needed:return {'status':'not_applicable','scope':'heading-boundary probes','rows':[]}
    rows=[]
    for i,path in enumerate(paths):
        check=verify(path,spec,profiles,folder/str(i));rows.extend(check['rows'])
        rows.extend(verify_table_boundaries(path,spec,profiles,folder/str(i)))
    covered={row['context'] for row in rows}
    passed=needed<=covered and all(row['gap_pass'] and row['pixels']['pixel_exact'] and row['negative_control_detected'] is not False for row in rows)
    return {'status':'passed' if passed else 'failed','scope':'heading/table boundary probes; not full document fidelity','rows':rows,'model_calls':0}
