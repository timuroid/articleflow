"""Export aggregate repair evidence without manuscript text, code prompts or account data."""
import argparse,json
from decimal import Decimal
from pathlib import Path
from articleflow.docx_engine import dump
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--artifacts',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
def costs(folder):
    rows=[json.loads(p.read_text()) for p in folder.rglob('meta.json')]
    return {'api_attempts':sum(r.get('api_attempts',0) for r in rows),'known_cost_usd':str(sum((Decimal(str(r.get('cost_usd') or 0)) for r in rows),Decimal(0))),'unknown_cost_attempts':sum(r.get('api_attempts',0) for r in rows if r.get('cost_usd') is None)}
def probe(r):
    return {k:r[k] for k in ['id','split','passed','conflicts','status','code','unresolved_count','codes'] if k in r}|{'pixel_exact':r.get('pixels',{}).get('pixel_exact'),'property_exact':r.get('format',{}).get('property_exact')}
rows=[]
for path in sorted(a.artifacts.glob('repair034*/repair/report.json')):
    r=json.loads(path.read_text());root=path.parent.parent
    rows.append({'series':root.name,**{k:r.get(k) for k in ['status','seconds','image','tests']},**costs(root),'baseline':[probe(x) for x in r.get('baseline',[])],
      'attempts':[{'number':x['number'],'status':x['status'],'code':x.get('code'),'retained_for_next_attempt':x.get('retained_for_next_attempt',False),'development':[probe(t) for t in x.get('development',[])],'sealed':[probe(t) for t in x.get('sealed',[])]} for x in r['attempts']]})
applications=[]
for folder in [a.artifacts/'repair034-fresh-osu',*sorted(a.artifacts.glob('managed034*-live/run'))]:
    if not (folder/'result.json').exists():continue
    r=json.loads((folder/'result.json').read_text());repair=r.get('engine_repair',{})
    applications.append({'series':folder.parent.name if folder.name=='run' else folder.name,'status':r['status'],'code':r.get('code'),'final_learning_seconds':r.get('elapsed_seconds'),'certification':r.get('certification'),'repair_status':repair.get('status'),'repair_seconds':repair.get('seconds'),'iterations':len(r.get('iterations',[])),**costs(folder)})
replay_path=a.artifacts/'repair034-binding-replay/document-1-normal/probe.json'
replay={'api_attempts':0,'mode':'saved_candidate_replay_with_reextraction'}
if replay_path.exists():replay.update(probe(json.loads(replay_path.read_text())))
r={'schema':'public-repair-study-034','repair_trials':rows,'fresh_or_managed_trials':applications,'binding_replay':replay,
'interpretation':'Fault-injection/replay experiments use frozen student outputs. Fresh/managed trials use new semantic calls. Series overlap: wall times are not isolated latency. Partial candidate progress is not certification. An undisclosed corpus is not proof of universal correctness.'}
dump(a.output,r)
