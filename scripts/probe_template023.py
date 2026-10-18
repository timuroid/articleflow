"""Offline research probes; never changes the reference or calls a model.

Normalization is an experiment, NOT an approved production transformation.
The conflict probe needs the owner's private reference and saved responses.
"""
import argparse,json
from pathlib import Path
from articleflow.docx_engine import load_package,parse_xml,xml_bytes,write_package,NS,dump
from articleflow.research import render_pdf
from articleflow.templateagent022 import compare_all


def normalize(source,out):
    from articleflow.typography019 import Resolver,stable_xml,tag
    parts=load_package(source);root=parse_xml(parts['word/document.xml']);resolver=Resolver(parts)
    updates=[]
    for para in root.findall('w:body//w:p',NS):
        for run in para.findall('.//w:r',NS):
            _,props=resolver.resolve(para,run);updates.append((run,props))
    for node,props in updates:
        old=node.find(tag('rPr'))
        if old is not None:node.remove(old)
        node.insert(0,parse_xml(stable_xml(props).encode()))
    parts['word/document.xml']=xml_bytes(root);write_package(out/'normalized.docx',parts)
    result=compare_all(render_pdf(source,out/'golden'),render_pdf(out/'normalized.docx',out/'render'),out/'diff')
    dump(out/'result.json',result)
    return {'mode':'normalization_experiment','pixel_exact':result['pixel_exact'],'differing_pixel_ratio':result['differing_pixel_ratio']}


def conflicts(source,out,teacher_path,student_path):
    from articleflow.agent023 import extract_input,build_package,apply
    from articleflow.semantic023 import expand_groups
    from articleflow.rules023 import semantic_spans
    from articleflow.roundtrip022 import neutralize
    content=extract_input(source,out/'extracted')
    teacher=json.loads(teacher_path.read_text());labels=expand_groups(teacher,content['blocks'])
    _,conflict_rows=build_package([{'extracted':out/'extracted','content':content,'semantics':semantic_spans(source)}],[labels],teacher['roles'],out/'template')
    dump(out/'conflicts.json',conflict_rows);neutralize(source,out/'degraded.docx')
    response=json.loads(student_path.read_text())
    def replay(*args,**kwargs):
        kwargs['validate'](response)
        return response,{'api_attempts':0,'mode':'offline_replay','fresh_model_trial':False}
    result=apply(out/'degraded.docx',out/'template',out/'application',{},caller=replay)
    summary={'mode':'conflict_replay','api_attempts':0,'conflicts':len(conflict_rows),'unresolved':len(result['unresolved']),'status':result['status']}
    dump(out/'summary.json',summary);return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['normalize','conflicts'])
    p.add_argument('--reference',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--teacher',type=Path);p.add_argument('--student',type=Path);a=p.parse_args()
    if a.mode=='conflicts' and (a.teacher is None or a.student is None):p.error('conflicts requires --teacher and --student')
    a.output.mkdir(parents=True,exist_ok=False,mode=0o700)
    print(json.dumps(normalize(a.reference,a.output) if a.mode=='normalize' else conflicts(a.reference,a.output,a.teacher,a.student)))
