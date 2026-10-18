"""Resume only the invalid inline rows of a saved real student response.

The first answer is read from a private prior experiment. This is a diagnostic
continuation, not a fresh one-pass student result or template certification.
"""
import argparse
import json
from pathlib import Path

from articleflow.agent023 import apply
from articleflow.docx_engine import DocumentError, digest, dump
from articleflow.provider023 import call


p = argparse.ArgumentParser(description=__doc__)
for name in ('source', 'template', 'response', 'output', 'key-file', 'ledger'):
    p.add_argument('--' + name, required=True, type=Path)
p.add_argument('--model', default='qwen/qwen3.8-27b')
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=False)
raw = json.loads(a.response.read_text())
first = json.loads(raw['choices'][0]['message']['content'])
dump(a.output/'protocol.json', {
    'schema': 'inline-correction-replay-036',
    'source_sha256': digest(a.source.read_bytes()),
    'template_sha256': digest((a.template/'semantic.json').read_bytes()),
    'prior_response_sha256': digest(a.response.read_bytes()),
    'model': a.model,
    'first_answer_origin': 'saved_prior_paid_response',
    'fresh_first_pass': False,
})
config = {'model': a.model, 'reasoning_effort': 'none',
          'key_file': str(a.key_file), 'ledger': str(a.ledger),
          'series': '036-owner-inline-correction', 'inline_repair_attempts': 1}
calls = 0


def saved_then_live(conf, messages, directory, **kwargs):
    global calls
    calls += 1
    if calls == 1:
        return kwargs['validate'](first), {'api_attempts': 0, 'mode': 'saved_response'}
    return call(conf, messages, directory, **kwargs)


try:
    result = apply(a.source, a.template, a.output/'application', config,
                   caller=saved_then_live)
    summary = {'schema': 'inline-correction-replay-036-summary',
               'status': result['status'],
               'first_pass': result['first_pass'],
               'inline_repair': result['inline_repair'],
               'unresolved_count': len(result['unresolved']),
               'model_invocations_including_saved': result['model_invocations'],
               'fresh_api_attempts': max(0, calls-1),
               'strict_one_pass_eligible': False,
               'rendered': (a.output/'application/result.docx').exists()}
except DocumentError as exc:
    summary = {'schema': 'inline-correction-replay-036-summary',
               'status': 'failed', 'code': str(exc),
               'model_invocations_including_saved': calls,
               'fresh_api_attempts': max(0, calls-1),
               'strict_one_pass_eligible': False,
               'rendered': False}
meta = a.output/'application/student-inline-repair/meta.json'
if meta.exists():
    item = json.loads(meta.read_text())
    summary['fresh_api_attempts'] = item.get('api_attempts', summary['fresh_api_attempts'])
    summary['known_cost_usd'] = item.get('cost_usd')
dump(a.output/'summary.json', summary)
print(json.dumps(summary, ensure_ascii=False))
