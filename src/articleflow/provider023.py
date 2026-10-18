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


# An incomplete *observation* of the lost local ledger, not invented per-call
# history. In particular, two HTTP 429 responses have no confirmed cost.
RECOVERY_LEGACY_MINIMUM = {
    'original_baseline_usage_usd': '7.956670174',
    'last_additional_cap_usd': '10',
    'observed_api_attempts': 155,
    'observed_known_cost_usd': '7.968487417',
    'unconfirmed_reserve_usd': '0.11889544',
}
RECOVERY_SCHEMA = 'budget-recovery-036'


def _amount(value, code='LEDGER_RECOVERY_INVALID'):
    try:
        number = Decimal(str(value))
    except (ValueError, TypeError):
        raise DocumentError(code) from None
    if not number.is_finite() or number < 0:
        raise DocumentError(code)
    return number


def _recovery_legacy(legacy):
    if not isinstance(legacy, dict) or not isinstance(legacy.get('provenance'), str) or not legacy['provenance'].strip():
        raise DocumentError('LEDGER_RECOVERY_INVALID')
    if legacy.get('original_baseline_usage_usd') != RECOVERY_LEGACY_MINIMUM['original_baseline_usage_usd'] or \
            legacy.get('last_additional_cap_usd') != RECOVERY_LEGACY_MINIMUM['last_additional_cap_usd']:
        raise DocumentError('LEDGER_RECOVERY_INVALID')
    if not isinstance(legacy.get('observed_api_attempts'), int) or isinstance(legacy['observed_api_attempts'], bool) or \
            legacy['observed_api_attempts'] < RECOVERY_LEGACY_MINIMUM['observed_api_attempts']:
        raise DocumentError('LEDGER_RECOVERY_INVALID')
    for field in ('observed_known_cost_usd', 'unconfirmed_reserve_usd'):
        if _amount(legacy.get(field)) < _amount(RECOVERY_LEGACY_MINIMUM[field]):
            raise DocumentError('LEDGER_RECOVERY_INVALID')
    if legacy.get('coverage') != 'incomplete':
        raise DocumentError('LEDGER_RECOVERY_INVALID')
    return dict(legacy)


def initialize_recovery_epoch(key_file, ledger, *, requested_cap_usd='4',
                              single_writer_verified=False, legacy=None):
    """Start one new, limited epoch after loss of the old per-call ledger.

    Provisioning is an explicit operator action. It never overwrites a ledger,
    performs no completion call, and retains the minimum unresolved old reserve.
    The operator must first exclude another writer using the same provider key.
    """
    if not single_writer_verified:
        raise DocumentError('LEDGER_RECOVERY_WRITER_UNVERIFIED')
    if legacy is None:
        legacy = {**RECOVERY_LEGACY_MINIMUM, 'coverage': 'incomplete',
                  'provenance': 'Local meta.json aggregate (155 observed attempts); cloud-handoff-033/035. Original ledger lost.'}
    legacy = _recovery_legacy(legacy)
    requested = _amount(requested_cap_usd)
    if requested <= 0 or requested > Decimal('4'):
        raise DocumentError('INVALID_BUDGET')
    ledger = Path(ledger)
    ledger.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(ledger.with_suffix('.lock'), os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if ledger.exists():
            raise DocumentError('LEDGER_ALREADY_EXISTS')
        snapshot = account(read_key(Path(key_file)))
        available = _amount(snapshot.get('available_usd'), 'BALANCE_CHECK_FAILED')
        usage = _amount(snapshot.get('usage_usd'), 'BALANCE_CHECK_FAILED')
        cap = min(requested, available)
        carry = _amount(legacy['unconfirmed_reserve_usd'])
        if cap <= carry:
            raise DocumentError('BUDGET_EXCEEDED')
        baseline = {'usage_usd': str(usage), 'available_usd': str(available), 'at': snapshot['at']}
        state = {'schema': RECOVERY_SCHEMA, 'baseline': baseline,
                 'initial_cap_usd': str(cap), 'additional_cap_usd': str(cap),
                 'topups': [], 'historical_attempts_available': False,
                 'legacy': legacy, 'carry_unsettled_reserve_usd': str(carry), 'attempts': []}
        # O_EXCL prevents a concurrent provisioner from overwriting an existing
        # ledger. An interrupted write leaves a fail-closed, invalid file.
        try:
            out = os.open(ledger, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            raise DocumentError('LEDGER_ALREADY_EXISTS') from None
        with os.fdopen(out, 'w') as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        return {'baseline': baseline, 'additional_cap_usd': str(cap),
                'carry_unsettled_reserve_usd': str(carry)}


def _recovery_snapshot(value, code='LEDGER_RECOVERY_INVALID'):
    if not isinstance(value, dict) or not isinstance(value.get('at'), str) or not value['at']:
        raise DocumentError(code)
    return (_amount(value.get('usage_usd'), code),
            _amount(value.get('available_usd'), code))


def _recovery_cap_state(state):
    """Verify the original <=$4 cap and every subsequent <=$10 top-up."""
    if state.get('schema') != RECOVERY_SCHEMA or state.get('historical_attempts_available') is not False:
        raise DocumentError('LEDGER_RECOVERY_INVALID')
    legacy = _recovery_legacy(state.get('legacy'))
    carry = _amount(state.get('carry_unsettled_reserve_usd'))
    if carry < _amount(legacy['unconfirmed_reserve_usd']):
        raise DocumentError('LEDGER_RECOVERY_INVALID')
    baseline = state.get('baseline')
    previous_usage, previous_available = _recovery_snapshot(baseline)
    topups = state.get('topups', [])
    if not isinstance(topups, list):
        raise DocumentError('LEDGER_RECOVERY_INVALID')
    if 'initial_cap_usd' in state:
        initial = _amount(state['initial_cap_usd'])
    elif not topups:
        # Existing recovery ledgers predate the top-up record format.
        initial = _amount(state.get('additional_cap_usd'))
    else:
        raise DocumentError('LEDGER_RECOVERY_INVALID')
    if initial <= 0 or initial > Decimal('4') or initial > previous_available:
        raise DocumentError('LEDGER_RECOVERY_INVALID')
    cap = initial
    for entry in topups:
        if not isinstance(entry, dict) or entry.get('single_writer_verified') is not True or \
                not isinstance(entry.get('at'), str) or not entry['at']:
            raise DocumentError('LEDGER_RECOVERY_INVALID')
        before = _amount(entry.get('previous_cap_usd'))
        added = _amount(entry.get('added_cap_usd'))
        after = _amount(entry.get('new_cap_usd'))
        if before != cap or not 0 < added <= Decimal('10') or \
                after != before+added or after > initial+Decimal('10') or after > Decimal('14'):
            raise DocumentError('LEDGER_RECOVERY_INVALID')
        snapshot = entry.get('provider_snapshot')
        usage, available = _recovery_snapshot(snapshot)
        if usage < previous_usage or snapshot['at'] != entry['at']:
            raise DocumentError('LEDGER_RECOVERY_INVALID')
        credited = available+(usage-previous_usage)-previous_available
        if credited < added or _amount(entry.get('verified_balance_increase_usd')) != credited:
            raise DocumentError('LEDGER_RECOVERY_INVALID')
        cap = after
        previous_usage, previous_available = usage, available
    if _amount(state.get('additional_cap_usd')) != cap:
        raise DocumentError('LEDGER_RECOVERY_INVALID')
    return cap, carry, (previous_usage, previous_available)


def _recovery_spent(state):
    attempts = state.get('attempts')
    if not isinstance(attempts, list):
        raise DocumentError('LEDGER_RECOVERY_INVALID')
    spent = Decimal(0)
    ids = set()
    for attempt in attempts:
        if not isinstance(attempt, dict) or not isinstance(attempt.get('id'), str) or not attempt['id'] or \
                attempt['id'] in ids:
            raise DocumentError('LEDGER_RECOVERY_INVALID')
        ids.add(attempt['id'])
        reserve = _amount(attempt.get('reserve_usd'))
        cost = attempt.get('cost_usd')
        spent += reserve if cost is None else _amount(cost)
    return spent


def extend_recovery_epoch(key_file, ledger, *, added_cap_usd, single_writer_verified=False):
    """Audit a newly authorized deposit without resetting the active ledger."""
    if not single_writer_verified:
        raise DocumentError('LEDGER_RECOVERY_WRITER_UNVERIFIED')
    added = _amount(added_cap_usd, 'INVALID_BUDGET')
    if not 0 < added <= Decimal('10'):
        raise DocumentError('INVALID_BUDGET')
    ledger = Path(ledger)
    fd = os.open(ledger.with_suffix('.lock'), os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not ledger.is_file():
            raise DocumentError('LEDGER_NOT_FOUND')
        try:
            state = json.loads(ledger.read_text())
        except (OSError, ValueError):
            raise DocumentError('LEDGER_RECOVERY_INVALID') from None
        if state.get('read_only'):
            raise DocumentError('LEDGER_READ_ONLY')
        cap, carry, (previous_usage, previous_available) = _recovery_cap_state(state)
        spent = _recovery_spent(state)
        if cap+added > Decimal('14') or cap+added > _amount(state.get('initial_cap_usd', cap))+Decimal('10'):
            raise DocumentError('BUDGET_EXCEEDED')
        snapshot = account(read_key(Path(key_file)))
        usage, available = _recovery_snapshot(snapshot, 'BALANCE_CHECK_FAILED')
        if usage < previous_usage:
            raise DocumentError('LEDGER_USAGE_REGRESSED')
        baseline_usage = _amount(state['baseline']['usage_usd'])
        if max(spent, usage-baseline_usage)+carry > cap:
            raise DocumentError('LEDGER_RECOVERY_INVALID')
        credited = available+(usage-previous_usage)-previous_available
        if credited < added:
            raise DocumentError('TOPUP_BALANCE_INSUFFICIENT')
        topup = {'at': snapshot['at'], 'previous_cap_usd': str(cap),
                 'added_cap_usd': str(added), 'new_cap_usd': str(cap+added),
                 'single_writer_verified': True,
                 'provider_snapshot': {'usage_usd': str(usage), 'available_usd': str(available),
                                       'at': snapshot['at']},
                 'verified_balance_increase_usd': str(credited)}
        state.setdefault('topups', []).append(topup)
        state.setdefault('initial_cap_usd', str(cap))
        state['additional_cap_usd'] = str(cap+added)
        save_private(ledger, state)
        return {'previous_cap_usd': str(cap), 'added_cap_usd': str(added),
                'new_cap_usd': str(cap+added), 'verified_balance_increase_usd': str(credited),
                'at': snapshot['at']}


def _recovery_headroom(state, balance, spent, reserve):
    if state.get('schema') != RECOVERY_SCHEMA:
        if state.get('schema') not in (None, 'budget-checkpoint-019'):
            raise DocumentError('LEDGER_SCHEMA_UNSUPPORTED')
        delta = Decimal(balance['usage_usd'])-Decimal(state['baseline']['usage_usd'])
        return max(spent, delta)+reserve <= Decimal(state['additional_cap_usd']) and \
            reserve <= Decimal(balance['available_usd'])
    cap, carry, (last_snapshot_usage, _) = _recovery_cap_state(state)
    old_usage = _amount(state['baseline'].get('usage_usd'))
    current_usage = _amount(balance.get('usage_usd'), 'BALANCE_CHECK_FAILED')
    available = _amount(balance.get('available_usd'), 'BALANCE_CHECK_FAILED')
    if current_usage < max(old_usage, last_snapshot_usage):
        raise DocumentError('LEDGER_USAGE_REGRESSED')
    delta = current_usage-old_usage
    return max(spent, delta)+carry+reserve <= cap and carry+reserve <= available


def _image_count(messages):
    """Count all billable input images; refuse modalities we cannot bound."""
    if not isinstance(messages, list):
        raise DocumentError('PRICING_INPUT_UNSUPPORTED')
    count = 0
    for message in messages:
        if not isinstance(message, dict) or message.get('role') not in ('system', 'developer', 'user', 'assistant') or \
                set(message)-{'role', 'content', 'name'}:
            raise DocumentError('PRICING_INPUT_UNSUPPORTED')
        content = message.get('content')
        if isinstance(content, str):
            continue
        if not isinstance(content, list):
            raise DocumentError('PRICING_INPUT_UNSUPPORTED')
        for part in content:
            if not isinstance(part, dict):
                raise DocumentError('PRICING_INPUT_UNSUPPORTED')
            if part.get('type') == 'text' and set(part) == {'type', 'text'} and isinstance(part.get('text'), str):
                continue
            if part.get('type') == 'image_url' and set(part) == {'type', 'image_url'} and \
                    isinstance(part.get('image_url'), dict) and \
                    not set(part['image_url'])-{'url', 'detail'} and \
                    isinstance(part['image_url'].get('url'), str) and part['image_url']['url']:
                count += 1
                continue
            raise DocumentError('PRICING_INPUT_UNSUPPORTED')
    return count


def _catalog_reserve(model, request, max_tokens):
    """Upper-bound token, request and image charges in this text/vision API."""
    image_count = _image_count(request['messages'])
    input_bound = len(json.dumps(request, ensure_ascii=False).encode())+4096
    if image_count:
        # A remote image URL or compressed data URL does not bound its decoded
        # vision tokens. The provider's context window does. If unavailable,
        # a visual request cannot be safely admitted under a monetary cap.
        top_provider = model.get('top_provider')
        if top_provider is not None and not isinstance(top_provider, dict):
            raise DocumentError('PRICING_VISUAL_UNBOUNDED')
        contexts = [model.get('context_length'), (top_provider or {}).get('context_length')]
        try:
            contexts = [int(v) for v in contexts if v is not None]
        except (ValueError, TypeError):
            raise DocumentError('PRICING_VISUAL_UNBOUNDED') from None
        if not contexts or any(v <= 0 for v in contexts):
            raise DocumentError('PRICING_VISUAL_UNBOUNDED')
        # The router may select a provider other than top_provider. Its smaller
        # current window therefore cannot cap another provider's prompt.
        input_bound = max(contexts)
    pricing = model.get('pricing')
    if not isinstance(pricing, dict) or not isinstance(pricing.get('overrides', []), list):
        raise DocumentError('PRICING_INVALID')
    prices = [pricing]
    for override in pricing.get('overrides', []):
        if not isinstance(override, dict):
            raise DocumentError('PRICING_INVALID')
        threshold = override.get('min_prompt_tokens', 0)
        if isinstance(threshold, bool):
            raise DocumentError('PRICING_INVALID')
        try:
            threshold_int = int(threshold)
        except (ValueError, TypeError):
            raise DocumentError('PRICING_INVALID') from None
        if threshold_int < 0 or str(threshold_int) != str(threshold):
            raise DocumentError('PRICING_INVALID')
        if threshold_int <= input_bound:
            prices.append(override)

    metered = {'prompt', 'completion', 'input_cache_read', 'input_cache_write', 'request', 'image'}
    # Web search is a known separate product but this API deliberately sends
    # no tools or plugins. Any future request that enables it needs its own
    # bounded query count and should not silently reuse this estimator.
    if any(k in request for k in ('plugins', 'tools', 'tool_choice', 'web_search')):
        raise DocumentError('PRICING_INPUT_UNSUPPORTED')
    def amount(value):
        if value is None or value == '':
            return Decimal(0)
        try:
            result = Decimal(str(value))
        except (ValueError, TypeError):
            raise DocumentError('PRICING_INVALID') from None
        if not result.is_finite() or result < 0:
            raise DocumentError('PRICING_INVALID')
        return result
    for entry in prices:
        for name, value in entry.items():
            if name in metered or name in ('overrides', 'min_prompt_tokens'):
                continue
            if name == 'web_search':
                amount(value)  # No search tool is enabled by this request.
            elif amount(value):
                raise DocumentError('PRICING_DIMENSION_UNSUPPORTED')
    def rate(*names):
        return max((amount(entry.get(name)) for entry in prices for name in names), default=Decimal(0))
    return Decimal(input_bound)*rate('prompt', 'input_cache_read', 'input_cache_write') + \
        Decimal(max_tokens)*rate('completion') + rate('request') + Decimal(image_count)*rate('image')


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
        reserve = _catalog_reserve(model, request, max_tokens)
        if state.get('schema') == RECOVERY_SCHEMA:
            spent = _recovery_spent(state)
        else:
            spent = sum((Decimal(str(a['cost_usd'] if a.get('cost_usd') is not None else a['reserve_usd']))
                         for a in state['attempts']), Decimal(0))
        if not _recovery_headroom(state, balance, spent, reserve):
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
