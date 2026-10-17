"""Acceptance probes through the production formatter, with fixed evaluator roles.

Role labels are evaluator inputs, never inferred accuracy. The neutral input
retains scientific structures and emphasis, but not paragraph/run typography or
empty layout paragraphs. Original-media geometry is explicitly retained.
"""
import copy
from pathlib import Path
from . import typography019 as t, layout021
from .docx_engine import NS, DocumentError, load_package, parse_xml, xml_bytes, write_package, digest
from .structure017 import inventory, compile_document, suggest_roles


def neutralize(source, target):
    parts=load_package(source); root=parse_xml(parts['word/document.xml']); body=root.find('w:body',NS)
    resolver=t.Resolver(parts); mapping={}; next_index=0
    for index,node in enumerate(list(body)):
        if layout021.empty_paragraph(node):
            body.remove(node);continue
        mapping[index]=next_index;next_index+=1
        for p in node.iter(t.tag('p')):
            effective,_=resolver.resolve(p)
            pp=t.prop('pPr')
            for name in ('numPr','sectPr'):
                value=t.child(effective,name) if name=='numPr' else p.find('w:pPr/w:sectPr',NS)
                if value is not None:pp.append(copy.deepcopy(value))
            for r in p.findall('.//w:r',NS):
                _,rp=resolver.resolve(p,r);new=t.prop('rPr')
                for name in ('i','iCs','b','bCs','vertAlign','lang','rtl'):
                    value=t.child(rp,name)
                    if value is not None:new.append(copy.deepcopy(value))
                t._replace(r,'rPr',new)
            t._replace(p,'pPr',pp)
        if node.tag==t.tag('tbl'):
            # Keep table topology, lose widths/row heights/borders from reference.
            t._replace(node,'tblPr',t.prop('tblPr'))
            grid=node.find('w:tblGrid',NS)
            if grid is not None:
                for col in grid:col.set(t.tag('w'),str(9000//max(1,len(grid))))
            for row in node.findall('.//w:tr',NS):
                old=t.child(row,'trPr')
                if old is not None:row.remove(old)
            for cell in node.findall('.//w:tc',NS):
                old=t.child(cell,'tcPr');new=t.prop('tcPr')
                if old is not None:
                    for c in old:
                        if c.tag in {t.tag('gridSpan'),t.tag('vMerge')}:new.append(copy.deepcopy(c))
                t._replace(cell,'tcPr',new)
    parts['word/document.xml']=xml_bytes(root)
    pp=t.prop('pPr');pp.append(t.prop('spacing',after=0,line=240,lineRule='auto'))
    rp=t.prop('rPr');rp.append(t.prop('rFonts',ascii='Arial',hAnsi='Arial'));rp.append(t.prop('sz',val=22))
    t.apply_base(parts,{'pPr':t.stable_xml(pp),'rPr':t.stable_xml(rp)})
    write_package(target,parts)
    return mapping


def verify(source,spec,selected,folder,golden,compare,render):
    folder.mkdir(parents=True,exist_ok=False)
    inv=inventory(source); sample=next(s for s in spec['samples'] if s['sha256']==inv['source_sha256'])
    if any('range' in b for b in inv['blocks']):raise DocumentError('ROUNDTRIP_INLINE_BOUNDARY_REVIEW')
    profiles={role:spec['styles'][role][key] for role,key in selected.items()}
    observations={o['block_id']:o for o in sample['observations']}
    fallback,_=suggest_roles(inv['blocks']);rows=[]
    for mode in ('original','neutralized'):
        incoming=source
        if mode=='neutralized':
            incoming=folder/'neutralized.docx';mapping=neutralize(source,incoming)
        else:mapping={b['index']:b['index'] for b in inv['blocks']}
        new_blocks={b['index']:b['id'] for b in inventory(incoming)['blocks']}
        assignments={};contexts={}
        for b in inv['blocks']:
            if b['index'] not in mapping:continue
            bid=new_blocks.get(mapping[b['index']])
            if bid is None:raise DocumentError('ROUNDTRIP_BLOCK_MAPPING')
            obs=observations.get(b['id'])
            if obs:
                key=obs['role'];assignments[bid]=key.split('.')[0];contexts[bid]=key
            else:assignments[bid]=fallback[b['id']]
        out=folder/f'{mode}-formatted.docx'
        report=compile_document(incoming,out,assignments=assignments,contexts=contexts,styles=profiles,
                                required=spec.get('structure',{}).get('required',[]),approved=True,fonts_ok=True,
                                editorial_output=folder/f'{mode}-editorial.docx')
        pdf=render(out,folder/mode);pixels=compare(golden,pdf,folder/f'{mode}-diff')
        rows.append({'input':mode,'pixels':pixels,'source_sha256':digest(incoming.read_bytes()),
                     'output_sha256':digest(out.read_bytes()),'missing':report['missing'],
                     'formatter_status':report['status'],'representation_changes':report['representation_changes'],
                     'status':'passed' if pixels['pixel_exact'] and not report['missing'] and report['status']=='ready' else 'failed'})
    return {'strategy':'production_roundtrip','status':'passed' if all(r['status']=='passed' for r in rows) else 'failed',
            'roles':'fixed evaluator labels; not model predictions','neutralization':'paragraph/run typography, blank layout paragraphs and table geometry removed; scientific objects and emphasis retained',
            'rows':rows}
