"""Explicit paid agent experiment; uses a pre-existing budget ledger."""
import argparse
import json
from pathlib import Path
from articleflow.agent023 import run

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference',type=Path,action='append',required=True)
    p.add_argument('--config',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--teacher',default='openai/gpt-6.1-sol')
    p.add_argument('--student',default='qwen/qwen3.8-27b')
    p.add_argument('--iterations',type=int,default=3)
    p.add_argument('--resume',type=Path)
    a=p.parse_args();base=json.loads(a.config.read_text())
    result=run(a.reference,a.output,{**base,'model':a.teacher,'reasoning_effort':'low'},
               {**base,'model':a.student,'reasoning_effort':'none'},max_iterations=a.iterations,resume_from=a.resume,
       progress=lambda r:print(json.dumps({'status':r['status'],'iteration':len(r['iterations']),
                    'applications':len(r['iterations'][-1]['applications']) if r['iterations'] else 0,'code':r.get('code')}),flush=True))
    print(json.dumps({'status':result['status'],'seconds':result['seconds'],'code':result.get('code')}))
