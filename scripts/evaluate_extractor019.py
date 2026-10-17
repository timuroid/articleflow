"""Explicit paid teacher -> portable template -> student development evaluation."""
import argparse
import json
from pathlib import Path
import benchmark_web017 as baseline
from evaluate_models019 import run
from articleflow.model019 import plan_document, save_private
from articleflow.structure017 import inventory, inspect_templates


def evaluate(extractor_config, student_config, output):
    output.mkdir(parents=True,exist_ok=False)
    cfg=json.loads(extractor_config.read_text());manifest=json.loads((baseline.CORPUS/'manifest.json').read_text())
    profiles={};rows=[]
    for family in manifest['styles']:
        paths=[baseline.CORPUS/e['path'] for e in manifest['entries'] if e['split']=='train' and e['style']==family]
        preliminary=inspect_templates(paths);plans={}
        for path in paths:
            inv=inventory(path)
            roles,contexts,meta=plan_document(inv['blocks'],preliminary['styles'],cfg,output/(family+'-'+path.stem))
            plans[inv['source_sha256']]={'assignments':roles,'contexts':contexts}
            rows.append({'id':path.stem,**meta});save_private(output/'extractor-results.json',{'rows':rows})
        spec=inspect_templates(paths,plans)
        selected={r:sorted(v,key=lambda k:(-len(v[k]),k))[0] for r,v in spec['variants'].items()}
        profiles[family]={r:spec['styles'][r][key] for r,key in selected.items()}
        save_private(output/(family+'-spec.json'),spec)
    save_private(output/'profiles.json',profiles)
    run(student_config,output/'student',profiles=output/'profiles.json')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--extractor-config',type=Path,required=True);p.add_argument('--student-config',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    evaluate(a.extractor_config,a.student_config,a.output)
