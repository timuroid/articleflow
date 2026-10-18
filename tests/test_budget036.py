"""Offline tests for an explicit recovery epoch after loss of the old ledger."""
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from articleflow import provider023
from articleflow import model019
from articleflow.docx_engine import DocumentError


class RecoveryBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ledger = self.root/'ledger.json'
        self.key_file = self.root/'missing-key'

    def provision(self, *, cap='4', usage='20', available='4', verified=True):
        with patch.object(provider023, 'read_key', return_value='synthetic-key'), \
                patch.object(provider023, 'account', return_value={
                    'usage_usd': usage, 'available_usd': available, 'at': '2026-10-18T00:00:00Z'}):
            return provider023.initialize_recovery_epoch(
                self.key_file, self.ledger, requested_cap_usd=cap,
                single_writer_verified=verified)

    def topup(self, added='10', *, usage='20', available='14', verified=True):
        with patch.object(provider023, 'read_key', return_value='synthetic-key'), \
                patch.object(provider023, 'account', return_value={
                    'usage_usd': usage, 'available_usd': available, 'at': '2026-10-18T00:02:00Z'}):
            return provider023.extend_recovery_epoch(
                self.key_file, self.ledger, added_cap_usd=added,
                single_writer_verified=verified)

    def call(self, *, usage='20', available='4', error=False, pricing=None,
             model_extra=None, messages=None):
        endpoints = []
        pricing = pricing if pricing is not None else {
            'prompt': '0.00000001', 'completion': '0.00000001'}
        model = {'id': 'synthetic-model', 'pricing': pricing, **(model_extra or {})}

        def api(key, endpoint, body=None):
            endpoints.append(endpoint)
            if endpoint == 'models':
                return 200, {'data': [model]}
            if error:
                return 429, {'error': {'message': 'rate limited'}}
            return 200, {'choices': [{'finish_reason': 'stop',
                                      'message': {'content': '{"ok":true}'}}],
                         'usage': {'cost': '0.001'}}

        with patch.object(provider023, 'read_key', return_value='synthetic-key'), \
                patch.object(provider023, 'account', return_value={
                    'usage_usd': usage, 'available_usd': available, 'at': '2026-10-18T00:01:00Z'}), \
                patch.object(provider023, 'api', side_effect=api):
            try:
                result = provider023.call({'key_file': str(self.key_file),
                                           'ledger': str(self.ledger),
                                           'model': 'synthetic-model'},
                                          messages if messages is not None else [],
                                          self.root/('run-'+str(len(list(self.root.glob('run-*'))))),
                                          max_tokens=256)
            except DocumentError as exc:
                result = str(exc)
        return result, endpoints

    def test_recovery_requires_single_writer_and_preserves_prior_evidence(self):
        with patch.object(provider023, 'account') as account:
            with self.assertRaisesRegex(DocumentError, 'LEDGER_RECOVERY_WRITER_UNVERIFIED'):
                provider023.initialize_recovery_epoch(self.key_file, self.ledger,
                                                       single_writer_verified=False)
            account.assert_not_called()
        result = self.provision()
        state = json.loads(self.ledger.read_text())
        self.assertEqual(state['schema'], provider023.RECOVERY_SCHEMA)
        self.assertEqual(state['baseline']['usage_usd'], '20')
        self.assertEqual(state['additional_cap_usd'], '4')
        self.assertEqual(result['carry_unsettled_reserve_usd'], '0.11889544')
        self.assertEqual(state['legacy']['observed_api_attempts'], 155)
        self.assertEqual(state['legacy']['observed_known_cost_usd'], '7.968487417')
        self.assertEqual(state['legacy']['coverage'], 'incomplete')
        original = self.ledger.read_bytes()
        with self.assertRaisesRegex(DocumentError, 'LEDGER_ALREADY_EXISTS'):
            self.provision()
        self.assertEqual(self.ledger.read_bytes(), original)

    def test_new_cap_is_bounded_by_live_balance_and_four_dollars(self):
        with self.assertRaisesRegex(DocumentError, 'INVALID_BUDGET'):
            self.provision(cap='4.01')
        self.provision(cap='4', available='0.5')
        self.assertEqual(json.loads(self.ledger.read_text())['additional_cap_usd'], '0.5')

    def test_topup_preserves_legacy_baseline_attempts_and_enables_call(self):
        self.provision()
        first, _ = self.call()
        self.assertEqual(first[0], {'ok': True})
        before = json.loads(self.ledger.read_text())
        # Existing private ledgers predate initial_cap_usd/topups.
        before.pop('initial_cap_usd')
        before.pop('topups')
        self.ledger.write_text(json.dumps(before))
        outcome = self.topup(usage='20.001', available='13.999')
        self.assertEqual(outcome['previous_cap_usd'], '4')
        self.assertEqual(outcome['new_cap_usd'], '14')
        self.assertEqual(outcome['verified_balance_increase_usd'], '10.000')
        after = json.loads(self.ledger.read_text())
        self.assertEqual(after['initial_cap_usd'], '4')
        self.assertEqual(after['additional_cap_usd'], '14')
        self.assertEqual(after['baseline'], before['baseline'])
        self.assertEqual(after['attempts'], before['attempts'])
        self.assertEqual(after['legacy'], before['legacy'])
        self.assertEqual(after['carry_unsettled_reserve_usd'], before['carry_unsettled_reserve_usd'])
        self.assertEqual(len(after['topups']), 1)
        next_result, endpoints = self.call(usage='20.001', available='13.999')
        self.assertEqual(next_result[0], {'ok': True})
        self.assertEqual(endpoints.count('chat/completions'), 1)
        self.assertEqual(len(json.loads(self.ledger.read_text())['attempts']), 2)

    def test_topup_requires_new_balance_and_explicit_single_writer(self):
        self.provision()
        original = self.ledger.read_bytes()
        with self.assertRaisesRegex(DocumentError, 'LEDGER_RECOVERY_WRITER_UNVERIFIED'):
            self.topup(verified=False)
        with self.assertRaisesRegex(DocumentError, 'TOPUP_BALANCE_INSUFFICIENT'):
            self.topup(available='13.99')
        with self.assertRaisesRegex(DocumentError, 'INVALID_BUDGET'):
            self.topup(added='10.01')
        self.assertEqual(self.ledger.read_bytes(), original)

    def test_repeated_topup_cannot_reuse_same_balance_increase(self):
        self.provision()
        self.topup(added='5', available='14')
        after = self.ledger.read_bytes()
        with self.assertRaisesRegex(DocumentError, 'TOPUP_BALANCE_INSUFFICIENT'):
            self.topup(added='5', available='14')
        self.assertEqual(self.ledger.read_bytes(), after)

    def test_usage_cannot_regress_below_last_topup_snapshot(self):
        self.provision()
        self.topup(usage='20.5', available='13.5')
        outcome, endpoints = self.call(usage='20.4', available='13.5')
        self.assertEqual(outcome, 'LEDGER_USAGE_REGRESSED')
        self.assertNotIn('chat/completions', endpoints)

    def test_forged_cap_or_topup_chain_fails_closed(self):
        self.provision()
        state = json.loads(self.ledger.read_text())
        state['additional_cap_usd'] = '14'
        self.ledger.write_text(json.dumps(state))
        outcome, endpoints = self.call()
        self.assertEqual(outcome, 'LEDGER_RECOVERY_INVALID')
        self.assertNotIn('chat/completions', endpoints)
        with patch.object(provider023, 'account') as account:
            with self.assertRaisesRegex(DocumentError, 'LEDGER_RECOVERY_INVALID'):
                provider023.extend_recovery_epoch(self.key_file, self.ledger,
                                                  added_cap_usd='10', single_writer_verified=True)
            account.assert_not_called()
        state['additional_cap_usd'] = '4'
        self.ledger.write_text(json.dumps(state))
        self.topup()
        state = json.loads(self.ledger.read_text())
        state['topups'][0]['previous_cap_usd'] = '3'
        self.ledger.write_text(json.dumps(state))
        outcome, endpoints = self.call()
        self.assertEqual(outcome, 'LEDGER_RECOVERY_INVALID')
        self.assertNotIn('chat/completions', endpoints)

    def test_concurrent_topups_are_serialized_and_second_fails(self):
        self.provision()
        with patch.object(provider023, 'read_key', return_value='synthetic-key'), \
                patch.object(provider023, 'account', return_value={
                    'usage_usd':'20','available_usd':'14','at':'2026-10-18T00:02:00Z'}):
            def extend(_):
                try:
                    return provider023.extend_recovery_epoch(
                        self.key_file, self.ledger, added_cap_usd='5',
                        single_writer_verified=True)['new_cap_usd']
                except DocumentError as exc:
                    return str(exc)
            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(extend, range(2)))
        self.assertCountEqual(outcomes, ['9', 'TOPUP_BALANCE_INSUFFICIENT'])
        state = json.loads(self.ledger.read_text())
        self.assertEqual(state['additional_cap_usd'], '9')
        self.assertEqual(len(state['topups']), 1)

    def test_old_unknown_reserve_can_exhaust_new_epoch(self):
        self.provision(cap='0.11890')
        outcome, endpoints = self.call()
        self.assertEqual(outcome, 'BUDGET_EXCEEDED')
        self.assertNotIn('chat/completions', endpoints)
        self.assertEqual(json.loads(self.ledger.read_text())['attempts'], [])

    def test_provider_usage_delta_dominates_local_attempt_sum(self):
        self.provision(cap='0.5')
        outcome, endpoints = self.call(usage='20.4')
        self.assertEqual(outcome, 'BUDGET_EXCEEDED')
        self.assertNotIn('chat/completions', endpoints)

    def test_valid_epoch_allows_call_and_counts_its_actual_cost(self):
        self.provision(cap='0.12')
        first, endpoints = self.call()
        self.assertEqual(first[0], {'ok': True})
        self.assertEqual(endpoints.count('chat/completions'), 1)
        state = json.loads(self.ledger.read_text())
        self.assertEqual(state['attempts'][0]['cost_usd'], '0.001')
        second, endpoints = self.call()
        self.assertEqual(second[0], {'ok': True})
        third, endpoints = self.call()
        self.assertEqual(third, 'BUDGET_EXCEEDED')
        self.assertNotIn('chat/completions', endpoints)

    def test_usage_regression_fails_closed(self):
        self.provision()
        outcome, endpoints = self.call(usage='19.99')
        self.assertEqual(outcome, 'LEDGER_USAGE_REGRESSED')
        self.assertNotIn('chat/completions', endpoints)

    def test_unknown_new_cost_remains_reserved_without_erasing_legacy(self):
        self.provision()
        outcome, endpoints = self.call(error=True)
        self.assertEqual(outcome, 'PROVIDER_HTTP_429')
        self.assertEqual(endpoints.count('chat/completions'), 1)
        state = json.loads(self.ledger.read_text())
        self.assertEqual(state['carry_unsettled_reserve_usd'], '0.11889544')
        self.assertIsNone(state['attempts'][0]['cost_usd'])
        self.assertGreater(float(state['attempts'][0]['reserve_usd']), 0)

    def test_fixed_request_charge_is_reserved_before_post(self):
        self.provision(cap='0.5')
        outcome, endpoints = self.call(pricing={'prompt': '0', 'completion': '0', 'request': '1'})
        self.assertEqual(outcome, 'BUDGET_EXCEEDED')
        self.assertNotIn('chat/completions', endpoints)
        self.assertEqual(json.loads(self.ledger.read_text())['attempts'], [])

    def test_override_request_and_each_image_charge_are_reserved(self):
        self.provision(cap='2')
        pictures = [{'type': 'image_url', 'image_url': {'url': f'https://example.org/{i}.png'}}
                    for i in range(2)]
        pricing = {'prompt': '0', 'completion': '0', 'request': '0.1', 'image': '0.1',
                   'overrides': [{'min_prompt_tokens': 1024, 'request': '0.6', 'image': '0.4'}]}
        outcome, endpoints = self.call(pricing=pricing,
                                       model_extra={'context_length': 2048,
                                                    'top_provider': {'context_length': 1024}},
                                       messages=[{'role': 'user', 'content': pictures}])
        self.assertEqual(outcome[0], {'ok': True})
        self.assertEqual(endpoints.count('chat/completions'), 1)
        attempt = json.loads(self.ledger.read_text())['attempts'][0]
        self.assertEqual(attempt['reserve_usd'], '1.4')

    def test_visual_prompt_uses_context_bound_not_short_url_bytes(self):
        self.provision(cap='0.5')
        outcome, endpoints = self.call(
            pricing={'prompt': '0.001', 'completion': '0', 'image': '0'},
            model_extra={'context_length': 1024},
            messages=[{'role': 'user', 'content': [
                {'type': 'image_url', 'image_url': {'url': 'https://example.org/i.png'}}]}])
        self.assertEqual(outcome, 'BUDGET_EXCEEDED')
        self.assertNotIn('chat/completions', endpoints)

    def test_visual_uses_larger_model_context_when_top_provider_is_smaller(self):
        self.provision(cap='1.5')
        outcome, endpoints = self.call(
            pricing={'prompt': '0.001', 'completion': '0'},
            model_extra={'context_length': 2048, 'top_provider': {'context_length': 1024}},
            messages=[{'role': 'user', 'content': [
                {'type': 'image_url', 'image_url': {'url': 'https://example.org/i.png'}}]}])
        self.assertEqual(outcome, 'BUDGET_EXCEEDED')
        self.assertNotIn('chat/completions', endpoints)

    def test_visual_without_context_bound_fails_closed(self):
        self.provision()
        outcome, endpoints = self.call(
            pricing={'prompt': '0', 'completion': '0', 'image': '0.1'},
            messages=[{'role': 'user', 'content': [
                {'type': 'image_url', 'image_url': {'url': 'https://example.org/i.png'}}]}])
        self.assertEqual(outcome, 'PRICING_VISUAL_UNBOUNDED')
        self.assertNotIn('chat/completions', endpoints)

    def test_unknown_nonzero_pricing_dimension_fails_closed(self):
        self.provision()
        outcome, endpoints = self.call(
            pricing={'prompt': '0', 'completion': '0', 'audio': '0.25'})
        self.assertEqual(outcome, 'PRICING_DIMENSION_UNSUPPORTED')
        self.assertNotIn('chat/completions', endpoints)

    def test_unpriced_audio_input_fails_closed_but_dormant_web_price_is_safe(self):
        self.provision()
        outcome, endpoints = self.call(
            pricing={'prompt': '0', 'completion': '0', 'web_search': '0.01'},
            messages=[{'role': 'user', 'content': [{'type': 'input_audio', 'audio': 'data'}]}])
        self.assertEqual(outcome, 'PRICING_INPUT_UNSUPPORTED')
        self.assertNotIn('chat/completions', endpoints)
        outcome, endpoints = self.call(
            pricing={'prompt': '0', 'completion': '0', 'web_search': '0.01'})
        self.assertEqual(outcome[0], {'ok': True})
        self.assertEqual(endpoints.count('chat/completions'), 1)

    def test_invalid_recovery_record_cannot_proceed_to_completion(self):
        self.provision()
        state = json.loads(self.ledger.read_text())
        state['carry_unsettled_reserve_usd'] = '0'
        self.ledger.write_text(json.dumps(state))
        outcome, endpoints = self.call()
        self.assertEqual(outcome, 'LEDGER_RECOVERY_INVALID')
        self.assertNotIn('chat/completions', endpoints)

    def test_legacy_model019_path_cannot_bypass_recovery_reserve(self):
        self.provision()
        prompt = self.root/'prompt.txt'
        prompt.write_text('Offline test')
        with patch.object(model019, 'read_key', return_value='synthetic-key'), \
                patch.object(model019, 'account') as account, \
                patch.object(model019, 'api') as api:
            with self.assertRaisesRegex(DocumentError, 'LEDGER_SCHEMA_UNSUPPORTED'):
                model019.plan_document([], [], {'ledger': str(self.ledger),
                                                  'key_file': str(self.key_file),
                                                  'prompt': str(prompt),
                                                  'model': 'synthetic-model'},
                                       self.root/'old-planner')
            account.assert_not_called()
            api.assert_not_called()


if __name__ == '__main__':
    unittest.main()
