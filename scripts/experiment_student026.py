"""Explicit live student trial with a frozen, declared template provenance."""
import argparse,json
from pathlib import Path
from articleflow.agent023 import apply
from articleflow.docx_engine import DocumentError,dump
from articleflow.research import render_pdf
from probe_style_equivalence024 import compare_bounded


def experiment(args):
    config={'model':args.model,'reasoning_effort':'none','key_file':str(args.key_file.resolve()),'ledger':str(args.ledger.resolve()),'series':'026-student-isolation'}
    summary={'mode':'live_student_on_evaluator_prepared_template','model':args.model,'known_assignments_supplied':False}
    try:
        result=apply(args.input,args.template,args.output,config)
        summary.update(status=result['status'],unresolved=len(result['unresolved']),model_call=result['model'])
        if result.get('pdf'):
            pixels=compare_bounded(render_pdf(args.golden,args.output/'golden'),Path(result['pdf']))
            summary.update(pages=pixels['golden_pages'],pixel_exact=pixels['pixel_exact'],differing_pixel_ratio=pixels['differing_pixel_ratio'])
    except DocumentError as exc:summary.update(status='failed',code=str(exc))
    dump(args.output/'summary.json',summary);print(json.dumps(summary,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('key-file','ledger','input','template','golden','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--model',default='qwen/qwen3.8-27b');experiment(p.parse_args())
