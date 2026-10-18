import tempfile,unittest
from pathlib import Path
import pymupdf
from articleflow.visual035 import inspect
from articleflow.questions035 import wait

class VisualTests(unittest.TestCase):
    def pdf(self,path,texts):
        with pymupdf.open() as d:
            for text in texts:d.new_page().insert_text((72,72),text)
            d.save(path)
    def test_all_pages_missing_page_and_diagnosis_not_gate(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);self.pdf(p/'a.pdf',['same','left','extra']);self.pdf(p/'b.pdf',['same','right'])
            calls=[]
            def caller(config,messages,directory,**kwargs):
                calls.append(messages);return {'observations':['Looks fine']},{'api_attempts':0}
            r=inspect(p/'a.pdf',p/'b.pdf',p/'out',{'model':'fake'},caller)
            self.assertEqual(len(r['pages']),3);self.assertEqual(len(calls),2)
            self.assertFalse(r['all_pages_exact']);self.assertEqual(r['pages'][2]['reason'],'PAGE_MISSING')
            self.assertTrue((p/'out/0003-reference.png').exists())
            self.assertTrue((p/'out/0002-diff.png').exists())
    def test_visual_model_only_changes_model_and_keeps_same_ledger(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);self.pdf(p/'a.pdf',['Reference']);self.pdf(p/'b.pdf',['Different'])
            seen=[]
            config={'model':'openai/gpt-6.1-sol','visual_model':'inclusionai/ling-3.0-flash-vl',
                    'ledger':'shared-ledger','key_file':'shared-key','reasoning_effort':'low'}
            def caller(model_config,messages,directory,**kwargs):
                seen.append((dict(model_config),messages))
                return {'observations':['different text']},{'api_attempts':0}
            report=inspect(p/'a.pdf',p/'b.pdf',p/'out',config,caller)
            self.assertEqual(len(seen),1)
            self.assertEqual(seen[0][0]['model'],'inclusionai/ling-3.0-flash-vl')
            for field in ('ledger','key_file','reasoning_effort'):
                self.assertEqual(seen[0][0][field],config[field])
            self.assertEqual(config['model'],'openai/gpt-6.1-sol')
            self.assertFalse(report['all_pages_exact'])
    def test_timeout_is_not_consent(self):
        now=[0.];events=[];initial={'revision':0,'text':''}
        result,state=wait([{'question':'Required?'}],initial,lambda:initial,events.append,seconds=30,clock=lambda:now[0],wall=lambda:100,sleep=lambda n:now.__setitem__(0,now[0]+n))
        self.assertEqual(result,initial);self.assertEqual(state['status'],'continued_without_answer');self.assertEqual(state['waited_seconds'],30)
        self.assertEqual(events[0]['deadline_unix'],130)
    def test_answer_stops_wait(self):
        now=[0.];initial={'revision':2,'text':'old'}
        result,state=wait([],initial,lambda:{'revision':3,'text':'optional'},lambda s:None,clock=lambda:now[0],wall=lambda:0,sleep=lambda n:None)
        self.assertEqual(result['text'],'optional');self.assertEqual(state['status'],'answered')
    def test_answer_is_used_by_teacher_before_compilation(self):
        import json
        from unittest.mock import patch
        from docx import Document
        from articleflow.agent023 import run
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);d=Document();d.add_paragraph('Body');d.save(p/'source.docx');self.pdf(p/'dummy.pdf',['Body']);seen=[]
            def caller(config,messages,directory,**kwargs):
                if config['model']=='teacher':
                    seen.append(json.loads(messages[1]['content'])['observations']['user_feedback'])
                    return {'roles':{'body':'Body paragraph'},'groups':[{'start':1,'end':1,'role':'body'}],'questions':[{'role':'body','question':'Обязателен ли блок?'}]},{}
                return {'groups':[{'start':1,'end':1,'role':'body'}]},{}
            def answered(q,initial,provider,emit,**kw):
                state={'status':'answered'};emit(state);return {'revision':1,'text':'Блок необязателен'},state
            with patch('articleflow.questions035.wait',side_effect=answered),patch('articleflow.agent023.render_pdf',return_value=p/'dummy.pdf'),patch('articleflow.agent023.compare_all',return_value={'pixel_exact':True}):
                r=run([p/'source.docx'],p/'run',{'model':'teacher','question_wait_seconds':30},{'model':'student'},max_iterations=1,caller=caller,feedback_provider=lambda:{'revision':0,'text':''},acceptance_probe=lambda *a:[{'passed':False}])
            self.assertEqual(seen,['','Блок необязателен']);self.assertEqual(r['feedback_revision_applied'],1)
            self.assertTrue((p/'run/iteration-1/effective-teacher.json').exists())
