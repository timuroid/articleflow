"""Explicit paid teacher/student trial on authored DOCX; requires an existing ledger.

No ledger initialization/reset and no implicit retries. Never use in ordinary CI.
"""
import argparse,json
from pathlib import Path
from benchmark_long025 import generate
from articleflow.agent023 import run,apply
from articleflow.roundtrip022 import neutralize
from articleflow.research import render_pdf
from articleflow.docx_engine import dump
from probe_style_equivalence024 import compare_bounded


def experiment(args):
    registry=json.loads((Path(__file__).resolve().parents[1]/'docs/research/models.json').read_text())
    approved={m['id'] for m in registry['models'] if m.get('release_date','')>'2026-06-30'}
    if args.teacher not in approved or args.student not in approved:raise ValueError('Model needs verified registry entry')
    state=json.loads(args.ledger.read_text())
    if state.get('read_only'):raise ValueError('Active writer ledger required')
    if not args.key_file.is_file():raise ValueError('Key file missing')
    args.output.mkdir(parents=True,exist_ok=False)
    common={'key_file':str(args.key_file.resolve()),'ledger':str(args.ledger.resolve()),'series':'026'}
    teacher={**common,'model':args.teacher,'reasoning_effort':'low'}
    student={**common,'model':args.student,'reasoning_effort':'none'}
    sources=[]
    for seed in (1,2):
        source=args.output/f'reference-{seed}.docx';generate(source,'typography',seed);sources.append(source)
    # Generator labels are deliberately NOT passed to the agent or student.
    report=run(sources,args.output/'learning',teacher,student,max_iterations=args.iterations)
    summary={'series':'026','mode':'live_provider_protocol','teacher':args.teacher,'student':args.student,
             'training_status':report['status'],'held_out':[],'known_roles_supplied':False}
    dump(args.output/'summary.json',summary)
    if report['status']=='reference_verified':
        for seed in (23,31):
            source=args.output/f'heldout-{seed}.docx';generate(source,'typography',seed)
            neutral=args.output/f'heldout-{seed}-neutral.docx';neutralize(source,neutral)
            result=apply(neutral,Path(report['template']),args.output/f'application-{seed}',student)
            row={'seed':seed,'status':result['status'],'unresolved':len(result['unresolved']),'model':result['model']}
            if result.get('pdf'):
                pixels=compare_bounded(render_pdf(source,args.output/f'golden-{seed}'),Path(result['pdf']))
                row.update(pages=pixels['golden_pages'],pixel_exact=pixels['pixel_exact'],differing_pixel_ratio=pixels['differing_pixel_ratio'])
            summary['held_out'].append(row);dump(args.output/'summary.json',summary)
    meta=[json.loads(p.read_text()) for p in args.output.rglob('meta.json')]
    summary['api_attempts']=sum(m.get('api_attempts',0) for m in meta)
    summary['fresh_model_responses']=sum(m.get('status')=='valid' for m in meta)
    dump(args.output/'summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('ledger','key-file','output'):p.add_argument('--'+name,required=True,type=Path)
    p.add_argument('--teacher',default='openai/gpt-6.1-sol');p.add_argument('--student',default='qwen/qwen3.8-27b')
    p.add_argument('--iterations',type=int,choices=range(1,6),default=2)
    experiment(p.parse_args())
