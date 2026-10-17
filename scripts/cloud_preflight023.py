"""Read-only cloud readiness inventory. Never reads keys or calls a model."""
import importlib.metadata
import json
import os
import shutil
import subprocess
from pathlib import Path

root=Path(__file__).resolve().parents[1]
def command(args):
    p=subprocess.run(args,cwd=root,capture_output=True,text=True,timeout=20)
    return p.stdout.strip() if p.returncode==0 else None
result={'schema':'cloud-preflight-023','commit':command(['git','rev-parse','HEAD']),
        'branch':command(['git','branch','--show-current']),
        'external_calls':0,'dependencies':{},'fonts':{},'render_engine':None}
for name in ('lxml','python-docx','Pillow','PyMuPDF','numpy','httpx','jsonschema','fastapi','uvicorn','behave'):
    try:result['dependencies'][name]=importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:result['dependencies'][name]=None
soffice=os.environ.get('ARTICLEFLOW_SOFFICE') or shutil.which('soffice')
if soffice:result['render_engine']=command([soffice,'--version'])
if shutil.which('fc-match'):
    for font in ('Arial','Times New Roman'):result['fonts'][font]=command(['fc-match','--format','%{family}',font])
result['private_reference_present']=(root/'private-fixtures/reference.docx').is_file()
result['model_configuration_present']=bool(os.environ.get('ARTICLEFLOW_MODEL_CONFIG'))
result['notes']=['Missing fonts or engine means exact-pixel results are not established.',
                 'No ledger is created or reset. Do not use a copied ledger for paid calls.',
                 'Run offline tests and both implemented feature files before experiments.']
print(json.dumps(result,ensure_ascii=False,indent=2))
