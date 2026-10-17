"""Explicit paid synthetic experiment. Requires private checkpoint + prompt."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import benchmark_web017 as baseline
from articleflow.model019 import plan_document, save_private
from articleflow.structure017 import inventory, inspect_templates, compile_document
from articleflow.docx_engine import DocumentError
from articleflow.research import render_pdf, compare_pixels
from articleflow.typography019 import scientific_signature


def run(config_path, output, repeats=1, model=None, profiles=None):
    config=json.loads(config_path.read_text())
    if model:config['model']=model
    output.mkdir(parents=True,exist_ok=False)
    manifest=json.loads((baseline.CORPUS/'manifest.json').read_text())
    for entry in manifest['entries']:
        if baseline.sha(baseline.CORPUS/entry['path']) != entry['sha256']:
            raise ValueError('CORPUS_HASH_MISMATCH')
    styles={}
    for family in manifest['styles']:
        spec=inspect_templates([baseline.CORPUS/e['path'] for e in manifest['entries'] if e['split']=='train' and e['style']==family])
        choices={r:sorted(v,key=lambda k:(-len(v[k]),k))[0] for r,v in spec['variants'].items()}
        styles[family]={r:spec['styles'][r][k] for r,k in choices.items()}
    if profiles is not None: styles=json.loads(profiles.read_text())
    save_private(output/'frozen.json',{'model':config['model'],'prompt_sha256':baseline.sha(config['prompt']),
                 'corpus_sha256':baseline.sha(baseline.CORPUS/'manifest.json'),'profiles':styles,'repeats':repeats,'implementation_sha256':{p.name:baseline.sha(p) for p in (baseline.ROOT/'src/articleflow').glob('*.py')},'evaluator_sha256':baseline.sha(__file__),'reasoning_effort':config.get('reasoning_effort','none')})
    rows=[]
    for repeat in range(repeats):
        for e in manifest['entries']:
            if e['kind'] not in ('source','missing_required'):continue
            src=baseline.CORPUS/e['path'];blocks=inventory(src)['blocks'];directory=output/(e['id']+f'-{repeat+1}')
            row={'id':e['id'],'repeat':repeat+1,'model':config['model']}
            try:
                assignments,contexts,meta=plan_document(blocks,styles[e['style']],config,directory)
                row.update(meta);row.update(baseline.scores(baseline.labels(e,blocks),assignments))
                target=directory/'result.docx';editorial=directory/'editorial.docx'
                report=compile_document(src,target,assignments=assignments,contexts=contexts,styles=styles[e['style']],editorial_output=editorial,approved=True,fonts_ok=True,model_assigned=True)
                row['compiler_status']=report['status'];row['missing']=report['missing']
                combined=baseline.body_nodes(target)+(baseline.body_nodes(editorial) if editorial.exists() else [])
                combined=[n for n in combined if not ''.join(n.itertext()).startswith('[ЗАПОЛНИТЬ:')]
                row['scientific_payload_exact']=scientific_signature(baseline.body_nodes(src))==scientific_signature(combined)
                if 'paired_reference' in e:
                    a=render_pdf(baseline.CORPUS/e['paired_reference'],directory/'golden')
                    b=render_pdf(target,directory/'rendered')
                    row['pixels']=compare_pixels(a,b)
            except DocumentError as error:
                if (directory/'meta.json').exists():row.update(json.loads((directory/'meta.json').read_text()))
                row['status']=str(error)
            rows.append(row);save_private(output/'results.json',{'series':'019','mode':'strict_one_pass','dataset':'synthetic-v1 development','rows':rows})
            print(json.dumps(row),flush=True)
            if row['status'] in {'BUDGET_EXCEEDED','BALANCE_CHECK_FAILED'}:return

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--repeats',type=int,default=1);p.add_argument('--model');a=p.parse_args()
    run(a.config,a.output,a.repeats,a.model)
