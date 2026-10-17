"""Known inline-role ablation on new seeds; never count it as an LLM trial."""
import argparse,json
from pathlib import Path
from benchmark_long025 import generate
from articleflow.agent023 import extract_input,build_package,apply
from articleflow.rules023 import semantic_spans
from articleflow.inline026 import validate,overlay
from articleflow.roundtrip022 import neutralize
from articleflow.research import render_pdf
from articleflow.docx_engine import dump
from probe_style_equivalence024 import compare_bounded

DEFINITIONS={'variable':'Обозначение переменной вместе с непосредственно предшествующим разделяющим пробелом'}

def marks(content,labels):
    rows=[]
    for i,b in enumerate(content['blocks'],1):
        if labels[b['id']]!='body':continue
        for token in (' x',' H'):
            a=b['text'].rfind(token)
            if a<0:raise ValueError('Missing authored variable')
            rows.append({'paragraph':i,'start':a,'end':a+len(token),'quote':token,'role':'variable'})
    return rows

def run(output):
    output.mkdir(parents=True,exist_ok=False);summary={'mode':'known_inline_roles_not_model_trial','api_attempts':0,'cases':[]}
    samples=[];assignments=[]
    for seed in (1,2,23,31):
        folder=output/str(seed);folder.mkdir();source=folder/'source.docx';meta=generate(source,'typography',seed)
        content=extract_input(source,folder/'extracted');labels=meta['labels'];annotations=marks(content,labels)
        if seed in (1,2):
            samples.append({'content':content,'extracted':folder/'extracted','semantics':overlay(semantic_spans(source),validate({'inline':annotations},content['blocks'],DEFINITIONS))})
            assignments.append(labels)
            if seed==1:continue
            _,conflicts=build_package(samples,assignments,{r:r for r in set(labels.values())},output/'template',DEFINITIONS)
            summary['training_documents']=2;summary['conflicts']=len(conflicts)
        neutral=folder/'neutral.docx';neutralize(source,neutral);incoming=extract_input(neutral,folder/'alignment')
        # This generator's empty table paragraphs are retained by neutralize.
        if [b['text'] for b in incoming['blocks']]!=[b['text'] for b in content['blocks']]:raise ValueError('Alignment changed')
        def caller(*args,**kwargs):
            response={'groups':[{'start':i,'end':i,'role':labels[b['id']]} for i,b in enumerate(incoming['blocks'],1)],'inline':marks(incoming,labels)}
            kwargs['validate'](response);return response,{'api_attempts':0,'mode':'known_inline_roles'}
        result=apply(neutral,output/'template',folder/'application',{},caller=caller)
        row={'seed':seed,'split':'train' if seed==2 else 'held_out','status':result['status'],'unresolved':len(result['unresolved'])}
        if result.get('pdf'):
            pixels=compare_bounded(render_pdf(source,folder/'golden'),Path(result['pdf']))
            row.update(pages=pixels['golden_pages'],pixel_exact=pixels['pixel_exact'])
        summary['cases'].append(row);dump(output/'results.json',summary);print(json.dumps(row),flush=True)
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);run(p.parse_args().output)
