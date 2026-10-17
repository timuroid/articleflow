"""Reproduce synthetic 023 results without keys, private files, or API calls."""
import argparse,json
from pathlib import Path
from build_complex023 import build
from articleflow.agent023 import run,apply
from articleflow.docx_engine import dump
from articleflow.research import render_pdf
from articleflow.roundtrip022 import neutralize
from articleflow.templateagent022 import compare_all

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    fixtures=ROOT/'datasets/complex-v023/model-replays';summary={'api_attempts':0,'fresh_model_trials':0,'mode':'offline_replay','families':[]}
    for family,oldrun in [('article','article-final3'),('nested','nested-resume3')]:
        seeds=[1] if family=='article' else [1,2];sources=[]
        for seed in seeds:
            source=a.output/f'{family}-{seed}.docx';build(source,family,seed);sources.append(source)
        paths=[fixtures/f'{oldrun}--iteration-1--teacher.json']+[fixtures/f'{oldrun}--iteration-1--application-{i+1}--student.json' for i in range(len(sources))]
        iterator=iter(paths)
        def replay(*args,**kwargs):
            response=json.loads(next(iterator).read_text());kwargs['validate'](response)
            return response,{'api_attempts':0,'fresh_model_trial':False,'mode':'offline_replay'}
        trained=run(sources,a.output/family,{'model':'saved-teacher'},{'model':'saved-Qwen'},max_iterations=1,caller=replay)
        row={'family':family,'training':trained,'held_out':None}
        if trained['status']=='reference_verified':
            source=a.output/f'{family}-17-golden.docx';build(source,family,17)
            incoming=a.output/f'{family}-17-neutral.docx';neutralize(source,incoming)
            response=json.loads((fixtures/f'{family}-heldout1--trial-1--student.json').read_text())
            def student(*args,**kwargs):
                kwargs['validate'](response)
                return response,{'api_attempts':0,'fresh_model_trial':False,'mode':'offline_replay'}
            result=apply(incoming,Path(trained['template']),a.output/f'{family}-heldout',{},caller=student)
            if result.get('pdf'):result['pixels']=compare_all(render_pdf(source,a.output/f'{family}-golden'),Path(result['pdf']),a.output/f'{family}-diff')
            row['held_out']=result
        summary['families'].append(row);dump(a.output/'results.json',summary)
        print(json.dumps({'family':family,'training':trained['status'],'transfer_exact':bool(row['held_out'] and row['held_out'].get('pixels',{}).get('pixel_exact'))}),flush=True)
    if not all(x['training']['status']=='reference_verified' and x['held_out'] and x['held_out'].get('pixels',{}).get('pixel_exact') for x in summary['families']):raise SystemExit(1)
