"""Offline recovery checks, explicit private reference and optional 200-file load."""
import argparse
import copy
import itertools
import json
from pathlib import Path
import benchmark_web017 as base
from articleflow.docx_engine import parse_xml, xml_bytes, NS, write_package, paragraph_text
from articleflow.structure017 import compile_document, inventory
from articleflow.research import render_pdf, compare_pixels, raster_hashes
from articleflow.fonts019 import audit
from articleflow.typography019 import scientific_signature


def run(output, reference=None, http=False):
    output.mkdir(parents=True,exist_ok=False);result={'fonts':audit(),'permutations':[]}
    source=base.CORPUS/'inputs/north-03.docx';parts=base.load_package(source)
    root=parse_xml(parts['word/document.xml']);body=root.find('w:body',NS)
    nodes=list(body);abstract=nodes[4:8]
    for i,order in enumerate(itertools.permutations(range(4))):
        tree=copy.deepcopy(root);b=tree.find('w:body',NS)
        b[:]=copy.deepcopy(nodes[:4]+[abstract[j] for j in order]+nodes[8:])
        changed=dict(parts);changed['word/document.xml']=xml_bytes(tree)
        src=output/f'permutation-{i}-input.docx';dst=output/f'permutation-{i}-result.docx';ed=output/f'permutation-{i}-editorial.docx'
        write_package(src,changed);compile_document(src,dst,editorial_output=ed)
        labels=[paragraph_text(n).split('.')[0] for n in base.body_nodes(dst) if paragraph_text(n).startswith(('Постановка проблемы.','Цель.','Результаты.','Практическая значимость.'))]
        result['permutations'].append({'order':list(order),'correct':labels==['Постановка проблемы','Цель','Результаты','Практическая значимость'],'content':scientific_signature(base.body_nodes(src))==scientific_signature(base.body_nodes(dst)+base.body_nodes(ed))})
    stable=[]
    for i in range(3):stable.append(raster_hashes(render_pdf(base.CORPUS/'evaluation/north-03.docx',output/'stability'/str(i))))
    result['render_stability']={'repeats':3,'equal':all(x==stable[0] for x in stable),'hashes':stable}
    if reference:
        expected='2a299af6dea621444d6a90c9eb87c339f0a1b6baf1e8579d1ea0338d572f9e7e'
        assert base.sha(reference)==expected
        dst=output/'private-result.docx';ed=output/'private-editorial.docx'
        report=compile_document(reference,dst,editorial_output=ed)
        a=render_pdf(reference,output/'private-golden');b=render_pdf(dst,output/'private-output')
        result['private_reference']={'source_sha256':expected,'status':report['status'],'missing':report['missing'],'source_blocks':report['source_blocks'],'questions_count':len(report['questions']),'pixels':compare_pixels(a,b),'legacy_content':base.conservation(reference,dst,ed)}
    if http:result['batches']=base.http_batches(output,source)
    base.save(output/'results.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('permutations','render_stability')}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--reference',type=Path);p.add_argument('--http',action='store_true');a=p.parse_args();run(a.output,a.reference,a.http)
