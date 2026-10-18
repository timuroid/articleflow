"""Offline integration replay of saved teacher/student outputs. No API calls."""
import argparse,json
from pathlib import Path
from articleflow.managed034 import run
from articleflow.docx_engine import dump,digest
p=argparse.ArgumentParser(description=__doc__)
for name in ('source','replay','output'):p.add_argument('--'+name,type=Path,required=True)
a=p.parse_args();calls=[]
def caller(config,messages,directory,**kwargs):
    directory=Path(directory)
    if directory.name=='teacher':saved=a.replay/'teacher/validated.json'
    elif directory.name=='student':
        parent=directory.parent
        saved=a.replay/('stress-1/'+parent.name if parent.name in {'restyled','permuted'} else parent.name)/'student/validated.json'
    else:raise RuntimeError('Unexpected call: replay cannot invent visual diagnoses or code patches')
    result=json.loads(saved.read_text());result=kwargs.get('validate',lambda x:x)(result)
    directory.mkdir(parents=True,exist_ok=False);meta={'api_attempts':0,'mode':'offline_replay','source_sha256':digest(saved.read_bytes())}
    dump(directory/'validated.json',result);dump(directory/'meta.json',meta);calls.append(meta);return result,meta
r=run([a.source],a.output,{'model':'replayed-teacher','visual_review':True},{'model':'replayed-student'},caller=caller,max_iterations=1)
reports=list(a.output.rglob('visual*/report.json'))
summary={'mode':'offline_replay_not_new_model_trial','status':r['status'],'code':r.get('code'),'source_sha256':digest(a.source.read_bytes()),'calls':calls,'visual_comparisons':len(reports),'screenshotted_page_pairs':sum(len(json.loads(x.read_text())['pages']) for x in reports),'certification':r.get('certification')}
dump(a.output/'summary035.json',summary);print(json.dumps(summary))
