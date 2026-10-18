"""One-pass student ablation on an already frozen synthetic template.

The target is read only by the evaluator after the model call. Raw answers
and the generated DOCX stay in an ignored output directory.
"""

from __future__ import annotations

import argparse
import json
import time
from decimal import Decimal
from pathlib import Path

from articleflow.agent023 import APPLICATION_INTEGRITY_GATES, apply
from articleflow.docx_engine import DocumentError, content_fingerprint, digest, dump
from articleflow.format032 import audit
from articleflow.research import render_pdf
from articleflow.templateagent022 import compare_all


def study(args):
    if content_fingerprint(args.input) != content_fingerprint(args.golden):
        raise ValueError('HELDOUT_CONTENT_DIFFERS')
    args.output.mkdir(parents=True, exist_ok=False)
    protocol={'schema':'frozen-student-ablation-037',
              'template_sha256':digest((args.template/'semantic.json').read_bytes()),
              'input_sha256':digest(args.input.read_bytes()),
              'golden_sha256':digest(args.golden.read_bytes()),
              'model':args.model,'reasoning_effort':args.reasoning_effort,
              'strict_one_pass':True,'runner_sha256':digest(Path(__file__).read_bytes())}
    dump(args.output/'protocol.json',protocol)
    config={'key_file':str(args.key_file.resolve()),'ledger':str(args.ledger.resolve()),
            'series':args.series,'model':args.model,'reasoning_effort':args.reasoning_effort,
            'inline_repair_attempts':0}
    started=time.monotonic();summary={'schema':'frozen-student-ablation-037-summary',
                                      'model':args.model,'status':'running'}
    try:
        trial=apply(args.input,args.template,args.output/'application',config)
        summary.update(status=trial['status'],unresolved_count=len(trial.get('unresolved',[])),
                       model_invocations=trial.get('model_invocations'),
                       strict_one_pass_eligible=trial.get('strict_one_pass_eligible'),
                       integrity_gates={k:trial.get(k) for k in APPLICATION_INTEGRITY_GATES})
        if trial.get('pdf'):
            target=args.output/'application/result.docx'
            summary['content_exact']=content_fingerprint(args.golden)==content_fingerprint(target)
            summary['property_exact']=audit(args.golden,target)['property_exact']
            pages=compare_all(render_pdf(args.golden,args.output/'golden-render'),
                              Path(trial['pdf']),args.output/'diff')
            summary['pixel_exact']=pages['pixel_exact']
            summary['pages_compared']=len(pages.get('matched_page_diagnostics',[]))
    except DocumentError as exc:
        summary.update(status='failed',code=str(exc))
    meta=list(args.output.rglob('meta.json'))
    values=[json.loads(path.read_text()) for path in meta]
    summary.update(api_attempts=sum(x.get('api_attempts',0) for x in values),
                   known_cost_usd=str(sum((Decimal(str(x['cost_usd'])) for x in values
                                           if x.get('cost_usd') is not None),Decimal(0))),
                   unknown_cost_attempts=sum(x.get('api_attempts',0) for x in values
                                             if x.get('cost_usd') is None),
                   seconds=round(time.monotonic()-started,3))
    dump(args.output/'summary.json',summary)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('input','golden','template','output','key-file','ledger'):
        parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--model',required=True)
    parser.add_argument('--reasoning-effort',default='none',choices=('none','minimal','low','medium','high'))
    parser.add_argument('--series',default='037-frozen-student-ablation')
    print(json.dumps(study(parser.parse_args()),ensure_ascii=False))
