"""Explicit paid convergence study of the built-in controller, no manual repair."""
import argparse,json,time
from pathlib import Path
from decimal import Decimal
from articleflow.agent028 import run
from articleflow.docx_engine import dump,digest


def experiment(args):
    args.output.mkdir(parents=True,exist_ok=False)
    definitions=json.loads(args.sources.read_text())['documents']
    selected=[r for r in definitions if r['status']=='downloaded' and (not args.only or r['id'] in args.only)]
    protocol={'series':'028','max_iterations':args.iterations,'teacher':'openai/gpt-6.1-sol','student':'qwen/qwen3.8-27b','manual_feedback':False,'manual_repairs':False,'separate_runs_for_each_iteration_limit':False,'source_manifest_sha256':digest(args.sources.read_bytes()),'implementation_hashes':{p.name:digest(p.read_bytes()) for p in (Path(__file__).resolve().parents[1]/'src/articleflow').glob('*.py')}}
    dump(args.output/'protocol.json',protocol)
    config={'key_file':str(args.key_file.resolve()),'ledger':str(args.ledger.resolve()),'series':'028'}
    summary={'protocol':protocol,'documents':[]}
    for item in selected:
        source=args.inputs/(item['id']+'.docx')
        if digest(source.read_bytes())!=item['sha256']:raise ValueError('SOURCE_CHANGED')
        started=time.monotonic()
        result=run([source],args.output/item['id'],{**config,'model':protocol['teacher'],'reasoning_effort':'low'},{**config,'model':protocol['student'],'reasoning_effort':'none'},max_iterations=args.iterations,max_calls=80)
        calls=result.get('call_history',[])
        row={'id':item['id'],'status':result['status'],'code':result.get('code'),'seconds':time.monotonic()-started,'first_success_iteration':next((r['number'] for r in result.get('iterations',[]) if r['status']=='passed'),None),'iterations':[{'number':r['number'],'status':r['status'],'conflicts':r.get('conflicting_groups'),'code':r.get('code'),'started_seconds':r.get('started_seconds'),'finished_seconds':r.get('finished_seconds'),'stress':[{'variant':s['variant'],'passed':s.get('passed'),'status':s.get('status'),'code':s.get('code')} for s in r.get('stress',[])]} for r in result.get('iterations',[])],'api_attempts':sum(c.get('api_attempts',0) for c in calls),'cost_usd':str(sum((Decimal(c.get('cost_usd') or 0) for c in calls),Decimal(0))),'certification':result.get('certification'),'preparation':[{'document':r['document'],'status':r.get('status'),'attempts':[{'number':a['number'],'status':a.get('status'),'code':a.get('code'),'adaptation':a.get('adaptation'),'pixel_exact':a.get('pixels',{}).get('pixel_exact')} for a in r['attempts']]} for r in result.get('preparation',[])]}
        summary['documents'].append(row);dump(args.output/'summary.json',summary);print(json.dumps(row,ensure_ascii=False),flush=True)
    summary['prefix_success']={str(limit):sum(r['first_success_iteration'] is not None and r['first_success_iteration']<=limit for r in summary['documents']) for limit in (1,2,3,5,8) if limit<=args.iterations}
    dump(args.output/'summary.json',summary)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('sources','inputs','output','key-file','ledger'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--iterations',type=int,choices=range(1,9),default=8);p.add_argument('--only',nargs='*')
    experiment(p.parse_args())
