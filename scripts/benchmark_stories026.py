"""Explicit known-role sections/stories probe, including first-page and PAGE field."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from test_stories026 import make
from articleflow.agent023 import extract_input,build_package,apply
from articleflow.rules023 import semantic_spans
from articleflow.roundtrip022 import neutralize
from articleflow.research import render_pdf
from articleflow.docx_engine import dump
from probe_style_equivalence024 import compare_bounded


def labels_for(content):
    labels={b['id']:'section_break' if not b['text'] else 'body' for b in content['blocks']}
    def walk(nodes,role):
        for n in nodes:
            if n['kind']=='paragraph':labels[n['id']]=role
            walk(n.get('children',[]),role)
    for story in content.get('stories',[]):walk(story['structure'],'footer' if 'footer' in story['part'] else 'header')
    return labels


def run(output):
    output.mkdir(parents=True,exist_ok=False);summary={'mode':'known_roles_not_model_trial','api_attempts':0,'cases':[]}
    for seed in (1,19):
        folder=output/str(seed);folder.mkdir();source=folder/'source.docx';make(source,seed)
        content=extract_input(source,folder/'extracted');labels=labels_for(content)
        if seed==1:
            _,conflicts=build_package([{'source':source,'content':content,'extracted':folder/'extracted','semantics':semantic_spans(source)}],[labels],{r:r for r in set(labels.values())},output/'template')
            summary['conflicts']=len(conflicts);dump(folder/'conflicts.json',conflicts)
        incoming=folder/'neutral.docx';neutralize(source,incoming);neutral_content=extract_input(incoming,folder/'alignment');assigned=labels_for(neutral_content)
        def caller(*args,**kwargs):
            response={'groups':[{'start':i,'end':i,'role':assigned[b['id']]} for i,b in enumerate(neutral_content['blocks'],1)]}
            kwargs['validate'](response);return response,{'api_attempts':0}
        result=apply(incoming,output/'template',folder/'application',{},caller=caller)
        row={'seed':seed,'status':result['status'],'unresolved':len(result['unresolved']),'stories':len(content['stories'])}
        if result.get('pdf'):
            comparison=compare_bounded(render_pdf(source,folder/'golden'),Path(result['pdf']))
            row.update(pages=comparison['golden_pages'],pixel_exact=comparison['pixel_exact'])
        summary['cases'].append(row);dump(output/'results.json',summary);print(json.dumps(row),flush=True)
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);run(p.parse_args().output)
