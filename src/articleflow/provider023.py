"""Budgeted JSON calls for explicit teacher/student experiments.

Shares the existing 019 ledger/lock. No reset, automatic retry or hidden repair.
Every sent request reserves its worst-case cost before network access.
"""
import fcntl
import json
import os
import time
import uuid
from decimal import Decimal
from pathlib import Path

from .docx_engine import DocumentError, digest
from .model019 import account, api, read_key, save_private


def call(config, messages, directory, *, max_tokens=8192, validate=lambda x: x):
    if not 256 <= max_tokens <= 32768:
        raise DocumentError('OUTPUT_LIMIT')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    ledger = Path(config['ledger'])
    request = {'model': config['model'], 'messages': messages, 'stream': False,
               'max_tokens': max_tokens, 'response_format': {'type': 'json_object'},
               'reasoning': {'effort': config.get('reasoning_effort', 'none'), 'exclude': True},
               'provider': {'allow_fallbacks': False, 'require_parameters': True}}
    save_private(directory/'request.json', request)
    meta = {'model': config['model'], 'request_sha256': digest(json.dumps(request, sort_keys=True).encode()),
            'api_attempts': 0, 'status': 'not_sent'}
    key = read_key(Path(config['key_file']))
    fd = os.open(ledger.with_suffix('.lock'), os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(ledger.read_text())
        if state.get('read_only'):
            raise DocumentError('LEDGER_READ_ONLY')
        balance = account(key)
        status, catalog = api(key, 'models')
        model = next((m for m in catalog.get('data', []) if m['id'] == config['model']), None)
        if status != 200 or model is None:
            raise DocumentError('MODEL_UNAVAILABLE')
        input_bound = len(json.dumps(request, ensure_ascii=False).encode())+4096
        prices = [model['pricing'], *[p for p in model['pricing'].get('overrides', [])
                                    if int(p.get('min_prompt_tokens',0)) <= input_bound]]
        def rate(names):
            values = [Decimal(str(p.get(k) or 0)) for p in prices for k in names]
            if any(not v.is_finite() or v < 0 for v in values):
                raise DocumentError('PRICING_INVALID')
            return max(values)
        # UTF-8 byte bound includes JSON and any image data; deliberately conservative.
        reserve = Decimal(input_bound)*rate(('prompt','input_cache_read','input_cache_write'))
        reserve += Decimal(max_tokens)*rate(('completion',))
        spent = sum((Decimal(str(a['cost_usd'] if a.get('cost_usd') is not None else a['reserve_usd'])) for a in state['attempts']), Decimal(0))
        delta = Decimal(balance['usage_usd'])-Decimal(state['baseline']['usage_usd'])
        if max(spent, delta)+reserve > Decimal(state['additional_cap_usd']) or reserve > Decimal(balance['available_usd']):
            raise DocumentError('BUDGET_EXCEEDED')
        attempt = {'id': uuid.uuid4().hex, 'at': balance['at'], 'model': config['model'],
                   'reserve_usd': str(reserve), 'cost_usd': None, 'status': 'reserved', 'series': config.get('series','023')}
        state['attempts'].append(attempt)
        save_private(ledger, state)
        start = time.monotonic()
        meta['api_attempts'] = 1
        try:
            status, response = api(key, 'chat/completions', request)
            save_private(directory/'response.json', response)
            meta['http_status'] = status
            cost = response.get('usage', {}).get('cost')
            if cost is not None:
                value = Decimal(str(cost))
                if value.is_finite() and value >= 0:
                    attempt['cost_usd'] = str(value)
            if status != 200:
                raise DocumentError('PROVIDER_HTTP_'+str(status))
            choice = response['choices'][0]
            if choice.get('finish_reason') != 'stop':
                raise DocumentError('MODEL_INCOMPLETE')
            result = validate(json.loads(choice['message']['content']))
            save_private(directory/'validated.json', result)
            attempt['status'] = 'valid'
        except Exception as exc:
            attempt['status'] = str(exc) if isinstance(exc, DocumentError) else 'MODEL_INVALID_RESPONSE'
        finally:
            meta.update(status=attempt['status'], cost_usd=attempt['cost_usd'], reserve_usd=str(reserve),
                        seconds=time.monotonic()-start)
            save_private(ledger, state)
            save_private(directory/'meta.json', meta)
    if meta['status'] != 'valid':
        raise DocumentError(meta['status'])
    return result, meta
