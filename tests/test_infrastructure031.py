import unittest
from pathlib import Path
from articleflow.infrastructure031 import recover
from articleflow.docx_engine import DocumentError

class InfrastructureTests(unittest.TestCase):
    def test_transient_error_retries_same_call_with_distinct_evidence_directories(self):
        directories=[];sleeps=[];events=[]
        def invoke(path):
            directories.append(path.name)
            if len(directories)<3:raise DocumentError('PROVIDER_HTTP_429')
            return {'groups':[]},{'cost_usd':'0.01'}
        result,meta=recover(invoke,Path('/tmp/student'),sleep=sleeps.append,on_retry=events.append)
        self.assertEqual(directories,['student','student-transport-2','student-transport-3'])
        self.assertEqual(sleeps,[5,15]);self.assertEqual(meta['transport_attempts'],3)
        self.assertEqual(meta['response_directory_name'],directories[-1]);self.assertEqual(len(events),2)

    def test_invalid_answer_and_budget_are_not_transport_retries(self):
        for code in ['QUESTION_SCHEMA','MODEL_INCOMPLETE','BUDGET_EXCEEDED','PROVIDER_HTTP_400']:
            attempts=[]
            def invoke(path):attempts.append(path);raise DocumentError(code)
            with self.assertRaisesRegex(DocumentError,code):recover(invoke,Path('/tmp/student'),sleep=lambda _:self.fail('unexpected retry'))
            self.assertEqual(len(attempts),1)

    def test_repeated_outage_stops(self):
        attempts=[]
        def invoke(path):attempts.append(path);raise DocumentError('PROVIDER_HTTP_503')
        with self.assertRaisesRegex(DocumentError,'PROVIDER_HTTP_503'):recover(invoke,Path('/tmp/student'),sleep=lambda _:None)
        self.assertEqual(len(attempts),3)
