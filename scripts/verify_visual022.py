"""Run the private, bounded full-document extraction experiment without APIs."""
import argparse,json
from pathlib import Path
from articleflow.structure017 import inspect_templates
from articleflow.templateagent022 import run

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--reference',type=Path,action='append',required=True)
p.add_argument('--spec',type=Path)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--selection',type=Path)
a=p.parse_args()
spec=json.loads(a.spec.read_text()) if a.spec else inspect_templates(a.reference)
result=run(a.reference,spec,a.output,selected=json.loads(a.selection.read_text()) if a.selection else None)
print(json.dumps({'status':result['status'],'samples':len(result['samples']),'model_calls':0,'code':result.get('code')}))
raise SystemExit(0 if result['status']=='passed' else 1)
