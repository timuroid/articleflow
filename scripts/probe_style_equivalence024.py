"""Controlled visual alias experiment; never modifies production template rules.

Uses evaluator-only source assignments. Passing a probe establishes equivalence
on the supplied document, NOT general equivalence or unseen transfer. The full
source catalogue remains intact. No provider calls; keep private inputs/results
out of public Git.
"""
import argparse
import copy
import json
from pathlib import Path
from articleflow.agent023 import extract_input,build_package,relabel
from articleflow.rules023 import semantic_spans,features
from articleflow.catalogue import render_catalogue
from articleflow.docx_engine import digest,dump
from articleflow.integrity023 import check
from articleflow.research import render_pdf,compare_pixels


def compare_bounded(reference,candidate):
    import pymupdf
    with pymupdf.open(reference) as a,pymupdf.open(candidate) as b:
        if max(len(a),len(b))>100:raise ValueError('Visual probe limit: 100 pages')
    return compare_pixels(reference,candidate)


def substitute(plan,content,semantics,condition,kind,style):
    result=copy.deepcopy(plan)
    f=features(content,{b['id']:b['role'] for b in plan['blocks']})['paragraph']
    changed=0
    for block in result['blocks']:
        pf=f[block['id']]
        if kind=='paragraph':
            if all(pf.get(k)==v for k,v in condition.items()):
                changed+=block['paragraph_style']!=style;block['paragraph_style']=style
        elif kind=='character':
            spans=[]
            for original in block['spans']:
                for semantic in semantics[block['id']]:
                    a=max(original['start'],semantic['start']);z=min(original['end'],semantic['end'])
                    if a>=z:continue
                    sf={**pf,'script':pf['language'],**semantic['features']}
                    target=style if all(sf.get(k)==v for k,v in condition.items()) else original['style']
                    changed+=target!=original['style']
                    if spans and spans[-1]['end']==a and spans[-1]['style']==target:spans[-1]['end']=z
                    else:spans.append({'start':a,'end':z,'style':target})
            block['spans']=spans
        else:raise ValueError('Unsupported probe kind')
    return result,changed


def run(source,annotation,output,limit,all_variants=False):
    output.mkdir(parents=True,exist_ok=False)
    content=extract_input(source,output/'extracted');semantics=semantic_spans(source)
    data=json.loads(annotation.read_text());assignments=data['assignments'];definitions=data['definitions']
    if set(assignments)!={b['id'] for b in content['blocks']}:raise ValueError('Annotation coverage mismatch')
    _,conflicts=build_package([{'content':content,'extracted':output/'extracted','semantics':semantics}],
                              [assignments],definitions,output/'template')
    _,base=relabel(output/'extracted',assignments,definitions)
    base.update(template_sha256=digest((output/'template/rules.json').read_bytes()),
                input_sha256=digest((output/'extracted/content/content.json').read_bytes()))
    golden=render_pdf(source,output/'golden')
    report={'schema':'visual-alias-probe-024','api_attempts':0,'mode':'evaluator_oracle_not_runtime',
            'general_equivalence_proven':False,'production_rules_modified':False,'cases':[]}
    combined=copy.deepcopy(base)
    for index,conflict in enumerate(conflicts):
        if conflict['kind'] not in {'paragraph','character'}:continue
        if len(report['cases'])>=limit:break
        candidates=sorted({e['set']['style'] for e in conflict['examples']})
        if not all_variants:candidates=candidates[:1]
        for variant,canonical in enumerate(candidates):
            if len(report['cases'])>=limit:break
            candidate,changed=substitute(base,content,semantics,conflict['when'],conflict['kind'],canonical)
            folder=output/f'case-{index}-{variant}';folder.mkdir();dump(folder/'plan.json',candidate)
            docx=folder/'candidate.docx';render_catalogue(output/'template',output/'extracted/content',candidate,docx)
            integrity=check(source,docx);pixels=compare_bounded(golden,render_pdf(docx,folder/'render'))
            exact=bool(changed) and all(integrity.values()) and pixels['pixel_exact']
            row={'group':index,'variant':variant,'kind':conflict['kind'],'changed_assignments':changed,'pixel_exact':pixels['pixel_exact'],
                 'differing_pixel_ratio':pixels['differing_pixel_ratio'],'content_checks':integrity,
                 'accepted_for_combination_probe':exact,'canonical_style':canonical}
            report['cases'].append(row);dump(output/'summary.json',report)
            if exact:combined,_=substitute(combined,content,semantics,conflict['when'],conflict['kind'],canonical)
            print(json.dumps({k:row[k] for k in ['group','kind','pixel_exact','changed_assignments']}),flush=True)
            if exact:break
    folder=output/'combined';folder.mkdir();dump(folder/'plan.json',combined)
    docx=folder/'candidate.docx';render_catalogue(output/'template',output/'extracted/content',combined,docx)
    report['combined']={'integrity':check(source,docx),'pixels':compare_bounded(golden,render_pdf(docx,folder/'render'))}
    dump(output/'summary.json',report)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True,type=Path)
    p.add_argument('--annotations',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--limit',type=int,default=50);p.add_argument('--all-variants',action='store_true');args=p.parse_args()
    if not 1<=args.limit<=100:p.error('limit must be 1..100')
    run(args.source,args.annotations,args.output,args.limit,args.all_variants)
