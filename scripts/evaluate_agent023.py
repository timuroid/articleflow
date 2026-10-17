"""Fresh student trials on a frozen package and a withheld synthetic document."""
import argparse
import json
from pathlib import Path
from articleflow.agent023 import apply
from articleflow.docx_engine import DocumentError, dump, digest
from articleflow.roundtrip022 import neutralize
from articleflow.research import render_pdf
from articleflow.templateagent022 import compare_all

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--template',type=Path,required=True)
    p.add_argument('--config',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--repeats',type=int,default=10)
    a=p.parse_args()
    if not 1<=a.repeats<=10:raise SystemExit('REPEAT_LIMIT')
    a.output.mkdir(parents=True,exist_ok=False)
    config={**json.loads(a.config.read_text()),'model':'qwen/qwen3.8-27b','reasoning_effort':'none'}
    neutralize(a.source,a.output/'degraded.docx')
    golden=render_pdf(a.source,a.output/'golden')
    result={'schema':'held-out-023','protocol':'neutralized DOCX; emphasis, scientific objects and topology retained',
            'source_sha256':digest(a.source.read_bytes()),
            'template_sha256':digest((a.template/'rules.json').read_bytes()),
            'semantic_sha256':digest((a.template/'semantic.json').read_bytes()),
            'configuration':{'model':config['model'],'reasoning':'none','repeats':a.repeats},'rows':[]}
    dump(a.output/'results.json',result)
    for i in range(a.repeats):
        row={'attempt':i+1,'passed':False}
        try:
            r=apply(a.output/'degraded.docx',a.template,a.output/f'trial-{i+1}',config)
            row.update({k:v for k,v in r.items() if k not in {'assignments','pdf'}})
            if r.get('pdf'):
                row['pixels']=compare_all(golden,Path(r['pdf']),a.output/f'diff-{i+1}')
                row['passed']=r['content_exact'] and r['placements_exact'] and row['pixels']['pixel_exact']
        except DocumentError as exc:
            row.update(status='failed',code=str(exc))
            meta=a.output/f'trial-{i+1}/student/meta.json'
            if meta.exists():row['model']=json.loads(meta.read_text())
        result['rows'].append(row);dump(a.output/'results.json',result)
        print(json.dumps({'attempt':i+1,'passed':row['passed'],'code':row.get('code'),'status':row['status']}),flush=True)
        if row.get('code') in {'BUDGET_EXCEEDED','BALANCE_CHECK_FAILED'}:break
