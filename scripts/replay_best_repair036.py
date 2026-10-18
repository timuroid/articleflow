"""Paid controlled repair from the best saved teacher plan, without a new teacher call."""
import argparse
import json
from decimal import Decimal
from pathlib import Path

from articleflow.docx_engine import dump, digest
from articleflow.managed034 import collect, pick_replay_work
from articleflow.probes034 import create
from articleflow.repair034 import run
from articleflow.sandbox034 import file_hashes, use


p = argparse.ArgumentParser(description=__doc__)
for name in ('reference', 'previous-run', 'base-engine', 'output', 'key-file', 'ledger'):
    p.add_argument('--' + name, required=True, type=Path)
p.add_argument('--image', default='articleflow-repair034')
p.add_argument('--max-attempts', type=int, default=2, choices=(1,2,3))
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=False)
prior = json.loads((a.previous_run/'result.json').read_text())
selected = pick_replay_work(a.previous_run, len(prior.get('iterations',[])))
if selected is None:
    raise SystemExit('No validated teacher plan exists in the prior run')
cases = collect([a.reference], a.previous_run, prior)
with use(None):
    guards = create(a.output/'guards')
dump(a.output/'protocol.json', {
    'schema': 'best-teacher-repair-replay-036',
    'reference_sha256': digest(a.reference.read_bytes()),
    'selected_teacher_iteration': int(selected.name.split('-')[-1]),
    'selected_conflicts': len(json.loads((selected/'training-conflicts.json').read_text())),
    'base_engine_hashes': file_hashes(a.base_engine),
    'development_cases': len(cases),
    'sealed_cases': len([case for case in guards if case['split']=='sealed']),
    'fresh_teacher_calls': 0,
})
config = {'model':'openai/gpt-6.1-sol', 'reasoning_effort':'low',
          'key_file':str(a.key_file), 'ledger':str(a.ledger),
          'series':'036-owner-best-repair'}
report = run(a.base_engine, cases+guards, a.output/'repair', config,
             max_attempts=a.max_attempts, image=a.image)
metas = [json.loads(path.read_text()) for path in (a.output/'repair').rglob('meta.json')]
summary = {'schema':'best-teacher-repair-replay-036-summary',
           'selected_teacher_iteration':int(selected.name.split('-')[-1]),
           'status':report['status'],
           'baseline_conflicts': next((r.get('conflicts') for r in report.get('baseline',[])
                                       if r['id']=='training-only'),None),
           'attempts':[{'number':x['number'],'status':x['status'],'code':x.get('code'),
                        'development_conflicts':next((r.get('conflicts') for r in x.get('development',[])
                                                      if r['id']=='training-only'),None),
                        'sealed_passed':sum(bool(r['passed']) for r in x.get('sealed',[])),
                        'sealed_total':len(x.get('sealed',[]))} for x in report.get('attempts',[])],
           'fresh_api_attempts':sum(x.get('api_attempts',0) for x in metas),
           'known_cost_usd':str(sum((Decimal(str(x['cost_usd'])) for x in metas
                                      if x.get('cost_usd') is not None),Decimal(0))),
           'template_certified':False}
dump(a.output/'summary.json',summary)
print(json.dumps(summary,ensure_ascii=False))
