"""Paid autonomous template experiment on a private DOCX; raw evidence stays local."""
import argparse,json,time
from contextlib import nullcontext
from decimal import Decimal
from pathlib import Path
from articleflow.managed034 import run
from articleflow.docx_engine import dump,digest
from articleflow.sandbox034 import Engine,file_hashes,use

p=argparse.ArgumentParser(description=__doc__)
for name in ('source','output','key-file','ledger'):p.add_argument('--'+name,required=True,type=Path)
p.add_argument('--iterations',type=int,default=3,choices=range(1,9))
p.add_argument('--max-calls',type=int,default=20)
p.add_argument('--teacher-effort',default='low',choices=('none','low','medium','high'))
p.add_argument('--visual-model',default='inclusionai/ling-3.0-flash-vl')
p.add_argument('--repair-image',default=None)
p.add_argument('--engine-source',type=Path,help='Frozen prior candidate engine for a research continuation')
p.add_argument('--series',default='036-owner-reference')
a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
protocol={'schema':'owner-template-experiment-036','source_sha256':digest(a.source.read_bytes()),
          'source_bytes':a.source.stat().st_size,'teacher_model':'openai/gpt-6.1-sol',
          'student_model':'qwen/qwen3.8-27b','iterations':a.iterations,'max_calls':a.max_calls,
          'teacher_effort':a.teacher_effort,'visual_model':a.visual_model,
          'visual_review':True,'triage_conflicts':True,'repair_image_enabled':bool(a.repair_image),
          'source_code_hashes':{x.name:digest(x.read_bytes()) for x in (Path(__file__).resolve().parents[1]/'src/articleflow').glob('*.py')}}
if a.engine_source:
    protocol['prior_candidate_hashes']=file_hashes(a.engine_source)
dump(a.output/'protocol.json',protocol)
private={'key_file':str(a.key_file.resolve()),'ledger':str(a.ledger.resolve()),'series':a.series}
started=time.monotonic()
last_stage=None
def progress(report):
    global last_stage
    stage=report.get('stage')
    if stage!=last_stage:
        last_stage=stage
        rows=report.get('iterations',[])
        print(json.dumps({'stage':stage,'iteration':len(rows),
                          'conflicts':rows[-1].get('conflicting_groups') if rows else None,
                          'status':report.get('status')},ensure_ascii=False),flush=True)
engine=Engine(a.engine_source,a.repair_image) if a.engine_source else None
with use(engine) if engine else nullcontext():
    result=run([a.source],a.output/'run',
               {**private,'model':protocol['teacher_model'],'reasoning_effort':a.teacher_effort,
                'visual_model':a.visual_model,'visual_review':True,'triage_conflicts':True},
               {**private,'model':protocol['student_model'],'reasoning_effort':'none','inline_repair_attempts':1},
               max_iterations=a.iterations,max_calls=a.max_calls,repair_image=a.repair_image,
               progress=progress)
meta=[json.loads(x.read_text()) for x in (a.output/'run').rglob('meta.json')]
iterations=[]
for row in result.get('iterations',[]):
    iterations.append({'number':row.get('number'),'status':row.get('status'),'code':row.get('code'),
                       'training_conflicts':row.get('conflicting_groups'),'student_skipped':row.get('student_skipped'),
                       'applications':[{'status':x.get('status'),'unresolved_count':len(x.get('unresolved',[])),
                                        'pixel_exact':x.get('pixels',{}).get('pixel_exact'),'property_exact':x.get('format',{}).get('property_exact')} for x in row.get('applications',[])],
                       'stress':[{'variant':x.get('variant'),'status':x.get('status'),'passed':x.get('passed'),
                                  'pixel_exact':x.get('pixels',{}).get('pixel_exact')} for x in row.get('stress',[])]})
summary={'schema':'owner-template-experiment-036-summary','source_sha256':protocol['source_sha256'],
         'status':result['status'],'code':result.get('code'),'last_stage':result.get('last_stage'),
         'seconds':round(time.monotonic()-started,3),'iterations':iterations,
         'api_attempts':sum(x.get('api_attempts',0) for x in meta),
         'known_cost_usd':str(sum((Decimal(str(x['cost_usd'])) for x in meta if x.get('cost_usd') is not None),Decimal(0))),
         'unknown_cost_attempts':sum(x.get('api_attempts',0) for x in meta if x.get('cost_usd') is None),
         'repair_status':result.get('engine_repair',{}).get('status'),
         'certification':result.get('certification')}
dump(a.output/'summary.json',summary)
print(json.dumps(summary,ensure_ascii=False),flush=True)
