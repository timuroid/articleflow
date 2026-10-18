"""Paid, explicit compiler repair study. Student answers are fixed replay inputs."""
import argparse,json,subprocess
from pathlib import Path
from articleflow.sandbox034 import snapshot
from articleflow.repair034 import run
from articleflow.probes034 import create
from articleflow.managed034 import collect
from articleflow.docx_engine import dump

p=argparse.ArgumentParser(description=__doc__)
for n in ['output','key-file','ledger','artifacts']:p.add_argument('--'+n,type=Path,required=True)
p.add_argument('--case',choices=['order','inline','long'],required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
base=a.output/'seed-engine';hashes=snapshot(base);probes=create(a.output/'probes')
config={'key_file':str(a.key_file.resolve()),'ledger':str(a.ledger.resolve()),'model':'openai/gpt-6.1-sol','reasoning_effort':'low','series':'034-'+a.case}
if a.case=='order':
    old=subprocess.check_output(['git','show','ebc6ebf0ebcd37beeee1d36f44e80f599802499d:src/articleflow/order024.py'])
    (base/'order024.py').write_bytes(old);cases=probes;modules=['order024.py']
else:
    for c in probes:c['split']='sealed'
    name='tusur' if a.case=='inline' else 'canterbury'
    previous=a.artifacts/('agent032-live' if a.case=='inline' else 'agent033-general-b')/name
    manifest=json.loads((previous/'result.json').read_text())
    source=a.artifacts/('real-v027' if a.case=='inline' else 'general028')/(name+'.docx')
    cases=collect([source],previous,manifest)+probes;modules=['rules023.py','catalogue.py','typography019.py']
    if a.case=='inline':(base/'rules023.py').write_bytes(subprocess.check_output(['git','show','8d9fc27e2c8560a24f337854f2c00b6c9b3b9bd9:src/articleflow/rules023.py']))
dump(a.output/'protocol.json',{'case':a.case,'historical_regression_seed':a.case!='long','student_mode':'frozen_responses_not_new_student_trials','repair_model':config['model'],'supervisor_hashes':hashes,'independent_guard_seed':34001,'max_attempts':2})
r=run(base,cases,a.output/'repair',config,max_attempts=2,modules=modules)
summary={k:v for k,v in r.items() if k not in {'engine','profile'}};dump(a.output/'summary.json',summary);print(json.dumps({'status':r['status'],'attempts':[(x['number'],x['status'],x.get('code')) for x in r['attempts']],'seconds':r['seconds']}))
